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

"""Tests for the artifact debug agent on the ADK runtime.

Each request goes through the agent's executor, as the A2A server sends it. ``adk_test_mode``
gives the runners in-memory session and artifact services shared per agent, and the agent's
LLM client raises on any call, so the skills prove they run with no model, database or
DeepLynx. CairoSVG needs the system cairo library, so the blocking conversion is stubbed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TaskState, TaskStatusUpdateEvent

AGENT_DIR = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location("artifact_debug_agent_module", AGENT_DIR / "agent.py")
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
ArtifactDebugAgent = _MODULE.ArtifactDebugAgent

CONVERSATION_ID = "test-conversation"
PNG_BYTES = b"\x89PNG\r\n\x1a\nstub-png"


@asynccontextmanager
async def _no_execution_record(params: dict[str, Any], context: Any) -> AsyncIterator[None]:
    yield


def _no_model(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("the artifact debug agent must not call a model")


def _make_agent() -> ArtifactDebugAgent:
    """Return the agent with in-memory ADK services and an LLM client that raises."""
    agent = ArtifactDebugAgent(agent_name="Artifact Debug Agent", agent_card_path=str(AGENT_DIR / "agent_card.json"))
    agent.load_agent_card()
    agent.adk_test_mode = True
    agent.llm_client = _no_model
    # The executor stores an execution record in DeepLynx for each request; skip it here.
    agent._create_execution_record = _no_execution_record
    return agent


def _request(task_id: str, skill_id: str, params: dict[str, Any]) -> MagicMock:
    """Return an A2A request context for ``skill_id``; each request has its own task."""
    context = MagicMock(spec=RequestContext)
    context.context_id = CONVERSATION_ID
    context.task_id = task_id
    context.current_task = None
    context.message = Message(
        message_id=f"message-{task_id}",
        role=Role.ROLE_USER,
        parts=[Part(text=json.dumps(params))],
        context_id=CONVERSATION_ID,
        metadata={"skillId": skill_id},
    )
    context.get_user_input.return_value = json.dumps(params)
    return context


async def _execute(agent: ArtifactDebugAgent, context: MagicMock) -> dict[str, Any]:
    """Run the request through the agent's executor and return its completed result."""
    event_queue = AsyncMock(spec=EventQueue)
    await agent.create_executor().execute(context, event_queue)
    events = [call.args[0] for call in event_queue.enqueue_event.await_args_list]
    final = [event for event in events if isinstance(event, TaskStatusUpdateEvent)][-1]
    assert final.status.state == TaskState.TASK_STATE_COMPLETED
    return json.loads(final.status.message.parts[0].text)


def _test_runner(agent: ArtifactDebugAgent) -> Any:
    """Return a test-mode runner; its artifact service is the one all the agent's runners share."""
    return agent.create_runner(
        _request("probe", "create_svg_artifact", {}),
        agent.adk_agents["create_svg_artifact"],
        event_queue=AsyncMock(spec=EventQueue),
        abort_signal=asyncio.Event(),
    )


@pytest.fixture(autouse=True)
def _local_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the synthetic "local" user: the tests send no platform user token."""
    monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")


@pytest.mark.asyncio
async def test_svg_then_png_save_through_adk_artifact_service_with_no_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _make_agent()
    runner = _test_runner(agent)
    service = runner.artifact_service
    scope = {"app_name": runner.app_name, "user_id": "local", "session_id": CONVERSATION_ID}
    await runner.close()

    loaded: list[str] = []
    service_class = type(service)
    real_load = service_class.load_artifact

    async def spy_load(self: Any, **kwargs: Any) -> Any:
        loaded.append(kwargs["filename"])
        return await real_load(self, **kwargs)

    # The service is a pydantic model, which refuses instance attributes; spy on its class.
    monkeypatch.setattr(service_class, "load_artifact", spy_load)

    converted: list[bytes] = []

    def fake_convert(source_svg: Path, target_png: Path) -> str:
        converted.append(source_svg.read_bytes())
        target_png.write_bytes(PNG_BYTES)
        return "stub"

    monkeypatch.setattr(ArtifactDebugAgent, "_convert_svg_to_png", staticmethod(fake_convert))

    svg = await _execute(agent, _request("task-svg", "create_svg_artifact", {"word": "hello"}))
    assert svg["status"] == "created"
    assert svg["artifact_name"] == "hello.svg"

    png = await _execute(agent, _request("task-png", "convert_svg_to_png", {"artifact_id": svg["artifact_id"]}))
    assert png["status"] == "converted", png
    assert png["artifact_name"] == "hello.png"

    keys = await service.list_artifact_keys(**scope)
    assert sorted(keys) == ["hello.png", "hello.svg"]

    saved_svg = await real_load(service, **scope, filename="hello.svg")
    saved_png = await real_load(service, **scope, filename="hello.png")
    assert saved_svg.inline_data.mime_type == "image/svg+xml"
    assert b">hello</text>" in saved_svg.inline_data.data
    assert saved_png.inline_data.mime_type == "image/png"
    assert saved_png.inline_data.data == PNG_BYTES

    # The PNG run loaded the saved SVG through the artifact service and converted its bytes.
    assert loaded == ["hello.svg"]
    assert converted == [saved_svg.inline_data.data]
