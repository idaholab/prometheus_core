# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Agent state records: small JSON objects a specialist agent keeps between requests.

Design: Confluence 44335895 ("Request-Scoped Agent Objects and Backend Task State").
Two scopes share one record format and one set of rules:

- ``agent_state:task:{task_id}`` -- state of one A2A task, carried across an
  ``INPUT_REQUIRED`` resume.
- ``agent_state:conv:{conversation_id}:{agent}`` -- one agent's state for a whole
  conversation (replaces the agent-side Redis ``ContextStateStore``).

Each key holds a JSON document with the owner ``(user, agent, conversation)``, a
``version`` and the ``state``. Every write is a ``WATCH``/``MULTI``
compare-and-set on the version, so two racing writers can't silently overwrite each
other. Every write refreshes the TTL. Agents never reach these keys: the backend reads
and writes them with its own Valkey user, after checking the caller.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from redis.exceptions import WatchError

from app.redis_client import RedisClient

logger = logging.getLogger(__name__)

_WATCH_RETRIES = 10


class AgentStateError(Exception):
    """A request the store refuses; ``status`` is the HTTP status the router returns."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class Owner:
    """Who a record belongs to. All three must match for any access."""

    user_id: str
    agent: str
    conversation_id: str


@dataclass(frozen=True)
class StateRecord:
    state: dict[str, Any]
    version: int
    created_at: str
    updated_at: str


def task_key(task_id: str) -> str:
    return f"agent_state:task:{task_id}"


def conversation_key(conversation_id: str, agent: str) -> str:
    return f"agent_state:conv:{conversation_id}:{agent}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _owned(raw: str | bytes | None, owner: Owner) -> Optional[dict[str, Any]]:
    """The stored document when it exists and belongs to *owner*, else ``None``.

    Not-owned and absent look the same to the caller (404), so knowing a task id
    doesn't reveal that the task exists.
    """
    if not raw:
        return None
    doc: dict[str, Any] = json.loads(raw)
    if (
        doc.get("owner_user_id") != owner.user_id
        or doc.get("agent") != owner.agent
        or doc.get("conversation_id") != owner.conversation_id
    ):
        return None
    return doc


def _record(doc: dict[str, Any]) -> StateRecord:
    return StateRecord(
        state=doc["state"],
        version=int(doc["version"]),
        created_at=str(doc["created_at"]),
        updated_at=str(doc["updated_at"]),
    )


class AgentStateStore:
    def __init__(self, redis: RedisClient, *, ttl_seconds: int, max_bytes: int) -> None:
        self._redis = redis
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes

    async def get(self, key: str, owner: Owner) -> Optional[StateRecord]:
        doc = _owned(await self._redis.get(key), owner)
        return None if doc is None else _record(doc)

    async def put(
        self,
        key: str,
        owner: Owner,
        state: dict[str, Any],
        *,
        expected_version: Optional[int],
    ) -> StateRecord:
        """Create (``expected_version=None``) or replace (the stored version) a record.

        Raises 409 on a version mismatch, including create when the caller's record
        already exists. Someone else's record at the key is 404, as on read.
        """
        encoded_state = json.dumps(state, separators=(",", ":"))
        if len(encoded_state.encode()) > self.max_bytes:
            raise AgentStateError(413, f"state exceeds {self.max_bytes} bytes")

        async with self._redis.pipeline(transaction=True) as pipe:
            for _ in range(_WATCH_RETRIES):
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    doc = _owned(raw, owner)
                    if raw and doc is None:
                        await pipe.unwatch()
                        raise AgentStateError(404, "No such state")
                    current = None if doc is None else int(doc["version"])
                    if current != expected_version:
                        await pipe.unwatch()
                        if expected_version is None:
                            raise AgentStateError(409, f"state already exists at version {current}")
                        raise AgentStateError(409, f"state is at version {current}, not {expected_version}")

                    now = _iso_now()
                    new = {
                        "owner_user_id": owner.user_id,
                        "agent": owner.agent,
                        "conversation_id": owner.conversation_id,
                        "version": (current or 0) + 1,
                        "state": state,
                        "created_at": now if doc is None else doc["created_at"],
                        "updated_at": now,
                    }
                    pipe.multi()
                    pipe.set(key, json.dumps(new, separators=(",", ":")), ex=self.ttl_seconds)
                    await pipe.execute()
                    return _record(new)
                except WatchError:
                    continue
        raise AgentStateError(409, f"{key} kept changing; gave up after {_WATCH_RETRIES} attempts")

    async def delete(self, key: str, owner: Owner) -> None:
        """Remove the caller's record. Idempotent: absent or not owned is a no-op."""
        async with self._redis.pipeline(transaction=True) as pipe:
            for _ in range(_WATCH_RETRIES):
                try:
                    await pipe.watch(key)
                    if _owned(await pipe.get(key), owner) is None:
                        await pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.delete(key)
                    await pipe.execute()
                    return
                except WatchError:
                    continue
        raise AgentStateError(409, f"{key} kept changing; gave up after {_WATCH_RETRIES} attempts")
