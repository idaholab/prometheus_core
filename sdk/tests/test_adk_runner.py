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

"""Tests for ``build_runner``, the factory that wires ADK into a Prometheus agent.

The runner is built on the non-test path, so the services come from ``ADK_SESSION_DB_URL``.
The database case points it at a SQLite file under ``tmp_path``; nothing connects to it, because
building a runner opens no connection. A stub summarizer keeps the compaction plugin from
building a real LLM client.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from google.adk.agents import LlmAgent
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from prometheus_api.adk.artifacts import ArtifactCallPlugin, DeepLynxArtifactService
from prometheus_api.adk.memory import PrometheusMemoryService
from prometheus_api.adk.plugins.approval import ApprovalPlugin
from prometheus_api.adk.plugins.bridge import A2ABridgePlugin
from prometheus_api.adk.plugins.cancel import CancelPlugin
from prometheus_api.adk.plugins.compaction import CompactionPlugin
from prometheus_api.adk.plugins.credentials import CredentialPlugin
from prometheus_api.adk.plugins.provenance import ProvenancePlugin
from prometheus_api.adk.runner import build_runner, session_services
from prometheus_api.agent import PrometheusAgent

NAMED_PLUGINS = (
    A2ABridgePlugin,
    ProvenancePlugin,
    CredentialPlugin,
    ApprovalPlugin,
    CancelPlugin,
    CompactionPlugin,
)
RUNNER_LOGGER = "prometheus_api.adk.runner"


class _StubLlm(BaseLlm):
    """Answers with fixed text; the runner is only built, never run."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))


class _CardAgent(PrometheusAgent):
    """A minimal Prometheus agent with an agent card and no skills."""

    def get_raw_agent_card(self) -> dict[str, Any]:
        return {"name": self.agent_name, "skills": []}


class _RecordingQueue:
    """An event queue fake that records what the bridge enqueues."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _fresh_session_services() -> Iterator[None]:
    """Reset the process cache of session services before and after each test."""
    session_services.cache_clear()
    yield
    session_services.cache_clear()


def _build(compaction_off: bool = False) -> Runner:
    kwargs: dict[str, Any] = {"compaction": None} if compaction_off else {}
    return build_runner(
        _CardAgent(agent_name="Runner Test Agent"),
        MagicMock(spec=RequestContext),
        LlmAgent(name="runner_root", model=_StubLlm()),
        event_queue=_RecordingQueue(),  # type: ignore[arg-type]
        summarizer_model=_StubLlm(),
        **kwargs,
    )


def _named_plugin_types(runner: Runner) -> list[type]:
    return [
        named
        for named in NAMED_PLUGINS
        for plugin in runner.plugin_manager.plugins
        if isinstance(plugin, named)
    ]


def test_build_runner_wires_resumable_app_services_and_plugins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Covers REQ-016-10."""
    monkeypatch.setenv("ADK_SESSION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'adk.db'}")

    runner = _build()

    assert runner.app is not None
    assert runner.app.resumability_config is not None
    assert runner.app.resumability_config.is_resumable is True
    assert runner.app.events_compaction_config is None
    assert isinstance(runner.session_service, DatabaseSessionService)
    assert isinstance(runner.memory_service, PrometheusMemoryService)
    assert isinstance(runner.artifact_service, DeepLynxArtifactService)
    assert sorted(t.__name__ for t in _named_plugin_types(runner)) == sorted(
        t.__name__ for t in NAMED_PLUGINS
    )
    assert any(isinstance(p, ArtifactCallPlugin) for p in runner.plugin_manager.plugins)


def test_build_runner_without_compaction_leaves_out_compaction_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Covers REQ-016-10."""
    monkeypatch.setenv("ADK_SESSION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'adk.db'}")

    runner = _build(compaction_off=True)

    named = _named_plugin_types(runner)
    assert len(named) == 5
    assert CompactionPlugin not in named
    assert not any(isinstance(p, CompactionPlugin) for p in runner.plugin_manager.plugins)


def test_build_runner_with_empty_db_url_uses_in_memory_services_and_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Covers REQ-016-10."""
    monkeypatch.setenv("ADK_SESSION_DB_URL", "")
    caplog.set_level(logging.WARNING, logger=RUNNER_LOGGER)

    first = _build()
    second = _build()

    for runner in (first, second):
        assert isinstance(runner.session_service, InMemorySessionService)
        assert isinstance(runner.memory_service, InMemoryMemoryService)
    warnings = [
        r for r in caplog.records if r.name == RUNNER_LOGGER and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "ADK_SESSION_DB_URL" in warnings[0].getMessage()


class _ClosingClient:
    """Fake ``AsyncLLMClient`` that counts ``aclose`` calls."""

    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class _ClientAgent(_CardAgent):
    """A card agent whose ``llm_client`` hands out one recorded fake client."""

    def __init__(self, client: _ClosingClient, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fake_client = client
        self.client_requests = 0

    def llm_client(self, context: RequestContext, **kwargs: Any) -> Any:
        self.client_requests += 1
        return self.fake_client


@pytest.mark.parametrize(
    ("own_summarizer", "expected_requests", "expected_closed"),
    [
        pytest.param(False, 1, 1, id="default-summarizer-client-closed"),
        pytest.param(True, 0, 0, id="caller-summarizer-not-closed"),
    ],
)
async def test_build_runner_close_closes_only_its_own_summarizer_client(
    own_summarizer: bool, expected_requests: int, expected_closed: int
) -> None:
    """Covers REQ-016-10 and REQ-016-04."""
    client = _ClosingClient()
    agent = _ClientAgent(client, agent_name="Runner Close Agent")
    runner = build_runner(
        agent,
        MagicMock(spec=RequestContext),
        LlmAgent(name="runner_root", model=_StubLlm()),
        event_queue=_RecordingQueue(),  # type: ignore[arg-type]
        summarizer_model=_StubLlm() if own_summarizer else None,
        test=True,
    )
    assert any(isinstance(p, CompactionPlugin) for p in runner.plugin_manager.plugins)

    await runner.close()

    assert agent.client_requests == expected_requests
    assert client.closed == expected_closed
