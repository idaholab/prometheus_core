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

"""Tests for the TEMPLATE_NAME agent's TEMPLATE_SKILL_ID skill on the ADK runtime.

Each test sends one A2A request through the agent's executor. The skill's ADK agent gets a
stub model instead of an LLM, and ``adk_test_mode`` keeps sessions and artifacts in memory,
so no model provider, database or DeepLynx is needed. Extend these as you implement your
agent: every input-validation branch and every distinct result shape deserves a test. Run
with `uv run pytest`.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.types import Message, Part, Role, TaskState, TaskStatusUpdateEvent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agent import TEMPLATE_CLASSAgent

SKILL_ID = "TEMPLATE_SKILL_ID"
AGENT_CARD = Path(__file__).resolve().parents[1] / "agent_card.json"


class StubLlm(BaseLlm):
    """Calls save_report once, then replies with the skill's JSON result."""

    model: str = "stub"
    calls: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.calls += 1
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            reply = {"status": "success", "input_received": "hello", "message": "Report saved."}
            parts = [types.Part(text=json.dumps(reply))]
        else:
            call = types.FunctionCall(
                name="save_report", args={"title": "Findings", "body": "All good."}
            )
            parts = [types.Part(function_call=call)]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def _make_agent(stub: BaseLlm) -> TEMPLATE_CLASSAgent:
    """Return the agent with a stub model on its skill and in-memory ADK services."""
    agent = TEMPLATE_CLASSAgent(agent_name="TEMPLATE_NAME Agent", agent_card_path=str(AGENT_CARD))
    agent.load_agent_card()
    agent.adk_test_mode = True
    agent.compaction = None
    # Change the instance dict, never the class dict.
    agent.adk_agents = {SKILL_ID: agent.adk_agents[SKILL_ID].clone(update={"model": stub})}
    # The executor stores an execution record in DeepLynx for each request; skip it here.
    agent._create_execution_record = _no_execution_record
    return agent


@asynccontextmanager
async def _no_execution_record(params: dict[str, Any], context: Any) -> AsyncIterator[None]:
    yield


def _request(context: MagicMock, params: dict[str, Any]) -> MagicMock:
    """Make the mocked context an A2A request for the skill with ``params``."""
    context.current_task = None
    context.message = Message(
        message_id="test-message",
        role=Role.ROLE_USER,
        parts=[Part(text=json.dumps(params))],
        context_id=context.context_id,
        metadata={"skillId": SKILL_ID},
    )
    context.get_user_input.return_value = json.dumps(params)
    return context


async def _execute(agent: TEMPLATE_CLASSAgent, context: MagicMock, event_queue: AsyncMock) -> None:
    """Run the request through the agent's executor, as the A2A server does."""
    await agent.create_executor().execute(context, event_queue)


def _statuses(event_queue: AsyncMock) -> list[TaskStatusUpdateEvent]:
    events = [call.args[0] for call in event_queue.enqueue_event.await_args_list]
    return [event for event in events if isinstance(event, TaskStatusUpdateEvent)]


async def _saved_artifacts(agent: TEMPLATE_CLASSAgent, context: MagicMock) -> list[str]:
    """Return the artifact names that the skill saved in this conversation."""
    runner = agent.create_runner(
        context,
        agent.adk_agents[SKILL_ID],
        event_queue=AsyncMock(),
        abort_signal=asyncio.Event(),
    )
    try:
        return await runner.artifact_service.list_artifact_keys(
            app_name=runner.app_name, user_id="local", session_id=context.context_id
        )
    finally:
        await runner.close()


@pytest.fixture(autouse=True)
def _local_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the synthetic "local" user: the tests send no platform user token."""
    monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")


async def test_skill_saves_one_report_and_completes(context, event_queue):
    stub = StubLlm()
    agent = _make_agent(stub)

    await _execute(agent, _request(context, {"input_data": "hello"}), event_queue)

    assert await _saved_artifacts(agent, context) == ["report.md"]
    final = _statuses(event_queue)[-1]
    assert final.status.state == TaskState.TASK_STATE_COMPLETED
    result = json.loads(final.status.message.parts[0].text)
    assert result["status"] == "success"
    assert result["input_received"] == "hello"
    # One call that asks for the tool, one that answers after its response.
    assert stub.calls == 2


async def test_skill_rejects_missing_input(context, event_queue):
    stub = StubLlm()
    agent = _make_agent(stub)

    with pytest.raises(ValueError, match="input_data"):
        await _execute(agent, _request(context, {}), event_queue)

    final = _statuses(event_queue)[-1]
    assert final.status.state == TaskState.TASK_STATE_FAILED
    assert stub.calls == 0
    assert await _saved_artifacts(agent, context) == []
