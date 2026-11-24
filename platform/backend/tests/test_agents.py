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
import ipaddress
import json
import time
import weakref
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.routers import agents as agents_mod
from app.agent_store import REGISTRY_KEY

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


# The real resolver, kept before the autouse fixture below replaces it.
_REAL_RESOLVE = agents_mod._resolve


@pytest.fixture(autouse=True)
def resolve_to_a_private_address(monkeypatch) -> None:
    """Resolve every card host to one private address, so no test touches DNS.

    A test that checks the address guard replaces this with its own resolver.
    """

    async def resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]

    monkeypatch.setattr(agents_mod, "_resolve", resolve)


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

    real_client = agents_mod._make_client()
    headers = dict(real_client.headers)
    asyncio.run(real_client.aclose())

    def client() -> httpx.AsyncClient:
        # The real client's headers, with the transport swapped for the handler.
        return httpx.AsyncClient(headers=headers, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(agents_mod, "_make_client", client)
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
            "checked_at": body["checked_at"],
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
            "checked_at": body["checked_at"],
            "skills": [{"id": "summarize", "name": "", "description": "", "tags": []}],
        },
        {
            "agent_name": "gamma-agent",
            "name": "Gamma Agent",
            "description": "Meshing.",
            "version": "2.0.0",
            "registered_at": "2026-11-02T09:00:00+00:00",
            "reachable": False,
            "checked_at": body["checked_at"],
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
    """A malformed field or skill empties or drops only itself: the other card fields and
    skills stay, and the warning names the agent and a count, never the card's values."""
    sentinel = "SENTINEL-card-value-7f3a"
    broken = {
        "agent_name": "aaa-broken-agent",
        "agent_card_params": {
            "name": "Broken Agent",
            "description": "Bad card.",
            "version": 3,
            "url": "http://broken-agent:8000/",
            "skills": [
                {"id": "fix", "name": "Fix", "tags": ["repair"]},
                {"id": "bad-tags", "tags": None},
                {"id": "bad-name", "name": None},
                {"id": "bad-tag", "tags": [sentinel, 4]},
                {"name": "no id"},
            ],
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
    assert body["agents"][0] == {
        "agent_name": "aaa-broken-agent",
        "name": "Broken Agent",
        "description": "Bad card.",
        "version": "",
        "registered_at": "2026-11-03T10:00:00+00:00",
        "reachable": True,
        "checked_at": body["checked_at"],
        "skills": [{"id": "fix", "name": "Fix", "description": "", "tags": ["repair"]}],
    }
    assert body["agents"][1]["agent_name"] == "alpha-agent"
    assert [skill["id"] for skill in body["agents"][1]["skills"]] == ["analyze_thermal"]
    warnings = [r.getMessage() for r in caplog.records if r.name == "app.routers.agents" and r.levelname == "WARNING"]
    assert warnings == ["Agent 'aaa-broken-agent' has 4 malformed skill(s); returning the others"]
    assert sentinel not in caplog.text


def test_agents_list_drops_skills_that_are_not_a_list(monkeypatch, fake_redis):
    odd = {**GAMMA, "agent_card_params": {**GAMMA["agent_card_params"], "skills": {"id": "x"}}}
    _seed(fake_redis, odd)
    _route_probes(monkeypatch, {"gamma-agent": 200})

    row = _authed_client(monkeypatch).get("/api/agents/gamma-agent").json()

    assert row["name"] == "Gamma Agent"
    assert row["skills"] == []


def test_agent_without_card_url_is_unreachable_without_a_probe(monkeypatch, fake_redis):
    """An entry registered without a card ``url`` is ``reachable: false``, and no probe is sent."""
    no_url = {**GAMMA, "agent_name": "no-url-agent", "agent_card_params": {**GAMMA["agent_card_params"], "url": ""}}
    _seed(fake_redis, no_url)
    seen = _route_probes(monkeypatch, {"gamma-agent": 200})

    resp = _authed_client(monkeypatch).get("/api/agents/no-url-agent")

    assert resp.status_code == 200
    assert resp.json()["reachable"] is False
    assert seen == []


def test_list_probes_run_concurrently(monkeypatch, fake_redis):
    """Three slow agents and one that hangs cost about one probe bound, not their sum: the list
    probes run concurrently, and the hung agent is cut off at the probe bound."""
    entries = [
        {
            **GAMMA,
            "agent_name": name,
            "agent_card_params": {**GAMMA["agent_card_params"], "url": f"http://{name}:8000/"},
        }
        for name in ("slow-a", "slow-b", "slow-c", "hung")
    ]
    _seed(fake_redis, *entries)
    monkeypatch.setattr(agents_mod, "AGENT_PROBE_TIMEOUT_S", 1.0)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10 if request.url.host == "hung" else 0.5)
        return httpx.Response(200)

    monkeypatch.setattr(agents_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    client = _authed_client(monkeypatch)

    started = time.monotonic()
    resp = client.get("/api/agents")
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    reachable = {row["agent_name"]: row["reachable"] for row in resp.json()["agents"]}
    assert reachable == {"hung": False, "slow-a": True, "slow-b": True, "slow-c": True}
    # Concurrent: about one bound, 1 s. Sequential: 3 x 0.5 s for the slow agents plus
    # 1 s for the hung one, 2.5 s. The cut-off sits between them with room for a slow runner.
    assert elapsed < 2.0


@pytest.mark.parametrize(
    ("raw", "card_url"),
    [
        pytest.param("{", None, id="not-json"),
        pytest.param(json.dumps(["x"]), None, id="not-an-object"),
        pytest.param(json.dumps({"agent_card_params": ["x"], "registered_at": 5}), None, id="card-not-a-dict"),
        pytest.param(json.dumps({"agent_card_params": {"url": 123}}), None, id="url-not-a-string"),
        pytest.param(json.dumps({"agent_card_params": {"url": "http://xn--a.com/"}}), None, id="url-idna-error"),
        pytest.param(json.dumps({"agent_card_params": {"url": "http://[::1/"}}), None, id="url-invalid"),
    ],
)
def test_agents_list_keeps_unreadable_entry(monkeypatch, fake_redis, raw, card_url):
    """An entry that a hand edit of Valkey broke keeps its row, keyed by its hash field,
    and fails neither the list, nor its own route, nor the service list ``GET /v1/agents``."""
    from app.config import settings

    _seed(fake_redis, ALPHA)
    asyncio.run(fake_redis.hset(REGISTRY_KEY, "aaa-bad-agent", raw))
    _route_probes(monkeypatch, {"alpha-agent": 200})
    client = _authed_client(monkeypatch)

    listed = client.get("/api/agents")
    one = client.get("/api/agents/aaa-bad-agent")

    assert listed.status_code == 200
    rows = listed.json()["agents"]
    assert [row["agent_name"] for row in rows] == ["aaa-bad-agent", "alpha-agent"]
    assert rows[0] == {
        "agent_name": "aaa-bad-agent",
        "name": "",
        "description": "",
        "version": "",
        "registered_at": None,
        "reachable": False,
        "checked_at": listed.json()["checked_at"],
        "skills": [],
    }
    assert rows[1]["reachable"] is True
    assert one.status_code == 200
    assert one.json()["reachable"] is False

    monkeypatch.setattr(settings, "agent_secret", "test-agent-secret")
    service = client.get("/v1/agents", headers={"Authorization": "Bearer test-agent-secret"})
    assert service.status_code == 200
    assert [entry["agent_name"] for entry in service.json()] == ["aaa-bad-agent", "alpha-agent"]


@pytest.mark.parametrize("path", ["/api/agents", "/api/agents/alpha-agent"], ids=["list", "one"])
def test_checked_at_is_taken_after_the_probe(monkeypatch, fake_redis, path):
    """``checked_at`` is the time of the probe result, not of the request's start."""
    _seed(fake_redis, ALPHA)
    probed_at: list[datetime] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        probed_at.append(datetime.now(timezone.utc))
        return httpx.Response(200)

    monkeypatch.setattr(agents_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow)))

    body = _authed_client(monkeypatch).get(path).json()

    assert datetime.fromisoformat(body["checked_at"]) >= probed_at[0]


@pytest.mark.parametrize(
    ("url", "resolved"),
    [
        pytest.param("ftp://alpha-agent/", ["10.0.0.7"], id="not-http"),
        pytest.param("file:///etc/passwd", ["10.0.0.7"], id="file"),
        pytest.param("http://169.254.169.254/latest/", ["169.254.169.254"], id="metadata-v4"),
        pytest.param("http://0xa9fea9fe/", ["169.254.169.254"], id="metadata-hex"),
        pytest.param("http://metadata.example/", ["169.254.169.254"], id="dns-to-metadata"),
        pytest.param("http://[fd00:ec2::254]/", ["fd00:ec2::254"], id="metadata-aws-v6"),
        pytest.param("http://[::ffff:169.254.169.254]/", ["::ffff:169.254.169.254"], id="metadata-v4-mapped"),
        pytest.param("http://[fe80::1]/", ["fe80::1"], id="link-local-v6"),
        pytest.param("http://mixed.example/", ["10.0.0.7", "169.254.1.1"], id="any-address-blocked"),
        pytest.param("http://nowhere.example/", [], id="no-address"),
    ],
)
def test_probe_refuses_a_blocked_target(monkeypatch, fake_redis, url, resolved):
    """A card url that is not http(s), or whose host resolves to a link-local or metadata
    address, is reported unreachable without a request, so the probe is no oracle on it."""
    entry = {**GAMMA, "agent_card_params": {**GAMMA["agent_card_params"], "url": url}}
    _seed(fake_redis, entry)

    async def resolve(host: str, port: int) -> list[str]:
        return resolved

    monkeypatch.setattr(agents_mod, "_resolve", resolve)
    seen = _route_probes(monkeypatch, {})

    row = _authed_client(monkeypatch).get("/api/agents/gamma-agent").json()

    assert row["reachable"] is False
    assert seen == []


def test_probe_allows_a_private_compose_host(monkeypatch, fake_redis):
    """In-tree agents run on private compose addresses; those are probed."""
    _seed(fake_redis, GAMMA)
    seen = _route_probes(monkeypatch, {"gamma-agent": 200})

    row = _authed_client(monkeypatch).get("/api/agents/gamma-agent").json()

    assert row["reachable"] is True
    assert [str(request.url) for request in seen] == ["http://gamma-agent:8000/healthz"]


def test_probe_drops_userinfo_from_the_card_url(monkeypatch, fake_redis):
    """``http://u:p@host/`` is probed without the userinfo, so it is never sent as Basic auth."""
    entry = {**GAMMA, "agent_card_params": {**GAMMA["agent_card_params"], "url": "http://u:p@gamma-agent:8000/"}}
    _seed(fake_redis, entry)
    seen = _route_probes(monkeypatch, {"gamma-agent": 200})

    row = _authed_client(monkeypatch).get("/api/agents/gamma-agent").json()

    assert row["reachable"] is True
    assert str(seen[0].url) == "http://gamma-agent:8000/healthz"
    assert "authorization" not in seen[0].headers


def test_probe_names_itself_in_the_user_agent(monkeypatch, fake_redis):
    """An agent's access log can tell a status probe from orchestrator traffic."""
    _seed(fake_redis, GAMMA)
    seen = _route_probes(monkeypatch, {"gamma-agent": 200})

    _authed_client(monkeypatch).get("/api/agents/gamma-agent")

    assert seen[0].headers["user-agent"] == "prometheus-backend-status"


@pytest.mark.parametrize(
    ("url", "probed"),
    [
        pytest.param("http://gamma-agent:8000", "http://gamma-agent:8000/healthz", id="bare-origin"),
        pytest.param("http://gamma-agent:8000/a2a/", "http://gamma-agent:8000/healthz", id="path"),
        pytest.param("http://gamma-agent:8000/a2a/?x=1", "http://gamma-agent:8000/healthz", id="path-and-query"),
        pytest.param("http://gamma-agent:8000/a2a#frag", "http://gamma-agent:8000/healthz", id="fragment"),
        pytest.param("  http://gamma-agent:8000/  ", "http://gamma-agent:8000/healthz", id="whitespace"),
        pytest.param("https://gamma-agent/agents/x/", "https://gamma-agent/healthz", id="https-gateway-path"),
        pytest.param("", None, id="empty"),
        pytest.param("   ", None, id="blank"),
        pytest.param("not a url", None, id="garbage"),
    ],
)
def test_probe_targets_the_card_url_origin(monkeypatch, fake_redis, url, probed):
    """The probe goes to ``/healthz`` on the card url's origin, whatever path, query or
    fragment the url has: the SDK serves ``/healthz`` at the root of the agent's app. A url
    with no host is reported unreachable without a request."""
    entry = {**GAMMA, "agent_card_params": {**GAMMA["agent_card_params"], "url": url}}
    _seed(fake_redis, entry)
    seen = _route_probes(monkeypatch, {"gamma-agent": 200})

    row = _authed_client(monkeypatch).get("/api/agents/gamma-agent").json()

    assert [str(request.url) for request in seen] == ([probed] if probed else [])
    assert row["reachable"] is (probed is not None)


def test_no_path_leaks_the_agents_secret(monkeypatch, fake_redis, caplog):
    """A sentinel in ``static_headers`` reaches no response body and no log line, on the
    list, one-agent, not-found and registry-down paths."""
    sentinel = "SENTINEL-static-header-91c2"
    leaky = {**ALPHA, "static_headers": {"Authorization": f"Bearer {sentinel}"}}
    _seed(fake_redis, leaky)
    _route_probes(monkeypatch, {"alpha-agent": 200})
    client = _authed_client(monkeypatch)

    with caplog.at_level("DEBUG"):
        bodies = [
            client.get("/api/agents"),
            client.get("/api/agents/alpha-agent"),
            client.get("/api/agents/no-such-agent"),
        ]

        async def fail(*args: Any, **kwargs: Any) -> Any:
            raise RedisError("valkey down")

        monkeypatch.setattr(fake_redis, "hgetall", fail)
        monkeypatch.setattr(fake_redis, "hget", fail)
        bodies += [client.get("/api/agents"), client.get("/api/agents/alpha-agent")]

    assert [resp.status_code for resp in bodies] == [200, 200, 404, 200, 503]
    for resp in bodies:
        assert sentinel not in resp.text
    assert sentinel not in caplog.text


def test_probes_never_exceed_the_concurrency_cap(monkeypatch, fake_redis):
    """However many agents a list holds, at most ``MAX_CONCURRENT_PROBES`` probes are open
    at once, so polling cannot open sockets without limit."""
    entries = [
        {
            **GAMMA,
            "agent_name": f"agent-{n:02d}",
            "agent_card_params": {**GAMMA["agent_card_params"], "url": f"http://agent-{n:02d}:8000/"},
        }
        for n in range(8)
    ]
    _seed(fake_redis, *entries)
    monkeypatch.setattr(agents_mod, "MAX_CONCURRENT_PROBES", 3)
    monkeypatch.setattr(agents_mod, "_probe_slots", weakref.WeakKeyDictionary())
    open_now = peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal open_now, peak
        open_now += 1
        peak = max(peak, open_now)
        await asyncio.sleep(0.05)
        open_now -= 1
        return httpx.Response(200)

    monkeypatch.setattr(agents_mod, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    rows = _authed_client(monkeypatch).get("/api/agents").json()["agents"]

    assert [row["reachable"] for row in rows] == [True] * 8
    assert peak == 3


def test_resolve_returns_the_hosts_addresses():
    """The real resolver, which every other test replaces: localhost needs no network."""
    addresses = asyncio.run(_REAL_RESOLVE("localhost", 8000))

    assert addresses
    assert all(ipaddress.ip_address(address).is_loopback for address in addresses)
