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

"""``GET /api/config`` reports the orchestrator's LLM model as ``llm_model``.

The client-agent is faked by monkeypatching ``A2AClient.get_llm_model``; no live agent.
"""

from typing import Any, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.a2a_client import A2AClient

MODEL = "anthropic/claude-sonnet-5-5"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def authed_client(monkeypatch) -> TestClient:
    """A ``TestClient`` with a valid session cookie, as ``test_auth._authed`` builds it."""
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)

    token = security.issue_token(security.User(identifier="alice"), sid="sid-config-llm-model")
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client


@pytest.fixture
def fake_llm_model(monkeypatch) -> Callable[[Any], None]:
    """Make ``A2AClient.get_llm_model`` return ``result``, or raise it when it is an exception."""

    def install(result: Any) -> None:
        async def fake(self: A2AClient) -> Any:
            if isinstance(result, BaseException):
                raise result
            return result

        monkeypatch.setattr(A2AClient, "get_llm_model", fake)

    return install


def test_config_returns_llm_model(authed_client, fake_llm_model):
    from app.config import settings
    from app.routers.config import CHAT_PROFILES

    fake_llm_model(MODEL)

    resp = authed_client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_model"] == MODEL
    # The other config fields keep their configured values.
    assert body["profiles"] == [profile.model_dump(mode="json") for profile in CHAT_PROFILES]
    assert body["chat_intro"] == settings.chat_intro
    assert body["chat_suggestion_title"] == settings.chat_suggestion_title
    assert body["workflow_suggestions"] == settings.workflow_suggestions
    assert body["auto_approve_steps"] == settings.auto_approve_steps
    assert body["max_upload_bytes"] == settings.max_upload_bytes


@pytest.fixture
def fake_agent_http(monkeypatch) -> Callable[[Callable[[httpx.Request], httpx.Response]], None]:
    """Route the real ``A2AClient``'s ``httpx.AsyncClient`` through a ``MockTransport`` handler."""

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            return _REAL_ASYNC_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr("app.a2a_client.httpx.AsyncClient", client)

    return install


def _agent_times_out(request: httpx.Request) -> httpx.Response:
    raise httpx.TimeoutException("timed out", request=request)


def _agent_returns_non_string_model(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"model": 5})


def test_config_degrades_without_agent_when_the_call_raises(authed_client, fake_llm_model):
    fake_llm_model(RuntimeError("client-agent unreachable"))

    resp = authed_client.get("/api/config")

    assert resp.status_code == 200
    assert resp.json()["llm_model"] is None


@pytest.mark.parametrize(
    "handler",
    [_agent_times_out, _agent_returns_non_string_model],
    ids=["timeout", "non-string-model"],
)
def test_config_degrades_without_agent(authed_client, fake_agent_http, handler):
    fake_agent_http(handler)

    resp = authed_client.get("/api/config")

    assert resp.status_code == 200
    assert resp.json()["llm_model"] is None
