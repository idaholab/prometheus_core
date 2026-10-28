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

"""The one thing the pipeline needs from an LLM: a completion.

Implemented directly over the LiteLLM proxy's OpenAI-compatible API via
httpx, so research_agent never has to import prometheus_api.llm_client to
get an answer out of a model. The A2A executor (agent.py) still uses
prometheus_api's LLMClient for its own auth/tracing, but adapts it to this
same `complete()` shape before handing it to the pipeline - see agent.py.
"""

import base64
import logging
from typing import TYPE_CHECKING, Awaitable, Callable, List, Literal

import httpx

if TYPE_CHECKING:  # Keep optional LangChain imports out of module initialization.
    from langchain_core.language_models.chat_models import BaseChatModel

    from research_agent.core.config import AgentConfig

logger = logging.getLogger(__name__)

CompleteFn = Callable[..., Awaitable[str]]
# (prompt, images: list[bytes], *, max_tokens) -> str
VlmCompleteFn = Callable[..., Awaitable[str]]
# text -> embedding vector
EmbedFn = Callable[[str], Awaitable[List[float]]]


def chat_model(
    config: "AgentConfig",
    role: Literal["orchestrator", "analyzer", "verifier", "vlm"],
    *,
    forced_tool_choice: bool = True,
) -> "BaseChatModel":
    """Build a LangChain chat model for the deep-agent engine.

    ``role`` selects the resolved route for that semantic model. Registry
    profiles keep using their aliases through the local proxy; direct profiles
    use their configured provider endpoint, key, and model. Imported lazily so
    the pipeline engine and the CLI never pull in LangChain provider packages.

    ``forced_tool_choice=False`` turns any forced tool choice ("any",
    "required", or one named tool) into "auto" when tools are bound. Some
    providers reject a forced choice outright - Claude on Bedrock answers
    "tool_choice: type "tool" and "any" are not supported for this model" -
    and LangChain's structured output (``create_agent(response_format=...)``)
    always forces one.
    """
    from langchain_litellm import ChatLiteLLM

    route = config.model_route(role)
    model_class = ChatLiteLLM if forced_tool_choice else _auto_tool_choice_class()
    return model_class(
        api_base=route.base_url.rstrip("/"),
        api_key=route.api_key or "not-needed",
        model=route.model,
        custom_llm_provider=route.provider,
    )


_AUTO_TOOL_CHOICE_CLASS = None


def _auto_tool_choice_class():
    """``ChatLiteLLM`` whose ``bind_tools`` never forces a tool call (built
    once, lazily, so importing this module never imports langchain_litellm)."""
    global _AUTO_TOOL_CHOICE_CLASS
    if _AUTO_TOOL_CHOICE_CLASS is None:
        from langchain_litellm import ChatLiteLLM

        class AutoToolChoiceChatLiteLLM(ChatLiteLLM):
            def bind_tools(self, tools, *, tool_choice=None, **kwargs):
                if tool_choice not in (None, False, "auto", "none"):
                    tool_choice = "auto"
                return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

        _AUTO_TOOL_CHOICE_CLASS = AutoToolChoiceChatLiteLLM
    return _AUTO_TOOL_CHOICE_CLASS


class LiteLLMClient:
    """Minimal chat-completion client against a LiteLLM proxy."""

    def __init__(self, base_url: str, api_key: str = None, model: str = "medium"):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def complete(self, prompt: str, *, max_tokens: int) -> str:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"] or ""


class LiteLLMEmbedder:
    """Text embeddings over the LiteLLM proxy's OpenAI-compatible ``/embeddings``
    endpoint. Backs the knowledge store's semantic retrieval; no new
    provider keys (the proxy maps the ``embedding`` alias to a real model)."""

    def __init__(self, base_url: str, api_key: str = None, model: str = "embedding"):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._base_url}/embeddings",
                headers=headers,
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()

        # OpenAI-compatible: {"data": [{"index": i, "embedding": [...]}, ...]}
        rows = sorted(data["data"], key=lambda d: d.get("index", 0))
        return [row["embedding"] for row in rows]

    async def embed(self, text: str) -> List[float]:
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []


class LiteLLMVlmClient:
    """Multimodal chat-completion client against a LiteLLM proxy.

    Sends OpenAI-style content parts: the text prompt plus one ``image_url``
    part per PNG (as a base64 ``data:`` URI). Used by optional figure analysis.
    """

    def __init__(self, base_url: str, api_key: str = None, model: str = "medium"):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def complete(
        self,
        prompt: str,
        images: List[bytes],
        *,
        max_tokens: int,
    ) -> str:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        content: list = [{"type": "text", "text": prompt}]
        for png in images:
            b64 = base64.b64encode(png).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )

        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"] or ""
