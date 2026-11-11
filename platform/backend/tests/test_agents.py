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

"""GET /api/agents and /api/agents/{agent_name} (app/routers/agents.py).

The registry is the conftest ``fake_redis`` hash; each agent's ``/healthz`` probe goes
through an ``httpx.MockTransport`` installed on the router's ``_make_client`` seam.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.routers import agents as agents_mod
from app.routers.agent_registry import REGISTRY_KEY

ALPHA_SECRET = "Bearer alpha-own-secret"
ALPHA_REGISTERED_AT = "2026-11-01T08:30:00+00:00"

# Stored as register_agent stores it: the registration body plus registered_at.
ALPHA = {
    "agent_name": "alpha-agent",
    "agent_card_params": {
        "name": "Alpha Agent",
        "description": "Thermal analysis.",
        "version": "1.2.0",
        "url": "http://alpha-agent:8000/a2a/",
        "skills": [
            {
                "id": "analyze_thermal",
                "name": "Analyze thermal",
                "description": "Runs a thermal analysis.",
                "tags": ["thermal"],
                "inputSchema": {"type": "object"},
            }
        ],
    },
    "static_headers": {"Authorization": ALPHA_SECRET},
    "registered_at": ALPHA_REGISTERED_AT,
}

# An entry stored before the backend recorded registered_at; its skill has no tags.
BETA = {
    "agent_name": "beta-agent",
    "agent_card_params": {
        "name": "Beta Agent",
        "description": "Summaries.",
        "version": "0.3.1",
        "url": "http://beta-agent:8000/",
        "skills": [{"id": "summarize", "inputSchema": {"type": "object"}}],
    },
    "static_headers": {},
}

# An agent whose /healthz answers, but not with a 2xx.
GAMMA = {
    "agent_name": "gamma-agent",
    "agent_card_params": {
        "name": "Gamma Agent",
        "description": "Meshing.",
        "version": "2.0.0",
        "url": "http://gamma-agent:8000/",
        "skills": [],
    },
    "static_headers": {},
    "registered_at": "2026-11-02T09:00:00+00:00",
}


def _authed_client(monkeypatch) -> TestClient:
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)

    token = security.issue_token(security.User(identifier="alice"), sid="sid-agents")
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client


def _seed(fake_redis: Any, *entries: dict[str, Any]) -> None:
    """Write *entries* into the registry hash, keyed by ``agent_name``, in the given order."""
    for entry in entries:
        asyncio.run(fake_redis.hset(REGISTRY_KEY, entry["agent_name"], json.dumps(entry)))


def _route_probes(monkeypatch, answers: dict[str, int | Exception]) -> list[httpx.Request]:
    """Answer each probe by host: a status code, or an exception the transport raises.

    A host or path not in *answers* gets a 404. Returns the probe requests seen.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = answers.get(request.url.host)
        if answer is None or request.url.path != "/healthz":
            return httpx.Response(404)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)

    monkeypatch.setattr(agents_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def _keys(value: Any) -> set[str]:
    """Every object key anywhere in a decoded JSON value."""
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


def test_agents_list_reports_status(monkeypatch, fake_redis):
    # Seeded out of name order, so the response order comes from the route's sort.
    _seed(fake_redis, GAMMA, BETA, ALPHA)
    seen = _route_probes(
        monkeypatch,
        {"alpha-agent": 200, "beta-agent": httpx.ConnectError("connection refused"), "gamma-agent": 500},
    )
    client = _authed_client(monkeypatch)

    before = datetime.now(timezone.utc)
    resp = client.get("/api/agents")
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert before <= datetime.fromisoformat(body["checked_at"]) <= after
    assert body["agents"] == [
        {
            "agent_name": "alpha-agent",
            "name": "Alpha Agent",
            "description": "Thermal analysis.",
            "version": "1.2.0",
            "registered_at": ALPHA_REGISTERED_AT,
            "reachable": True,
            "checked_at": None,
            "skills": [
                {
                    "id": "analyze_thermal",
                    "name": "Analyze thermal",
                    "description": "Runs a thermal analysis.",
                    "tags": ["thermal"],
                }
            ],
        },
        {
            "agent_name": "beta-agent",
            "name": "Beta Agent",
            "description": "Summaries.",
            "version": "0.3.1",
            "registered_at": None,
            "reachable": False,
            "checked_at": None,
            "skills": [{"id": "summarize", "name": "", "description": "", "tags": []}],
        },
        {
            "agent_name": "gamma-agent",
            "name": "Gamma Agent",
            "description": "Meshing.",
            "version": "2.0.0",
            "registered_at": "2026-11-02T09:00:00+00:00",
            "reachable": False,
            "checked_at": None,
            "skills": [],
        },
    ]
    # Each agent was probed live on the origin of its card url, not on the url's path.
    assert sorted(str(request.url) for request in seen) == [
        "http://alpha-agent:8000/healthz",
        "http://beta-agent:8000/healthz",
        "http://gamma-agent:8000/healthz",
    ]
    # The card url, the agent's own headers and the skill input schemas stay off this wire.
    assert not {"url", "static_headers", "inputSchema"} & _keys(body)
    assert ALPHA_SECRET not in resp.text
    assert "http://alpha-agent:8000" not in resp.text

    # The reset of GitHub #321 deletes the hash; the next read reflects it.
    asyncio.run(fake_redis.delete(REGISTRY_KEY))

    after_reset = client.get("/api/agents")

    assert after_reset.status_code == 200
    assert after_reset.json()["agents"] == []


def test_agent_status_returns_one_agent(monkeypatch, fake_redis):
    _seed(fake_redis, ALPHA, BETA)
    seen = _route_probes(monkeypatch, {"alpha-agent": 200, "beta-agent": 200})
    client = _authed_client(monkeypatch)

    before = datetime.now(timezone.utc)
    resp = client.get("/api/agents/alpha-agent")
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_name"] == "alpha-agent"
    assert body["name"] == "Alpha Agent"
    assert body["registered_at"] == ALPHA_REGISTERED_AT
    assert body["reachable"] is True
    # Checked during this request, not cached or stored.
    assert before <= datetime.fromisoformat(body["checked_at"]) <= after
    # Only the requested agent is probed, and its url and headers stay off this wire.
    assert [str(request.url) for request in seen] == ["http://alpha-agent:8000/healthz"]
    assert not {"url", "static_headers", "inputSchema"} & _keys(body)
    assert ALPHA_SECRET not in resp.text


def test_agent_status_unknown_name_is_404(monkeypatch, fake_redis):
    _seed(fake_redis, ALPHA)
    _route_probes(monkeypatch, {"alpha-agent": 200})
    client = _authed_client(monkeypatch)

    resp = client.get("/api/agents/x")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent 'x' is not registered"


@pytest.mark.parametrize("path", ["/api/agents", "/api/agents/alpha-agent"], ids=["list", "one"])
def test_agents_routes_require_session(monkeypatch, fake_redis, path):
    from app.main import app

    _seed(fake_redis, ALPHA)
    _route_probes(monkeypatch, {"alpha-agent": 200})
    client = TestClient(app)

    resp = client.get(path)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_agent_probe_timeout_reports_unreachable(monkeypatch, fake_redis):
    _seed(fake_redis, ALPHA)
    monkeypatch.setattr(agents_mod, "AGENT_PROBE_TIMEOUT_S", 0.05)

    async def hang(request: httpx.Request) -> httpx.Response:
        # A mock transport ignores httpx's own timeouts, so only the route's bound ends this.
        await asyncio.sleep(10)
        return httpx.Response(200)

    monkeypatch.setattr(agents_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(hang)))
    client = _authed_client(monkeypatch)

    resp = client.get("/api/agents/alpha-agent")

    assert resp.status_code == 200
    assert resp.json()["reachable"] is False


def test_agents_list_degrades_when_valkey_fails(monkeypatch, fake_redis):
    _seed(fake_redis, ALPHA)

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise RedisError("valkey down")

    monkeypatch.setattr(fake_redis, "hgetall", fail)
    client = _authed_client(monkeypatch)

    before = datetime.now(timezone.utc)
    resp = client.get("/api/agents")
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["agents"] == []
    assert before <= datetime.fromisoformat(body["checked_at"]) <= after


def test_agent_status_is_503_when_valkey_fails(monkeypatch, fake_redis):
    _seed(fake_redis, ALPHA)

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise RedisError("valkey down")

    monkeypatch.setattr(fake_redis, "hget", fail)
    client = _authed_client(monkeypatch)

    resp = client.get("/api/agents/alpha-agent")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Agent registry is unavailable"


def test_agents_list_keeps_malformed_entry(monkeypatch, fake_redis, caplog):
    # A card the status row cannot validate: its version is a number, not a string.
    broken = {
        "agent_name": "aaa-broken-agent",
        "agent_card_params": {
            "name": "Broken Agent",
            "description": "Bad card.",
            "version": 3,
            "url": "http://broken-agent:8000/",
            "skills": [{"id": "fix"}],
        },
        "static_headers": {},
        "registered_at": "2026-11-03T10:00:00+00:00",
    }
    _seed(fake_redis, ALPHA, broken)
    _route_probes(monkeypatch, {"alpha-agent": 200, "broken-agent": 200})
    client = _authed_client(monkeypatch)

    with caplog.at_level("WARNING", logger="app.routers.agents"):
        resp = client.get("/api/agents")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["agents"] == [
        {
            "agent_name": "aaa-broken-agent",
            "name": "",
            "description": "",
            "version": "",
            "registered_at": "2026-11-03T10:00:00+00:00",
            "reachable": True,
            "checked_at": None,
            "skills": [],
        },
        {
            "agent_name": "alpha-agent",
            "name": "Alpha Agent",
            "description": "Thermal analysis.",
            "version": "1.2.0",
            "registered_at": ALPHA_REGISTERED_AT,
            "reachable": True,
            "checked_at": None,
            "skills": [
                {
                    "id": "analyze_thermal",
                    "name": "Analyze thermal",
                    "description": "Runs a thermal analysis.",
                    "tags": ["thermal"],
                }
            ],
        },
    ]
    warnings = [r.getMessage() for r in caplog.records if r.name == "app.routers.agents" and r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "Agent 'aaa-broken-agent' has a malformed card" in warnings[0]


def test_agent_without_card_url_is_unreachable_without_a_probe(monkeypatch, fake_redis):
    """An entry registered without a card ``url`` is ``reachable: false``, and no probe is sent."""
    no_url = {**GAMMA, "agent_name": "no-url-agent", "agent_card_params": {**GAMMA["agent_card_params"], "url": ""}}
    _seed(fake_redis, no_url)
    seen = _route_probes(monkeypatch, {"gamma-agent": 200})

    resp = _authed_client(monkeypatch).get("/api/agents/no-url-agent")

    assert resp.status_code == 200
    assert resp.json()["reachable"] is False
    assert seen == []


def test_make_client_bounds_each_probe_by_the_probe_timeout():
    """The default probe client applies ``AGENT_PROBE_TIMEOUT_S`` to every phase of a request."""
    client = agents_mod._make_client()
    try:
        assert client.timeout == httpx.Timeout(agents_mod.AGENT_PROBE_TIMEOUT_S)
    finally:
        asyncio.run(client.aclose())
