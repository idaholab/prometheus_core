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

"""Interaction records: a specialist agent's yes/no question to the user.

Design: ``docs/design/user-approval.md``. Keys (all in Valkey, behind the backend):

- ``interaction:{id}`` -- hash with the record's fields. TTL = ``expires_at`` + 24 h,
  so an answered record stays readable for the conversation history.
- ``user:interactions:{sub}`` -- set of the user's *pending* ids.
- ``task:interaction:{task_id}`` -- the task's one pending id (``SET NX`` guard).
- ``interaction:{id}:resolved`` -- pub/sub channel; one message when the record
  leaves ``pending``. Long-polls wait on it.

Every state change is a ``WATCH``/``MULTI`` compare-and-set from ``pending``, so an
Accept racing the expiry has exactly one winner. Expiry is lazy: any read of a
pending record past ``expires_at`` resolves it to ``expired`` first, so agent and
backend clocks never have to agree.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

from redis.exceptions import WatchError
from redis.typing import FieldT

from app.contract import Interaction, InteractionResolvedBy, InteractionState
from app.redis_client import RedisClient, close_pubsub

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 16 * 1024
MAX_PENDING_PER_USER = 20
MAX_TIMEOUT_SECONDS = 3600.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_WAIT_SECONDS = 60.0
RETENTION_SECONDS = 24 * 3600
_WATCH_RETRIES = 10


def record_key(interaction_id: str) -> str:
    return f"interaction:{interaction_id}"


def resolved_channel(interaction_id: str) -> str:
    return f"interaction:{interaction_id}:resolved"


def user_pending_key(user_id: str) -> str:
    return f"user:interactions:{user_id}"


def task_pending_key(task_id: str) -> str:
    return f"task:interaction:{task_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class InteractionError(Exception):
    """A request the store refuses. ``status`` is the HTTP status the router returns."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class NotPending(Exception):
    """The record already left ``pending``; carries its actual (final) state."""

    def __init__(self, record: Interaction) -> None:
        super().__init__(record.state)
        self.record = record


@dataclass(frozen=True)
class StoredInteraction:
    """A record plus the fields that never go on the browser wire."""

    record: Interaction
    user_id: str
    agent_token_hash: str
    seq: int


@dataclass(frozen=True)
class Created:
    record: Interaction
    agent_token: str


def _to_hash(stored: StoredInteraction) -> dict[FieldT, str | int]:
    fields = {k: v for k, v in stored.record.model_dump().items() if v is not None}
    fields.update(user_id=stored.user_id, agent_token_hash=stored.agent_token_hash, seq=str(stored.seq))
    out: dict[FieldT, str | int] = {str(k): str(v) for k, v in fields.items()}
    return out


def _from_hash(raw: dict[str, Any]) -> StoredInteraction:
    record = Interaction.model_validate({k: v for k, v in raw.items() if k in Interaction.model_fields})
    return StoredInteraction(
        record=record,
        user_id=str(raw["user_id"]),
        agent_token_hash=str(raw["agent_token_hash"]),
        seq=int(raw.get("seq", 1)),
    )


class InteractionStore:
    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    # -- create ------------------------------------------------------------- #

    async def create(
        self,
        *,
        user_id: str,
        agent: str,
        conversation_id: str,
        task_id: str,
        skill: str,
        message: str,
        timeout_seconds: float,
    ) -> Created:
        if len(message.encode()) > MAX_MESSAGE_BYTES:
            raise InteractionError(413, f"message exceeds {MAX_MESSAGE_BYTES} bytes")
        if not message.strip():
            raise InteractionError(422, "message is empty")
        await self._expire_stale(user_id)
        if await self._redis.scard(user_pending_key(user_id)) >= MAX_PENDING_PER_USER:
            raise InteractionError(429, f"user already has {MAX_PENDING_PER_USER} pending requests")

        timeout = min(max(float(timeout_seconds), MIN_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)
        now = _now()
        expires = now + timedelta(seconds=timeout)
        interaction_id = "ia_" + secrets.token_hex(16)
        agent_token = secrets.token_urlsafe(32)
        ttl = int(timeout) + RETENTION_SECONDS

        # One pending request per task. The guard lives as long as the request could.
        if not await self._redis.set(task_pending_key(task_id), interaction_id, nx=True, ex=int(timeout) + 60):
            current = await self._redis.get(task_pending_key(task_id))
            if current is None or await self._pending_or_none(str(current)) is not None:
                raise InteractionError(409, "this task already has a pending request")
            # The previous request was resolved but its guard outlived it; take over.
            await self._redis.set(task_pending_key(task_id), interaction_id, ex=int(timeout) + 60)

        seq = int(await self._redis.incr(f"task:interaction-seq:{task_id}"))
        await self._redis.expire(f"task:interaction-seq:{task_id}", ttl)
        stored = StoredInteraction(
            record=Interaction(
                id=interaction_id,
                conversation_id=conversation_id,
                task_id=task_id,
                agent=agent,
                skill=skill,
                message=message,
                state="pending",
                created_at=_iso(now),
                expires_at=_iso(expires),
            ),
            user_id=user_id,
            agent_token_hash=hash_token(agent_token),
            seq=seq,
        )
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(record_key(interaction_id), mapping=_to_hash(stored))
        pipe.expire(record_key(interaction_id), ttl)
        pipe.sadd(user_pending_key(user_id), interaction_id)
        await pipe.execute()
        logger.info("Interaction %s created by %s for task %s", interaction_id, agent, task_id)
        return Created(record=stored.record, agent_token=agent_token)

    # -- read --------------------------------------------------------------- #

    async def get(self, interaction_id: str) -> Optional[StoredInteraction]:
        """The record, with a stale pending one first moved to ``expired``."""
        raw = cast(dict[str, Any], await self._redis.hgetall(record_key(interaction_id)))
        if not raw:
            return None
        stored = _from_hash(raw)
        if stored.record.state == "pending" and _parse(stored.record.expires_at) <= _now():
            try:
                return await self.resolve(interaction_id, "expired", "timeout")
            except NotPending as exc:
                return await self.get(str(exc.record.id))
        return stored

    async def _pending_or_none(self, interaction_id: str) -> Optional[StoredInteraction]:
        stored = await self.get(interaction_id)
        return stored if stored is not None and stored.record.state == "pending" else None

    async def list_pending(self, user_id: str) -> list[Interaction]:
        ids = sorted(await self._redis.smembers(user_pending_key(user_id)))
        out: list[Interaction] = []
        for raw_id in ids:
            interaction_id = str(raw_id)
            stored = await self.get(interaction_id)
            if stored is None:
                await self._redis.srem(user_pending_key(user_id), interaction_id)
            elif stored.record.state == "pending":
                out.append(stored.record)
        return sorted(out, key=lambda r: r.created_at)

    async def _expire_stale(self, user_id: str) -> None:
        await self.list_pending(user_id)

    async def get_for_agent(self, interaction_id: str, *, agent: str, agent_token: str) -> StoredInteraction:
        """The record, if ``agent`` created it and ``agent_token`` matches; else 404."""
        stored = await self.get(interaction_id)
        if (
            stored is None
            or stored.record.agent != agent
            or not hmac.compare_digest(stored.agent_token_hash, hash_token(agent_token))
        ):
            raise InteractionError(404, "No such interaction")
        return stored

    # -- resolve ------------------------------------------------------------ #

    async def resolve(
        self, interaction_id: str, state: InteractionState, by: InteractionResolvedBy
    ) -> StoredInteraction:
        """Move a pending record to ``state``. Raises :class:`NotPending` if it already left
        ``pending`` and :class:`InteractionError` (404) if it doesn't exist."""
        key = record_key(interaction_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            for _ in range(_WATCH_RETRIES):
                try:
                    await pipe.watch(key)
                    raw = cast(dict[str, Any], await pipe.hgetall(key))
                    if not raw:
                        await pipe.unwatch()
                        raise InteractionError(404, "No such interaction")
                    current = _from_hash(raw)
                    if current.record.state != "pending":
                        await pipe.unwatch()
                        raise NotPending(current.record)
                    resolved_at = _iso(_now())
                    pipe.multi()
                    pipe.hset(key, mapping={"state": state, "resolved_at": resolved_at, "resolved_by": by})
                    pipe.srem(user_pending_key(current.user_id), interaction_id)
                    await pipe.execute()
                    break
                except WatchError:
                    continue
            else:
                raise WatchError(f"{key} kept changing; gave up after {_WATCH_RETRIES} attempts")

        task_key = task_pending_key(current.record.task_id)
        if await self._redis.get(task_key) == interaction_id:
            await self._redis.delete(task_key)
        await self._redis.publish(resolved_channel(interaction_id), state)
        logger.info("Interaction %s %s (%s)", interaction_id, state, by)
        record = current.record.model_copy(update={"state": state, "resolved_at": resolved_at, "resolved_by": by})
        return StoredInteraction(record, current.user_id, current.agent_token_hash, current.seq)

    async def answer(self, interaction_id: str, *, user_id: str, accept: bool) -> Interaction:
        """The user's decision. 404 for a record the user doesn't own; NotPending if late."""
        stored = await self.get(interaction_id)
        if stored is None or stored.user_id != user_id:
            raise InteractionError(404, "No such interaction")
        if stored.record.state != "pending":
            raise NotPending(stored.record)
        return (await self.resolve(interaction_id, "accepted" if accept else "declined", "user")).record

    async def cancel_for_task(self, task_id: str, by: InteractionResolvedBy = "system") -> Optional[Interaction]:
        """Cancel the task's pending request, if any (agent gone, stream lost)."""
        interaction_id = await self._redis.get(task_pending_key(task_id))
        if interaction_id is None:
            return None
        try:
            return (await self.resolve(str(interaction_id), "cancelled", by)).record
        except (NotPending, InteractionError):
            return None

    # -- wait --------------------------------------------------------------- #

    async def wait(self, interaction_id: str, wait_seconds: float) -> Interaction:
        """Wait until the record leaves ``pending`` or ``wait_seconds`` pass; return it.

        Subscribes first, then re-reads, so a resolution between the caller's last read
        and the subscribe isn't missed. A timer bounds the wait even if a notification
        is lost; expiry is checked on every read.
        """
        wait_seconds = min(max(wait_seconds, 0.0), MAX_WAIT_SECONDS)
        channel = resolved_channel(interaction_id)
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(channel)
            stored = await self.get(interaction_id)
            if stored is None:
                raise InteractionError(404, "No such interaction")
            if stored.record.state != "pending":
                return stored.record
            # Wake for expiry even if no one answers.
            deadline = min(wait_seconds, max((_parse(stored.record.expires_at) - _now()).total_seconds(), 0.0))
            loop = asyncio.get_running_loop()
            end = loop.time() + deadline
            while (remaining := end - loop.time()) > 0:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=min(remaining, 1.0))
                if msg is not None:
                    break
            stored = await self.get(interaction_id)
            if stored is None:
                raise InteractionError(404, "No such interaction")
            return stored.record
        finally:
            await close_pubsub(pubsub, channel)
