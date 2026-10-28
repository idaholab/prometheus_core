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
"""The ADK model over ``AsyncLLMClient``: every completion goes through a profile alias."""

import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

from ..llm_client import AsyncLLMClient

if TYPE_CHECKING:
    # litellm loads the nearest .env at import time unless LITELLM_MODE is set. ADK imports
    # it lazily with LITELLM_MODE defaulted to PRODUCTION, so importing this module must not.
    from litellm import ModelResponse

# LiteLlm sets these on a streaming request; AsyncLLMClient.chat does not stream.
_STREAM_ARGS = ("stream", "stream_options")


class _PrometheusTransport(LiteLLMClient):
    """LiteLlm transport that sends each completion through ``AsyncLLMClient.chat``."""

    def __init__(self, client: AsyncLLMClient) -> None:
        self._client = client

    async def acompletion(  # type: ignore[override]  # streams as AsyncIterator
        self,
        model: Any,
        messages: Any,
        tools: Any,
        **kwargs: Any,
    ) -> "ModelResponse | AsyncIterator[ModelResponse]":
        # Same guard as ADK's _ensure_litellm_imported, for a call that does not come from LiteLlm.
        os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
        from litellm import ModelResponse

        stream = bool(kwargs.get("stream"))
        tool_choice = kwargs.pop("tool_choice", None)
        call_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in _STREAM_ARGS and value is not None
        }
        response = await self._client.chat(
            messages,
            model=model,
            tools=tools or None,
            tool_choice=tool_choice if tools else None,
            **call_kwargs,
        )
        raw = response.raw
        result = raw if isinstance(raw, ModelResponse) else ModelResponse(**raw)
        if stream:
            return _single_chunk(result)
        return result


async def _single_chunk(response: "ModelResponse") -> "AsyncIterator[ModelResponse]":
    """Yield the whole non-streaming response as the only chunk of a stream."""
    yield response


class PrometheusLlm(LiteLlm):
    """ADK ``LiteLlm`` bound to a request-scoped ``AsyncLLMClient`` and a flavor alias."""

    def __init__(self, alias: str, client: AsyncLLMClient) -> None:
        super().__init__(model=alias, llm_client=_PrometheusTransport(client))


def prometheus_model(alias: str, client: AsyncLLMClient) -> LiteLlm:
    """Build the ADK model that sends every completion through ``client`` with ``alias``."""
    return PrometheusLlm(alias, client)
