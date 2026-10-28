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

"""Tests for the A2A bridge plugin and its ``bridge_events`` switch on ``build_runner``.

The run uses ``build_runner(test=True)`` with in-memory ADK services and a stub model that calls
one ordinary tool and one long-running tool, so no real LLM or DeepLynx is involved. The agent
records the calls the bridge makes to its ``send_*`` helpers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from google.adk.agents import LlmAgent
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.tools.long_running_tool import LongRunningFunctionTool
from google.genai import types

from prometheus_api.adk.plugins.bridge import (
    PENDING_FUNCTION_CALL_IDS_METADATA_KEY,
    A2ABridgePlugin,
)
from prometheus_api.adk.runner import build_runner
from prometheus_api.agent import PrometheusAgent

USER = "user-1"
TOOL = "lookup"
PAUSE_TOOL = "wait_for_user"
ARTIFACT_URI = "deeplynx://organizations/1/projects/2/items/42"


class _StubLlm(BaseLlm):
    """Calls the ordinary and the long-running tool once, then answers with text."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            parts = [types.Part(text="done")]
        else:
            parts = [
                types.Part(function_call=types.FunctionCall(name=TOOL, args={})),
                types.Part(function_call=types.FunctionCall(name=PAUSE_TOOL, args={})),
            ]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


class _RecordingAgent(PrometheusAgent):
    """A minimal Prometheus agent that records the bridge's calls to its ``send_*`` helpers."""

    def __init__(self) -> None:
        super().__init__(agent_name="Bridge Test Agent")
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_raw_agent_card(self) -> dict[str, Any]:
        return {"name": self.agent_name, "skills": []}

    async def send_status_update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        self.calls.append(("send_status_update", kwargs))

    async def send_input_required(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        self.calls.append(("send_input_required", kwargs))

    async def send_artifact_reference(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(("send_artifact_reference", kwargs))
        return kwargs["uri"]

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def lookup() -> dict[str, Any]:
    """Look something up."""
    return {"found": True}


def wait_for_user() -> dict[str, Any]:
    """Wait for the user to answer."""
    return {"status": "pending"}


def _runner(agent: _RecordingAgent, **kwargs: Any) -> Runner:
    return build_runner(
        agent,
        MagicMock(spec=RequestContext),
        LlmAgent(
            name="bridge_root",
            model=_StubLlm(),
            tools=[lookup, LongRunningFunctionTool(wait_for_user)],
        ),
        event_queue=MagicMock(),
        compaction=None,
        test=True,
        **kwargs,
    )


async def _run(runner: Runner) -> list[Event]:
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id=USER)
    message = types.Content(role="user", parts=[types.Part(text="go")])
    return [
        event
        async for event in runner.run_async(
            user_id=USER, session_id=session.id, new_message=message
        )
    ]


def _bridge(runner: Runner) -> A2ABridgePlugin:
    bridges = [p for p in runner.plugin_manager.plugins if isinstance(p, A2ABridgePlugin)]
    assert len(bridges) == 1
    return bridges[0]


def _pending_ids(events: list[Event]) -> list[str]:
    return [
        call.id
        for event in events
        for call in event.get_function_calls()
        if call.id in (event.long_running_tool_ids or set())
    ]


async def test_bridge_events_by_default_emit_status_and_input_required() -> None:
    """Covers REQ-016-11: build_runner's default bridge sends the A2A status events."""
    agent = _RecordingAgent()

    events = await _run(_runner(agent))

    statuses = [kw["message"] for name, kw in agent.calls if name == "send_status_update"]
    assert f"Running {TOOL}" in statuses
    assert f"Running {PAUSE_TOOL}" not in statuses, "a pending call is a pause, not a status"
    pauses = [kw for name, kw in agent.calls if name == "send_input_required"]
    pending = _pending_ids(events)
    assert len(pending) == 1
    assert len(pauses) == 1
    assert pauses[0]["metadata"] == {PENDING_FUNCTION_CALL_IDS_METADATA_KEY: pending}


@pytest.mark.parametrize("bridge_events", [True, False], ids=["events-on", "events-off"])
async def test_bridge_emits_artifact_reference_with_or_without_events(
    bridge_events: bool,
) -> None:
    """Covers REQ-016-11: artifact references go through send_artifact_reference either way."""
    agent = _RecordingAgent()
    runner = _runner(agent, bridge_events=bridge_events)

    uri = await _bridge(runner).emit_artifact_reference(42, "plot.png", "image/png", ARTIFACT_URI)

    assert uri == ARTIFACT_URI
    assert agent.names() == ["send_artifact_reference"]
    sent = {k: v for k, v in agent.calls[0][1].items() if k not in ("context", "event_queue")}
    assert sent == {
        "name": "plot.png",
        "description": "plot.png",
        "uri": ARTIFACT_URI,
        "mime_type": "image/png",
        "metadata": {"deeplynx_item_id": 42, "deeplynx_file_id": 42},
    }


async def test_bridge_events_off_emits_no_status_or_input_required() -> None:
    """Covers REQ-016-11: build_runner(bridge_events=False) keeps the run's events off."""
    agent = _RecordingAgent()
    runner = _runner(agent, bridge_events=False)

    events = await _run(runner)
    await _bridge(runner).emit_artifact_reference(42, "plot.png", "image/png", ARTIFACT_URI)

    # The same run reached the tool call, the pause and the model text.
    assert any(call.name == TOOL for event in events for call in event.get_function_calls())
    assert len(_pending_ids(events)) == 1
    assert any(event.content and any(p.text for p in event.content.parts or []) for event in events)
    assert agent.names() == ["send_artifact_reference"]
