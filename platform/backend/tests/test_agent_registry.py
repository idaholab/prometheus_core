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

"""/v1/agents registry and /a2a/{agent_name} gateway (app/routers/agent_registry.py)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import agent_registry as registry_mod

SECRET = "test-agent-secret"
AUTH = {"Authorization": f"Bearer {SECRET}"}

CARD = {
    "name": "Thermal Agent",
    "url": "http://thermal-agent:8000/",
    "skills": [{"id": "analyze_thermal", "inputSchema": {"type": "object"}}],
}
REGISTRATION = {
    "agent_name": "thermal-agent",
    "agent_card_params": CARD,
    "static_headers": {"Authorization": "Bearer agent-own-secret"},
}


@pytest.fixture(autouse=True)
def agent_secret(monkeypatch):
    monkeypatch.setattr(settings, "agent_secret", SECRET)


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture
def upstream(monkeypatch) -> list[httpx.Request]:
    """Route the proxy's outbound calls to an in-process fake agent; return what it saw."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if body["method"] == "SendStreamingMessage":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'data: {"n": 1}\n\ndata: {"n": 2}\n\n',
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}})

    monkeypatch.setattr(registry_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": SECRET}])
def test_rejects_missing_or_wrong_secret(client, headers):
    assert client.get("/v1/agents", headers=headers).status_code == 401
    assert client.post("/v1/agents", json=REGISTRATION, headers=headers).status_code == 401


def test_fails_closed_without_configured_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "agent_secret", "")
    assert client.get("/v1/agents", headers={"Authorization": "Bearer "}).status_code == 503


def test_register_list_delete(client):
    created = client.post("/v1/agents", json=REGISTRATION, headers=AUTH)
    assert created.status_code == 200
    assert created.json() == {"agent_id": "thermal-agent", "agent_name": "thermal-agent", "agent_card_params": CARD}

    listed = client.get("/v1/agents", headers=AUTH).json()
    # A bare list, as AgentRegistryClient and tool_discovery.discover_agents expect.
    assert listed == [created.json()]
    assert "static_headers" not in json.dumps(listed)

    assert client.delete("/v1/agents/thermal-agent", headers=AUTH).status_code == 200
    assert client.get("/v1/agents", headers=AUTH).json() == []
    assert client.delete("/v1/agents/thermal-agent", headers=AUTH).status_code == 404


def test_reregistration_overwrites(client):
    client.post("/v1/agents", json=REGISTRATION, headers=AUTH)
    moved = {**REGISTRATION, "agent_card_params": {**CARD, "url": "http://elsewhere:8000/"}}
    client.post("/v1/agents", json=moved, headers=AUTH)

    listed = client.get("/v1/agents", headers=AUTH).json()
    assert [e["agent_card_params"]["url"] for e in listed] == ["http://elsewhere:8000/"]


def test_get_card(client):
    client.post("/v1/agents", json=REGISTRATION, headers=AUTH)
    assert client.get("/a2a/thermal-agent", headers=AUTH).json() == CARD
    assert client.get("/a2a/unknown", headers=AUTH).status_code == 404


def test_proxy_forwards_with_agent_headers(client, upstream):
    client.post("/v1/agents", json=REGISTRATION, headers=AUTH)
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {}}

    resp = client.post("/a2a/thermal-agent", json=message, headers={**AUTH, "A2A-Version": "1.0"})

    assert resp.status_code == 200
    assert resp.json() == {"jsonrpc": "2.0", "id": "1", "result": {"ok": True}}
    (sent,) = upstream
    assert str(sent.url) == CARD["url"]
    # The caller's registry token is replaced by the agent's registered credentials.
    assert sent.headers["authorization"] == "Bearer agent-own-secret"
    assert sent.headers["a2a-version"] == "1.0"
    assert json.loads(sent.content) == message


def test_proxy_streams_event_stream_through(client, upstream):
    client.post("/v1/agents", json=REGISTRATION, headers=AUTH)
    message = {"jsonrpc": "2.0", "id": "1", "method": "SendStreamingMessage", "params": {}}

    resp = client.post("/a2a/thermal-agent", json=message, headers=AUTH)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.content == b'data: {"n": 1}\n\ndata: {"n": 2}\n\n'


def test_proxy_unknown_agent_404(client, upstream):
    assert client.post("/a2a/unknown", json={}, headers=AUTH).status_code == 404
    assert upstream == []


def test_proxy_unreachable_agent_502(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(registry_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client.post("/v1/agents", json=REGISTRATION, headers=AUTH)
    assert client.post("/a2a/thermal-agent", json={}, headers=AUTH).status_code == 502
