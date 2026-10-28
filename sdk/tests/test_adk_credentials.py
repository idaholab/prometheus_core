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

"""Tests for the ADK credential plugin.

The run uses in-memory ADK services and a stub model that calls one tool that declares a
``credential_resource``, so no real LLM or credential broker is involved.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from prometheus_api.adk.plugins.credentials import CredentialPlugin, tool_credential
from prometheus_api.credentials import Credential

APP = "credentials-test"
USER = "user-1"
TOOL = "read_deeplynx"
SECRET = "secret-123"


class _StubLlm(BaseLlm):
    """Calls the credential tool once, then answers with text after any tool response."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            parts = [types.Part(text="done")]
        else:
            parts = [types.Part(function_call=types.FunctionCall(name=TOOL, args={}))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


class _BrokerAgent:
    """The minimal agent surface the plugin reads: a fake credential broker."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, Optional[dict[str, Any]]]] = []

    async def get_credential(
        self, resource: str, scope: Optional[dict[str, Any]] = None
    ) -> Credential:
        self.requests.append((resource, scope))
        return Credential(
            resource=resource,
            value={"jwt_token": SECRET},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )


async def test_credential_token_scoped_to_call(caplog: pytest.LogCaptureFixture) -> None:
    """Covers REQ-016-07."""
    caplog.set_level(logging.DEBUG)
    seen: list[Optional[Credential]] = []

    def read_deeplynx(tool_context: ToolContext) -> dict[str, Any]:
        """Read DeepLynx with the per-call credential."""
        seen.append(tool_credential(tool_context))
        return {"status": "ok"}

    tool = FunctionTool(read_deeplynx)
    tool.credential_resource = "deeplynx"  # type: ignore[attr-defined]

    broker = _BrokerAgent()
    sessions = InMemorySessionService()
    app = App(
        name=APP,
        root_agent=LlmAgent(name="credential_agent", model=_StubLlm(), tools=[tool]),
        plugins=[CredentialPlugin(broker)],  # type: ignore[arg-type]
    )
    runner = Runner(app=app, session_service=sessions)
    session = await sessions.create_session(app_name=APP, user_id=USER)

    events = [
        event
        async for event in runner.run_async(
            user_id=USER,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="read")]),
        )
    ]

    # The tool got the broker's credential for its one call.
    assert broker.requests == [("deeplynx", None)]
    assert len(seen) == 1 and seen[0] is not None
    assert seen[0].value == {"jwt_token": SECRET}
    assert any(event.get_function_responses() for event in events)

    # The stored session carries the token in no event and no state key.
    stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=session.id)
    assert stored is not None
    assert stored.events, "the run stored no events"
    for event in stored.events:
        assert SECRET not in event.model_dump_json(), f"token in stored event {event.id}"
    for key, value in stored.state.items():
        assert SECRET not in f"{key}={value!r}", f"token in session state key {key!r}"

    # The yielded events and the logs do not carry it either.
    for event in events:
        assert SECRET not in event.model_dump_json(), f"token in yielded event {event.id}"
    for record in caplog.records:
        assert SECRET not in record.getMessage(), f"token in log record from {record.name}"
