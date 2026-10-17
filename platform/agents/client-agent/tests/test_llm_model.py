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

"""Resolution of the orchestrator's LLM alias to the deployment's provider model."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)
from starlette.applications import Starlette
from starlette.testclient import TestClient

import tool_discovery
from orchestrator import llm_model, service

PROXY_URL = "http://litellm:4000"
MASTER_KEY = "sk-test-master"

MODEL_INFO_ENTRIES = [
    {"model_name": "small", "litellm_params": {"model": "anthropic/claude-haiku-4-5"}},
    {"model_name": "medium", "litellm_params": {"model": "anthropic/claude-sonnet-5-5"}},
]


@pytest.fixture(autouse=True)
def _reset_llm_model_cache():
    llm_model._reset_cache()
    yield
    llm_model._reset_cache()


@pytest.fixture
def proxy_mode(monkeypatch):
    """Point the resolver at a LiteLLM proxy and give it a master key."""
    fake_config = SimpleNamespace(proxy_url=PROXY_URL)
    monkeypatch.setattr(llm_model.LLMConfig, "from_env", classmethod(lambda cls: fake_config))
    monkeypatch.setattr(tool_discovery, "LITELLM_MASTER_KEY", MASTER_KEY)


@pytest.fixture
def serve_model_info(monkeypatch):
    """Route the resolver's httpx client to a handler serving ``payload``; return the requests."""

    def install(payload):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/model/info":
                return httpx.Response(200, json=payload)
            return httpx.Response(404)

        real_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(llm_model.httpx, "AsyncClient", client_factory)
        return requests

    return install


@pytest.mark.parametrize(
    "payload",
    [MODEL_INFO_ENTRIES, {"data": MODEL_INFO_ENTRIES}],
    ids=["bare_list", "data_wrapper"],
)
def test_resolve_reads_proxy_model_info(proxy_mode, serve_model_info, payload):
    requests = serve_model_info(payload)

    result = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))

    assert result == "anthropic/claude-sonnet-5-5"
    assert [str(request.url) for request in requests] == [f"{PROXY_URL}/model/info"]
    assert requests[0].headers["Authorization"] == f"Bearer {MASTER_KEY}"


@pytest.fixture
def route_proxy(monkeypatch):
    """Route the resolver's httpx client to ``handler``."""

    def install(handler):
        real_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(llm_model.httpx, "AsyncClient", client_factory)

    return install


def test_resolve_uses_fallback_profile(monkeypatch, tmp_path):
    config_file = tmp_path / "fallback.yaml"
    config_file.write_text(
        "model_list:\n"
        "  - model_name: small\n"
        "    litellm_params:\n"
        "      model: anthropic/claude-haiku-4-5\n"
        "  - model_name: medium\n"
        "    litellm_params:\n"
        "      model: anthropic/claude-sonnet-5-5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)  # keep LLMConfig.from_env away from any cwd .env
    monkeypatch.setenv("LLM_CONFIG_FILE", str(config_file))

    result = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))

    assert result == "anthropic/claude-sonnet-5-5"


def _server_error(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


def _no_alias(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=[MODEL_INFO_ENTRIES[0]])


@pytest.mark.parametrize(
    "handler",
    [_server_error, _timeout, _no_alias],
    ids=["server_error", "timeout", "missing_alias"],
)
def test_resolve_degrades_to_none_when_proxy_fails(proxy_mode, route_proxy, handler):
    route_proxy(handler)

    result = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))

    assert result is None


def test_resolve_failure_is_not_cached(proxy_mode, route_proxy):
    responses = iter([httpx.Response(500), httpx.Response(200, json=MODEL_INFO_ENTRIES)])
    route_proxy(lambda request: next(responses))

    first = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))
    second = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))

    assert first is None
    assert second == "anthropic/claude-sonnet-5-5"


@pytest.mark.parametrize(
    "resolved",
    ["anthropic/claude-sonnet-5-5", None],
    ids=["resolved", "unresolved"],
)
def test_llm_model_route_returns_alias_and_model(monkeypatch, resolved):
    async def fake_resolve_llm_model(alias=llm_model.ORCHESTRATOR_LLM_ALIAS):
        return resolved

    monkeypatch.setattr(service, "resolve_llm_model", fake_resolve_llm_model)
    # configure_app binds the agent's endpoint methods; none of them is called
    # at registration, so the agent needs no card, registry or LLM setup.
    agent = service.OrchestratorAgent.__new__(service.OrchestratorAgent)
    app = Starlette()
    agent.configure_app(app)

    response = TestClient(app).get("/llm/model")

    assert response.status_code == 200
    assert response.json() == {"alias": "medium", "model": resolved}


@pytest.fixture
def fake_clock(monkeypatch):
    """Give llm_model its own monotonic clock; advance it by mutating ``now[0]``."""
    now = [1000.0]
    monkeypatch.setattr(llm_model, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_resolve_caches_model_until_refresh_window_ends(
    monkeypatch, proxy_mode, serve_model_info, fake_clock
):
    monkeypatch.setattr(llm_model, "DISCOVERY_REFRESH_SECONDS", 60)
    requests = serve_model_info(MODEL_INFO_ENTRIES)

    first = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))
    fake_clock[0] += 59
    within_window = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))
    requests_within_window = len(requests)
    fake_clock[0] += 1
    after_window = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))

    assert first == within_window == after_window == "anthropic/claude-sonnet-5-5"
    assert requests_within_window == 1
    assert len(requests) == 2


def test_resolve_cache_never_expires_when_refresh_disabled(
    monkeypatch, proxy_mode, serve_model_info, fake_clock
):
    monkeypatch.setattr(llm_model, "DISCOVERY_REFRESH_SECONDS", 0)
    requests = serve_model_info(MODEL_INFO_ENTRIES)

    first = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))
    fake_clock[0] += 10_000_000
    later = asyncio.run(llm_model.resolve_llm_model(llm_model.ORCHESTRATOR_LLM_ALIAS))

    assert first == later == "anthropic/claude-sonnet-5-5"
    assert len(requests) == 1
