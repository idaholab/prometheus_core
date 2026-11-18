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

"""Client for the backend's agent state API (``/v1/agent-state``).

The agent never touches Valkey: the backend stores the record, checks that the user
in the forwarded identity JWT owns the conversation, and keeps each record private
to the ``(user, agent, conversation)`` that wrote it
(``platform/docs/design/request-scoped-agent.md`` in the platform repo).

Two scopes:

- **task** -- one A2A task's state, carried across an ``INPUT_REQUIRED`` resume.
- **conversation** -- this agent's state for the whole conversation.

Every call sends ``Bearer <AGENT_SECRET>``, ``X-Agent-Name`` (ignored under Istio,
where the backend identifies the agent from its mTLS certificate) and the turn's
user identity JWT in ``X-User-Token``.

Writes are versioned: :meth:`AgentStateClient.load` returns the stored version, and
:meth:`AgentStateClient.save` must pass it back (``None`` to create). A stale
version raises :class:`AgentStateConflict` instead of overwriting a newer write.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

Scope = Literal["task", "conversation"]


class AgentStateError(RuntimeError):
    """The backend couldn't serve the state request (unreachable, auth, refused).

    Never swallowed into "no state": a request that can't load or save its state
    fails, as the execution record does.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AgentStateConflict(AgentStateError):
    """The stored version isn't the one passed to :meth:`AgentStateClient.save` (HTTP 409)."""


@dataclass(frozen=True)
class StoredState:
    state: dict[str, Any]
    version: int


class AgentStateClient:
    """Thin async client; one short-lived ``httpx.AsyncClient`` per call, like the registry client."""

    def __init__(
        self,
        base_url: str,
        *,
        agent_name: str,
        agent_secret: str,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_secret = agent_secret
        self.timeout = timeout

    @classmethod
    def from_env(cls, base_url: str, *, agent_name: str) -> AgentStateClient:
        return cls(base_url, agent_name=agent_name, agent_secret=os.getenv("AGENT_SECRET", ""))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout)

    def _target(
        self, scope: Scope, *, conversation_id: str, task_id: str | None, user_token: str
    ) -> tuple[str, dict[str, str]]:
        if not user_token:
            raise AgentStateError("no verified user identity for this turn")
        if not conversation_id:
            raise AgentStateError("conversation_id is required")
        headers = {
            "Authorization": f"Bearer {self.agent_secret}",
            "X-Agent-Name": self.agent_name,
            "X-User-Token": user_token,
        }
        if scope == "task":
            if not task_id:
                raise AgentStateError("task_id is required for task-scoped state")
            headers["X-Conversation-Id"] = conversation_id
            return f"{self.base_url}/v1/agent-state/tasks/{task_id}", headers
        return f"{self.base_url}/v1/agent-state/conversations/{conversation_id}", headers

    async def _send(
        self, method: str, url: str, headers: dict[str, str], **kwargs: Any
    ) -> httpx.Response:
        try:
            async with self._client() as client:
                return await client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentStateError(f"backend unreachable: {exc}") from exc

    async def load(
        self,
        scope: Scope,
        *,
        conversation_id: str,
        user_token: str,
        task_id: str | None = None,
    ) -> StoredState | None:
        """The stored state and its version, or ``None`` when there is none.

        The backend answers 404 both for "no state" and for "no such conversation";
        both mean there is nothing to resume from.
        """
        url, headers = self._target(
            scope, conversation_id=conversation_id, task_id=task_id, user_token=user_token
        )
        resp = await self._send("GET", url, headers)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise AgentStateError(
                f"backend refused the state read ({resp.status_code}): {_detail(resp)}",
                status=resp.status_code,
            )
        data = resp.json()
        return StoredState(state=data["state"], version=int(data["version"]))

    async def save(
        self,
        scope: Scope,
        state: dict[str, Any],
        *,
        version: int | None,
        conversation_id: str,
        user_token: str,
        task_id: str | None = None,
    ) -> int:
        """Create (``version=None``) or replace (the version :meth:`load` returned); return the new version."""
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")
        url, headers = self._target(
            scope, conversation_id=conversation_id, task_id=task_id, user_token=user_token
        )
        headers["If-None-Match" if version is None else "If-Match"] = (
            "*" if version is None else f'"{version}"'
        )
        resp = await self._send("PUT", url, headers, json={"state": state})
        if resp.status_code == 409:
            raise AgentStateConflict(f"state changed concurrently: {_detail(resp)}", status=409)
        if resp.status_code != 200:
            raise AgentStateError(
                f"backend refused the state write ({resp.status_code}): {_detail(resp)}",
                status=resp.status_code,
            )
        return int(resp.json()["version"])

    async def delete(
        self,
        scope: Scope,
        *,
        conversation_id: str,
        user_token: str,
        task_id: str | None = None,
    ) -> None:
        """Remove the state. Idempotent; a missing record or conversation is not an error."""
        url, headers = self._target(
            scope, conversation_id=conversation_id, task_id=task_id, user_token=user_token
        )
        resp = await self._send("DELETE", url, headers)
        if resp.status_code not in (204, 404):
            raise AgentStateError(
                f"backend refused the state delete ({resp.status_code}): {_detail(resp)}",
                status=resp.status_code,
            )


def _detail(resp: httpx.Response) -> Any:
    try:
        return resp.json().get("detail", resp.text)
    except ValueError:
        return resp.text
