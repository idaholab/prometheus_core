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

"""AgentStateClient against a fake /v1/agent-state backend."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from prometheus_api.agent.agent_state import (
    AgentStateClient,
    AgentStateConflict,
    AgentStateError,
    NOT_FOUND_HEADER,
)

BASE = "http://backend:8000"
CONV = "conv-1"
TOKEN = "user-jwt"


class FakeBackend:
    """Version-checked records keyed by URL path, like the backend routes."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.force_status: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.force_status is not None:
            return httpx.Response(self.force_status, json={"detail": "forced"})
        path = request.url.path
        record = self.records.get(path)
        if request.method == "GET":
            if record is None:
                return httpx.Response(
                    404, json={"detail": "No such state"}, headers={NOT_FOUND_HEADER: "state"}
                )
            return httpx.Response(200, json=record, headers={"ETag": f'"{record["version"]}"'})
        if request.method == "DELETE":
            self.records.pop(path, None)
            return httpx.Response(204)
        current = None if record is None else record["version"]
        if_match = request.headers.get("if-match")
        expected = None if request.headers.get("if-none-match") == "*" else int(if_match.strip('"'))
        if expected != current:
            return httpx.Response(409, json={"detail": f"state is at version {current}"})
        new = {"state": json.loads(request.content)["state"], "version": (current or 0) + 1}
        self.records[path] = new
        return httpx.Response(200, json={**new, "created_at": "t", "updated_at": "t"})


@pytest.fixture
def backend(monkeypatch) -> FakeBackend:
    fake = FakeBackend()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        AgentStateClient, "_client", lambda self: httpx.AsyncClient(transport=transport)
    )
    return fake


@pytest.fixture
def client() -> AgentStateClient:
    return AgentStateClient(BASE, agent_name="thermal-agent", agent_secret="s3cret")


async def test_conversation_round_trip(backend, client):
    assert await client.load("conversation", conversation_id=CONV, user_token=TOKEN) is None
    v1 = await client.save(
        "conversation", {"a": 1}, version=None, conversation_id=CONV, user_token=TOKEN
    )
    loaded = await client.load("conversation", conversation_id=CONV, user_token=TOKEN)
    assert loaded is not None and (loaded.state, loaded.version) == ({"a": 1}, v1)
    v2 = await client.save(
        "conversation", {"a": 2}, version=v1, conversation_id=CONV, user_token=TOKEN
    )
    assert v2 == v1 + 1
    await client.delete("conversation", conversation_id=CONV, user_token=TOKEN)
    assert await client.load("conversation", conversation_id=CONV, user_token=TOKEN) is None

    put = next(r for r in backend.requests if r.method == "PUT")
    assert put.url == f"{BASE}/v1/agent-state/conversations/{CONV}"
    assert put.headers["authorization"] == "Bearer s3cret"
    assert put.headers["x-agent-name"] == "thermal-agent"
    assert put.headers["x-user-token"] == TOKEN
    assert put.headers["if-none-match"] == "*"


async def test_task_scope_sends_conversation_header(backend, client):
    await client.save(
        "task",
        {"stage": "need_bc"},
        version=None,
        conversation_id=CONV,
        task_id="t-1",
        user_token=TOKEN,
    )
    (put,) = backend.requests
    assert put.url == f"{BASE}/v1/agent-state/tasks/t-1"
    assert put.headers["x-conversation-id"] == CONV


async def test_stale_version_raises_conflict(backend, client):
    v1 = await client.save("conversation", {}, version=None, conversation_id=CONV, user_token=TOKEN)
    await client.save("conversation", {"n": 1}, version=v1, conversation_id=CONV, user_token=TOKEN)
    with pytest.raises(AgentStateConflict):
        await client.save(
            "conversation", {"n": 2}, version=v1, conversation_id=CONV, user_token=TOKEN
        )
    with pytest.raises(AgentStateConflict):
        await client.save("conversation", {}, version=None, conversation_id=CONV, user_token=TOKEN)


@pytest.mark.parametrize("status", [401, 413, 500])
async def test_backend_errors_raise(backend, client, status):
    backend.force_status = status
    with pytest.raises(AgentStateError) as exc:
        await client.load("conversation", conversation_id=CONV, user_token=TOKEN)
    assert exc.value.status == status
    with pytest.raises(AgentStateError):
        await client.save("conversation", {}, version=None, conversation_id=CONV, user_token=TOKEN)
    with pytest.raises(AgentStateError):
        await client.delete("conversation", conversation_id=CONV, user_token=TOKEN)


async def test_unreachable_backend_raises(monkeypatch, client):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(refuse)
    monkeypatch.setattr(
        AgentStateClient, "_client", lambda self: httpx.AsyncClient(transport=transport)
    )
    with pytest.raises(AgentStateError, match="unreachable"):
        await client.load("conversation", conversation_id=CONV, user_token=TOKEN)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": "conversation", "conversation_id": CONV, "user_token": ""},
        {"scope": "conversation", "conversation_id": "", "user_token": TOKEN},
        {"scope": "task", "conversation_id": CONV, "user_token": TOKEN},
    ],
)
async def test_missing_identity_or_ids_fail_before_any_request(backend, client, kwargs):
    with pytest.raises(AgentStateError):
        await client.load(**kwargs)
    assert backend.requests == []


def _answer_404(monkeypatch, **kwargs: Any) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, **kwargs))
    monkeypatch.setattr(
        AgentStateClient, "_client", lambda self: httpx.AsyncClient(transport=transport)
    )


async def test_missing_conversation_raises_instead_of_empty_state(monkeypatch, client):
    _answer_404(
        monkeypatch,
        json={"detail": "No such conversation"},
        headers={NOT_FOUND_HEADER: "conversation"},
    )
    with pytest.raises(AgentStateError, match="conversation not found") as exc:
        await client.load("conversation", conversation_id=CONV, user_token=TOKEN)
    assert exc.value.status == 404
    with pytest.raises(AgentStateError, match="conversation not found"):
        await client.save("conversation", {}, version=None, conversation_id=CONV, user_token=TOKEN)
    await client.delete("conversation", conversation_id=CONV, user_token=TOKEN)  # still idempotent


async def test_404_from_something_else_raises(monkeypatch, client):
    """A wrong REGISTRY_URL (LiteLLM, say) answers 404 without the marker; that isn't "no state"."""
    _answer_404(monkeypatch, text="Not Found")
    for call in (
        client.load("conversation", conversation_id=CONV, user_token=TOKEN),
        client.save("conversation", {}, version=None, conversation_id=CONV, user_token=TOKEN),
        client.delete("conversation", conversation_id=CONV, user_token=TOKEN),
    ):
        with pytest.raises(AgentStateError, match="REGISTRY_URL"):
            await call
