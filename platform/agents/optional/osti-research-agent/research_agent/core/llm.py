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

import asyncio
import base64
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Literal, TypeVar

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

T = TypeVar("T")

# Waits before each retry of a model call that failed transiently. They add
# up to about 30 s: the LiteLLM proxy has answered 404 "page not found" for
# a model that works for about 15 s at a time, failing every call made then.
RETRY_DELAYS_S = (2.0, 8.0, 20.0)
# Statuses worth retrying: the proxy's passing 404, rate limits and server
# errors. Other 4xx (bad request, auth) fail the same way every time.
RETRY_STATUSES = frozenset({404, 408, 409, 429, 500, 502, 503, 504, 529})


def is_transient(exc: BaseException) -> bool:
    """True for a model-call error that a later attempt may not hit.

    Timeouts are not retried: the call already waited its full timeout, and
    a retry would double that against the run's time budget."""
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUSES
    try:
        import litellm
    except ImportError:  # pragma: no cover - litellm is a runtime dependency
        return False
    if isinstance(exc, litellm.Timeout):
        return False
    if isinstance(exc, litellm.APIConnectionError):
        return True
    return getattr(exc, "status_code", None) in RETRY_STATUSES


async def with_retries(call: Callable[[], Awaitable[T]], what: str) -> T:
    """Await ``call()``, retrying a transient failure after each delay in
    ``RETRY_DELAYS_S``. The last failure, or any other error, is raised."""
    for delay in RETRY_DELAYS_S:
        try:
            return await call()
        except Exception as exc:
            if not is_transient(exc):
                raise
            logger.warning(
                "%s failed (%s: %s); retrying in %.0f s",
                what,
                type(exc).__name__,
                str(exc)[:200],
                delay,
            )
        await asyncio.sleep(delay)
    return await call()


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

    Every model call, streamed or not, retries a transient failure (see
    ``with_retries``); ``ChatLiteLLM``'s own retry skips the proxy's 404.
    """
    route = config.model_route(role)
    retrying, auto_tool_choice = _chat_model_classes()
    model_class = retrying if forced_tool_choice else auto_tool_choice
    return model_class(
        api_base=route.base_url.rstrip("/"),
        api_key=route.api_key or "not-needed",
        model=route.model,
        custom_llm_provider=route.provider,
    )


_CHAT_MODEL_CLASSES = None


def _chat_model_classes():
    """The two ``ChatLiteLLM`` subclasses ``chat_model`` builds: one that
    retries transient failures, and one that also never forces a tool call.
    Built once, lazily, so importing this module never imports
    langchain_litellm."""
    global _CHAT_MODEL_CLASSES
    if _CHAT_MODEL_CLASSES is None:
        from langchain_litellm import ChatLiteLLM

        class RetryingChatLiteLLM(ChatLiteLLM):
            # Both the agents' streamed calls and plain ainvoke land here.
            async def acompletion_with_retry(self, run_manager=None, **kwargs: Any) -> Any:
                return await with_retries(
                    lambda: self.client.acompletion(**kwargs),
                    f"Model call to {self.model}",
                )

        class AutoToolChoiceChatLiteLLM(RetryingChatLiteLLM):
            def bind_tools(self, tools, *, tool_choice=None, **kwargs):
                if tool_choice not in (None, False, "auto", "none"):
                    tool_choice = "auto"
                return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

        _CHAT_MODEL_CLASSES = (RetryingChatLiteLLM, AutoToolChoiceChatLiteLLM)
    return _CHAT_MODEL_CLASSES


class LiteLLMClient:
    """Minimal chat-completion client against a LiteLLM proxy."""

    def __init__(self, base_url: str, api_key: str = None, model: str = "medium"):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def complete(self, prompt: str, *, max_tokens: int) -> str:
        """One completion; a transient failure is retried (``with_retries``)."""
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async def post() -> dict:
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
                return response.json()

        data = await with_retries(post, f"Completion from {self._model}")
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
