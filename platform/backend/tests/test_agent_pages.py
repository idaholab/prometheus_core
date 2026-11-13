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

"""Agent pages proxied through the platform (app/routers/agent_pages.py).

An artifact's path link (``metadata.links`` ``{"label", "path"}``) opens through
``/api/artifacts/{id}/links/{n}``, which hands out a short-lived grant, and
``/api/agent-pages/{grant}/...``, which forwards to the producing agent's registered
URL with the agent's own credentials. The agent is an in-process fake.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app import security
from app.config import settings
from app.routers import agent_pages
from app.routers.agent_registry import REGISTRY_KEY
from app.services.artifacts import agent_page_prefix, artifact_link_path, to_artifact_meta

SID = "sid-pages"
AGENT_URL = "http://uq-agent:8004/"
AGENT_HEADERS = {"Authorization": "Bearer agent-own-secret"}


def _uq_artifact(links=None, producer="forwardsamplinguq-agent") -> dict:
    return {
        "artifact_id": "uq-1",
        "name": "uq_run.ipynb",
        "producer_agent_id": producer,
        "metadata": {
            "links": links
            if links is not None
            else [
                {"label": "Pipeline", "url": "https://gitlab.example/g/p/-/pipelines/42"},
                {"label": "Open interactive dashboard", "path": "/console/?run=uq_run"},
            ]
        },
    }


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)


@pytest.fixture
def agent(monkeypatch) -> list[httpx.Request]:
    """The fake producing agent; returns the requests it received."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/console/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html", "set-cookie": "agent=1", "content-security-policy": "none"},
                content=b'<script src="bundle.js"></script>',
            )
        if request.url.path == "/console/result/uq_run":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/console/moved":
            return httpx.Response(302, headers={"location": "http://elsewhere/"})
        return httpx.Response(404, json={"ok": False})

    monkeypatch.setattr(agent_pages, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


async def _client(session_store, fake_redis, artifacts, *, register=True) -> TestClient:
    from app.main import app

    await session_store.reset(SID, "c1", artifacts=artifacts)
    if register:
        entry = {
            "agent_name": "forwardsamplinguq-agent",
            "agent_card_params": {"name": "ForwardSamplingUQ Agent", "url": AGENT_URL},
            "static_headers": AGENT_HEADERS,
        }
        await fake_redis.hset(REGISTRY_KEY, "forwardsamplinguq-agent", json.dumps(entry))
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, security.issue_token(security.User(identifier="alice"), sid=SID))
    return client


def _open(client: TestClient, n: int = 1) -> str:
    resp = client.get(f"/api/artifacts/uq-1/links/{n}", follow_redirects=False)
    assert resp.status_code == 303, resp.text
    assert resp.headers["cache-control"] == "no-store"
    return resp.headers["location"]


# --------------------------------------------------------------------------- #
# Link validation (services.artifacts)


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        ("/console/?run=7", "/console/"),
        ("/console/", "/console/"),
        ("/dash/run-7", "/dash/"),
        ("/a/b/c.html#top", "/a/b/"),
        ("/x", None),  # no directory: would expose the agent's root
        ("/", None),
        ("console/", None),  # relative
        ("//evil.example/x/", None),  # scheme-relative: another host
        ("http://evil.example/x/", None),
        ("/a/../b/", None),
        ("/a/./b/", None),
        ("/a\\b/", None),
        ("/a b/", None),
        ("/a\n/", None),
        ("/" + "a/" * 1100, None),  # too long
        (7, None),
    ],
)
def test_agent_page_prefix(path, prefix):
    assert agent_page_prefix(path) == prefix


def test_path_links_become_same_origin_link_routes():
    meta = to_artifact_meta(_uq_artifact())
    assert meta is not None
    assert [(link.label, link.url) for link in meta.links] == [
        ("Pipeline", "https://gitlab.example/g/p/-/pipelines/42"),
        ("Open interactive dashboard", "/api/artifacts/uq-1/links/1"),
    ]


def test_invalid_path_links_are_dropped_and_do_not_shift_indices():
    artifact = _uq_artifact(
        links=[
            {"label": "root", "path": "/x"},
            {"label": "other host", "path": "//evil.example/a/"},
            {"label": "Dashboard", "path": "/console/"},
        ]
    )
    meta = to_artifact_meta(artifact)
    assert meta is not None and [link.url for link in meta.links] == ["/api/artifacts/uq-1/links/0"]
    assert artifact_link_path(artifact, 0) == "/console/"


def test_artifact_link_path_only_for_path_links():
    artifact = _uq_artifact()
    assert artifact_link_path(artifact, 0) is None  # an absolute URL needs no proxy
    assert artifact_link_path(artifact, 1) == "/console/?run=uq_run"
    assert artifact_link_path(artifact, 2) is None
    assert artifact_link_path(artifact, -1) is None
    assert artifact_link_path({"artifact_id": "a", "metadata": "nope"}, 0) is None


# --------------------------------------------------------------------------- #
# The proxy


async def test_a_path_link_opens_the_agent_page_through_the_platform(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])

    location = _open(client)
    assert location.startswith("/api/agent-pages/") and location.endswith("/?run=uq_run")

    page = client.get(location)
    assert page.status_code == 200
    assert page.text == '<script src="bundle.js"></script>'
    # Forwarded to the producing agent's registered URL, under the link's directory,
    # with the agent's own credentials, never the user's cookie.
    assert str(agent[0].url) == "http://uq-agent:8004/console/?run=uq_run"
    assert agent[0].headers["authorization"] == AGENT_HEADERS["Authorization"]
    assert "cookie" not in agent[0].headers
    # The page runs in an opaque origin and keeps nothing of the agent's own policy.
    assert page.headers["content-security-policy"].startswith("sandbox allow-scripts")
    assert "allow-same-origin" not in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in page.headers


async def test_the_page_relative_requests_reuse_the_grant_without_a_cookie(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    grant_path = _open(client).split("?")[0]  # /api/agent-pages/{grant}/

    client.cookies.clear()  # the sandboxed page has no platform cookie
    data = client.get(f"{grant_path}result/uq_run")
    assert data.status_code == 200 and data.json() == {"ok": True}
    assert str(agent[-1].url) == "http://uq-agent:8004/console/result/uq_run"
    assert data.headers["access-control-allow-origin"] == "*"


@pytest.mark.parametrize("rest", ["../secret", "a/../../secret", "%2e%2e/secret", "a\\b"])
async def test_requests_cannot_leave_the_link_directory(secret, agent, session_store, fake_redis, rest):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    grant = _open(client).split("/")[3]
    assert client.get(f"/api/agent-pages/{grant}/{rest}").status_code == 404
    assert agent == []


async def test_open_requires_a_session(secret, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    client.cookies.clear()
    assert client.get("/api/artifacts/uq-1/links/1", follow_redirects=False).status_code == 401


@pytest.mark.parametrize("n", [0, 2, 99])
async def test_open_404_for_a_url_link_or_a_missing_link(secret, session_store, fake_redis, n):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    assert client.get(f"/api/artifacts/uq-1/links/{n}", follow_redirects=False).status_code == 404


async def test_open_404_for_another_sessions_artifact(secret, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [])
    assert client.get("/api/artifacts/uq-1/links/1", follow_redirects=False).status_code == 404


async def test_a_forged_or_expired_grant_is_404(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    now = datetime.now(timezone.utc)
    base = {"typ": "agent-page", "sid": SID, "aid": "uq-1", "n": 1}
    forged = jwt.encode({**base, "exp": now + timedelta(hours=1)}, "wrong-secret", algorithm="HS256")
    expired = jwt.encode({**base, "exp": now - timedelta(seconds=1)}, "test-secret", algorithm="HS256")
    session_token = security.issue_token(security.User(identifier="alice"), sid=SID)  # wrong typ
    other_link = jwt.encode({**base, "n": 0, "exp": now + timedelta(hours=1)}, "test-secret", algorithm="HS256")
    for grant in (forged, expired, session_token, other_link, "not-a-token"):
        assert client.get(f"/api/agent-pages/{grant}/").status_code == 404
    assert agent == []


async def test_a_logged_out_session_closes_its_pages(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    location = _open(client)
    await security.revoke_session(fake_redis, SID, int(datetime.now(timezone.utc).timestamp()) + 3600)
    assert client.get(location).status_code == 404
    assert agent == []


async def test_an_unregistered_producer_is_404(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()], register=False)
    assert client.get(_open(client)).status_code == 404
    client2 = await _client(session_store, fake_redis, [_uq_artifact(producer=None)])
    assert client2.get(_open(client2)).status_code == 404
    assert agent == []


async def test_an_agent_redirect_is_not_followed(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    grant_path = _open(client).split("?")[0]
    assert client.get(f"{grant_path}moved").status_code == 502


async def test_an_unreachable_agent_is_502(secret, monkeypatch, session_store, fake_redis):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(agent_pages, "_make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    resp = client.get(_open(client))
    assert resp.status_code == 502
    assert "uq-agent" not in resp.text


async def test_agent_errors_pass_through(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    grant_path = _open(client).split("?")[0]
    assert client.get(f"{grant_path}missing").status_code == 404


async def test_an_agent_registered_without_a_url_is_404(secret, agent, session_store, fake_redis):
    client = await _client(session_store, fake_redis, [_uq_artifact()])
    entry = {"agent_name": "forwardsamplinguq-agent", "agent_card_params": {"name": "UQ"}}
    await fake_redis.hset(REGISTRY_KEY, "forwardsamplinguq-agent", json.dumps(entry))
    assert client.get(_open(client)).status_code == 404
    assert agent == []


async def test_the_default_client_does_not_follow_redirects():
    client = agent_pages._make_client()
    try:
        assert client.follow_redirects is False
        assert client.timeout.read == agent_pages.AGENT_PAGE_TIMEOUT_S
    finally:
        await client.aclose()


def test_an_overlong_url_link_is_dropped():
    artifact = _uq_artifact(links=[{"label": "long", "url": "https://example.com/" + "a" * 3000}])
    meta = to_artifact_meta(artifact)
    assert meta is not None and meta.links == []
