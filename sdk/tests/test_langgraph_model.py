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

"""Tests for ``PrometheusChatModel``, the LangChain chat model over ``AsyncLLMClient``."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from prometheus_api.langgraph.model import PrometheusChatModel
from prometheus_api.llm_client import AsyncLLMClient, ChatResponse
from prometheus_api.llm_client.tools import ToolCall


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


class _RecordingAsyncClient(AsyncLLMClient):
    """``AsyncLLMClient`` stand-in that records each ``chat`` call and replays a response."""

    def __init__(self, response: ChatResponse):  # no config: the fake never reaches a provider
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def chat(self, text_or_messages, model=None, trace_tags=None, **kwargs):  # type: ignore[override]
        self.calls.append({"messages": text_or_messages, "model": model, **kwargs})
        return self._response


def _tool_call_response() -> ChatResponse:
    return ChatResponse(
        text="",
        model_alias="small",
        provider_model="resolved-small",
        usage=None,
        raw={},
        tool_calls=(ToolCall(id="call_1", name="add", arguments={"a": 2, "b": 3}),),
        finish_reason="tool_calls",
    )


def _text_response() -> ChatResponse:
    return ChatResponse("5", "small", "resolved-small", None, {}, (), "stop")


async def test_bound_tools_go_through_chat_and_tool_calls_come_back():
    """Covers REQ-017-01."""
    client = _RecordingAsyncClient(_tool_call_response())
    model = PrometheusChatModel(alias="small", client=client)

    message = await model.bind_tools([add]).ainvoke([HumanMessage("What is 2 + 3?")])

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "small"
    assert call["messages"] == [{"role": "user", "content": "What is 2 + 3?"}]
    tools = call["tools"]
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "add"
    assert set(tools[0]["function"]["parameters"]["properties"]) == {"a", "b"}

    assert isinstance(message, AIMessage)
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0] == {
        "name": "add",
        "args": {"a": 2, "b": 3},
        "id": "call_1",
        "type": "tool_call",
    }


async def test_replayed_tool_message_reaches_chat_as_tool_role():
    """Covers REQ-017-01."""
    client = _RecordingAsyncClient(_text_response())
    model = PrometheusChatModel(alias="small", client=client)
    history = [
        HumanMessage("What is 2 + 3?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "add", "args": {"a": 2, "b": 3}, "id": "call_1"}],
        ),
        ToolMessage(content="5", tool_call_id="call_1"),
    ]

    message = await model.bind_tools([add]).ainvoke(history)

    sent = client.calls[0]["messages"]
    assert sent[1]["role"] == "assistant"
    assert sent[1]["tool_calls"][0]["id"] == "call_1"
    assert sent[2] == {"role": "tool", "tool_call_id": "call_1", "content": "5"}
    assert message.content == "5"
    assert message.tool_calls == []


def test_sync_invoke_raises_not_implemented():
    """Covers REQ-017-01."""
    model = PrometheusChatModel(alias="small", client=_RecordingAsyncClient(_text_response()))

    with pytest.raises(NotImplementedError):
        model.invoke("What is 2 + 3?")


def test_model_fields_carry_no_provider_url_key_or_model_id():
    """Covers REQ-017-01."""
    model = PrometheusChatModel(alias="small", client=_RecordingAsyncClient(_text_response()))

    own_fields = set(PrometheusChatModel.model_fields) - set(BaseChatModel.model_fields)
    assert own_fields == {"alias", "client"}
    for forbidden in ("api_key", "base_url", "api_base", "model_name", "model_id"):
        assert forbidden not in PrometheusChatModel.model_fields
    assert model.alias == "small"
