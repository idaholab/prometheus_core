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

"""Tests for the ADK approval plugin.

The run uses in-memory ADK services and a stub model that calls one counting tool, so no real
LLM is involved. The pause is the ADK ``adk_request_confirmation`` long-running call, which
the A2A bridge plugin maps to ``input-required``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from prometheus_api.adk.plugins.approval import ApprovalPlugin

APP = "approval-test"
USER = "user-1"
TOOL = "count_tool"
CONFIRMATION_CALL = "adk_request_confirmation"


class _StubLlm(BaseLlm):
    """Calls the counting tool once, then answers with text after any tool response."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            parts = [types.Part(text="done")]
        else:
            parts = [types.Part(function_call=types.FunctionCall(name=TOOL, args={"n": 1}))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


class _CardAgent:
    """The minimal agent surface the plugin reads: an agent card with one approval skill."""

    def get_raw_agent_card(self) -> dict[str, Any]:
        return {"skills": [{"id": TOOL, "name": "Count", "requires_approval": True}]}


def _function_responses(events: list[Event], name: str) -> list[dict[str, Any]]:
    return [
        response.response
        for event in events
        for response in event.get_function_responses()
        if response.name == name
    ]


async def _run(runner: Runner, session_id: str, message: types.Content) -> list[Event]:
    return [
        event
        async for event in runner.run_async(
            user_id=USER, session_id=session_id, new_message=message
        )
    ]


@pytest.mark.parametrize(
    ("confirmed", "expected_result", "expected_count"),
    [
        pytest.param(True, {"count": 1}, 1, id="confirmed-runs-tool"),
        pytest.param(False, {"status": "rejected"}, 0, id="rejected-skips-tool"),
    ],
)
async def test_approval_pauses_tool_until_confirmed(
    confirmed: bool, expected_result: dict[str, Any], expected_count: int
) -> None:
    """Covers REQ-016-05."""
    calls: list[int] = []

    def count_tool(n: int) -> dict[str, Any]:
        """Count one call."""
        calls.append(n)
        return {"count": len(calls)}

    sessions = InMemorySessionService()
    app = App(
        name=APP,
        root_agent=LlmAgent(name="approval_agent", model=_StubLlm(), tools=[count_tool]),
        plugins=[ApprovalPlugin(_CardAgent())],  # type: ignore[arg-type]
    )
    runner = Runner(app=app, session_service=sessions)
    session = await sessions.create_session(app_name=APP, user_id=USER)

    first = await _run(
        runner, session.id, types.Content(role="user", parts=[types.Part(text="count")])
    )

    # The pause: ADK emits its confirmation call as a long-running call, which the bridge
    # maps to input-required, and the tool has not run.
    requests = [
        (event, call)
        for event in first
        for call in event.get_function_calls()
        if call.name == CONFIRMATION_CALL
    ]
    assert len(requests) == 1
    request_event, request = requests[0]
    assert request.id in (request_event.long_running_tool_ids or set())
    assert request.args["originalFunctionCall"]["name"] == TOOL
    assert _function_responses(first, TOOL) == [{"status": "pending_approval"}]
    assert calls == [], "the tool ran before the user answered the confirmation"

    answer = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=request.id, name=CONFIRMATION_CALL, response={"confirmed": confirmed}
                )
            )
        ],
    )
    second = await _run(runner, session.id, answer)

    assert _function_responses(second, TOOL) == [expected_result]
    assert len(calls) == expected_count
