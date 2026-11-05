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

"""LangChain chat model over :class:`~prometheus_api.llm_client.AsyncLLMClient`.

The model carries only a semantic alias. Provider URLs, keys and model IDs stay in the
LLM configuration that the client resolves, so agent code never sees them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    InvalidToolCall,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UsageMetadata,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from prometheus_api.llm_client import AsyncLLMClient, ChatResponse
from prometheus_api.llm_client.tools import tool_result_message


def _to_openai(message: BaseMessage) -> dict[str, Any]:
    """Map one LangChain message to the OpenAI message dict that ``chat`` accepts."""
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": message.content}
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, AIMessage):
        result: dict[str, Any] = {"role": "assistant", "content": message.text or None}
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
                }
                for call in message.tool_calls
            ]
        return result
    if isinstance(message, ToolMessage):
        return tool_result_message(message.tool_call_id, message.content)
    raise TypeError(f"PrometheusChatModel does not support {type(message).__name__}")


def _usage_metadata(usage: dict[str, Any] | None) -> UsageMetadata | None:
    if not usage:
        return None
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
    )


def _to_ai_message(response: ChatResponse) -> AIMessage:
    """Build an AIMessage from the normalized text, tool calls and usage of a response."""
    tool_calls: list[ToolCall] = []
    invalid_tool_calls: list[InvalidToolCall] = []
    for call in response.tool_calls:
        if call.arguments_error:
            invalid_tool_calls.append(
                InvalidToolCall(
                    type="invalid_tool_call",
                    id=call.id,
                    name=call.name,
                    args=None,
                    error=call.arguments_error,
                )
            )
        else:
            tool_calls.append(
                ToolCall(type="tool_call", id=call.id, name=call.name, args=call.arguments)
            )
    return AIMessage(
        content=response.text,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        usage_metadata=_usage_metadata(response.usage),
    )


def _openai_tool_choice(tool_choice: str | dict[str, Any]) -> str | dict[str, Any]:
    # LangChain spells "call some tool" as "any" and names a tool by its bare name.
    if isinstance(tool_choice, dict) or tool_choice in ("auto", "none", "required"):
        return tool_choice
    if tool_choice == "any":
        return "required"
    return {"type": "function", "function": {"name": tool_choice}}


class PrometheusChatModel(BaseChatModel):
    """Async-only chat model that sends a semantic alias through ``AsyncLLMClient.chat``."""

    alias: str = "default"
    client: AsyncLLMClient

    @property
    def _llm_type(self) -> str:
        return "prometheus-llm-client"

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        response = await self.client.chat(
            [_to_openai(message) for message in messages],
            model=self.alias,
            tools=kwargs.get("tools") or None,
            tool_choice=kwargs.get("tool_choice"),
        )
        return ChatResult(generations=[ChatGeneration(message=_to_ai_message(response))])

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:
        raise NotImplementedError("PrometheusChatModel is async only; use ainvoke")

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type[BaseModel] | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Bind tools as OpenAI function schemas, as the OpenAI chat models do."""
        if tool_choice is not None:
            kwargs["tool_choice"] = _openai_tool_choice(tool_choice)
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)
