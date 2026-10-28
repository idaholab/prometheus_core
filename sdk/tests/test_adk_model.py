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

"""Tests for the ADK model adapter over ``AsyncLLMClient``."""

from __future__ import annotations

from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.models import lite_llm
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import InMemoryRunner
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types

from prometheus_api.llm_client import ChatResponse

_TOOL_CALL_ID = "call_lookup_1"


class _RecordingLLMClient:
    """Fake ``AsyncLLMClient`` that records each ``chat`` call and answers with a tool call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: Any, model: str | None = None, **kwargs: Any) -> ChatResponse:
        self.calls.append({"messages": messages, "model": model, **kwargs})
        raw = {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": "fake-provider-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": _TOOL_CALL_ID,
                                "type": "function",
                                "function": {
                                    "name": "lookup_part",
                                    "arguments": '{"part_id": "P-7"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        return ChatResponse(
            text="",
            model_alias=model or "",
            provider_model="fake-provider-model",
            usage=raw["usage"],
            raw=raw,
        )


def lookup_part(part_id: str, tool_context: ToolContext) -> dict[str, str]:
    """Look up one part by its identifier."""
    # End the turn on the tool result, so the turn makes exactly one model call.
    tool_context.actions.skip_summarization = True
    return {"part_id": part_id, "status": "found"}


@pytest.fixture
def no_direct_litellm(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record any completion that bypasses the client and goes to ``litellm.acompletion``."""
    direct: list[dict[str, Any]] = []

    async def _forbidden(**kwargs: Any) -> Any:
        direct.append(kwargs)
        raise AssertionError("completion bypassed AsyncLLMClient.chat")

    # Import litellm only here, in PRODUCTION mode: a DEV-mode import at collection runs
    # load_dotenv() on sdk/.env and leaks its values into other tests.
    monkeypatch.setenv("LITELLM_MODE", "PRODUCTION")
    lite_llm._ensure_litellm_imported()
    import litellm

    monkeypatch.setattr(litellm, "acompletion", _forbidden)
    monkeypatch.setattr(lite_llm, "acompletion", _forbidden)
    return direct


async def test_adk_model_routes_through_llm_client(
    no_direct_litellm: list[dict[str, Any]],
) -> None:
    """Covers REQ-016-01."""
    # model.py imports litellm at load, so import it after the fixture set PRODUCTION mode.
    from prometheus_api.adk.model import prometheus_model

    client = _RecordingLLMClient()
    model = prometheus_model("large", client)  # type: ignore[arg-type]
    assert isinstance(model, LiteLlm)

    agent = LlmAgent(
        name="parts_agent",
        model=model,
        instruction="Look up the part the user names.",
        tools=[FunctionTool(lookup_part)],
    )
    runner = InMemoryRunner(agent=agent, app_name="adk-model-test")
    session = await runner.session_service.create_session(app_name="adk-model-test", user_id="u1")

    events = [
        event
        async for event in runner.run_async(
            user_id="u1",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Find part P-7.")]),
        )
    ]

    assert no_direct_litellm == []
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "large"
    assert [tool["function"]["name"] for tool in call["tools"]] == ["lookup_part"]
    for provider_arg in ("api_key", "api_base", "base_url"):
        assert provider_arg not in call

    function_calls = [
        part.function_call
        for event in events
        if event.content and event.content.parts
        for part in event.content.parts
        if part.function_call
    ]
    assert len(function_calls) == 1
    assert function_calls[0].name == "lookup_part"
    assert function_calls[0].args == {"part_id": "P-7"}
    assert function_calls[0].id == _TOOL_CALL_ID
