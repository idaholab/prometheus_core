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
"""Context compaction for ADK model calls (PPLT-83).

The plugin rewrites only the outgoing ``LlmRequest.contents``; stored session events never
change. Above the trigger ratio of the model alias's input window it keeps a token-budgeted
tail, replaces the older middle with one reference-only summary plus a mechanical anchor index,
and turns old function responses into one-line stubs that keep their artifact IDs.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from ...llm_client import AsyncLLMClient

logger = logging.getLogger(__name__)

SUMMARY_PROMPT_VERSION = "compaction-summary/v1"
SUMMARY_PROMPT = (
    "Summarize the conversation excerpt below for the assistant that continues it. Keep the "
    "user's goals, decisions made, facts learned, tool results that matter, and open questions. "
    "Be concise. Do not invent identifiers; an exact index of identifiers is attached "
    "separately.\n\nExcerpt:\n"
)
REFERENCE_START = "[reference only]"
REFERENCE_END = "[/reference only]"

PROMPT_TOKENS_KEY = "compaction:prompt_tokens"
COOLDOWN_KEY = "compaction:cooldown"

_DEEPLYNX_URI = re.compile(r"deeplynx://[^\s\"'<>)\]},]+")
_ARTIFACT_ID_KEYS = frozenset({"artifact_id", "artifactId", "artifact_ids", "artifactIds"})
_CONTEXT_WINDOW_MARKERS = ("context window", "context_length_exceeded", "maximum context length")
_EXCERPT_RESULT_CHARS = 500


def estimate_tokens(contents: list[types.Content]) -> int:
    """Rough token count of request contents: four characters per token."""
    chars = sum(
        len(part.model_dump_json(exclude_none=True)) for c in contents for part in c.parts or []
    )
    return chars // 4


@dataclass(frozen=True)
class CompactionPolicy:
    """When and how far the compaction plugin shrinks a model request."""

    trigger_ratio: float = 0.7
    tail_tokens: int = 8000
    cooldown_calls: int = 3
    input_windows: dict[str, int] = field(
        default_factory=lambda: {"small": 32_000, "medium": 128_000, "large": 128_000}
    )
    default_input_window: int = 32_000
    count_tokens: Callable[[list[types.Content]], int] = estimate_tokens

    def input_window(self, alias: str | None) -> int:
        """Input window in tokens for a model alias, or the default for an unknown alias."""
        return self.input_windows.get(alias or "", self.default_input_window)


@dataclass
class _Anchors:
    call_ids: list[str] = field(default_factory=list)
    uris: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)

    def add(self, bucket: list[str], value: str) -> None:
        if value and value not in bucket:
            bucket.append(value)

    def scan(self, value: Any) -> None:
        """Collect every ``deeplynx://`` URI and artifact ID found in a JSON-like value."""
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _ARTIFACT_ID_KEYS:
                    for artifact_id in item if isinstance(item, list) else [item]:
                        if isinstance(artifact_id, str):
                            self.add(self.artifact_ids, artifact_id)
                self.scan(item)
        elif isinstance(value, list):
            for item in value:
                self.scan(item)
        elif isinstance(value, str):
            for uri in _DEEPLYNX_URI.findall(value):
                self.add(self.uris, uri)

    def scan_content(self, content: types.Content) -> None:
        for part in content.parts or []:
            if part.text:
                self.scan(part.text)
            if part.function_call:
                self.add(self.call_ids, part.function_call.id or "")
                self.scan(part.function_call.args)
            if part.function_response:
                self.add(self.call_ids, part.function_response.id or "")
                self.scan(part.function_response.response)

    def index(self) -> str:
        lines = ["Anchor index (exact identifiers from the compacted turns):"]
        lines.append("tool_call_ids: " + (", ".join(self.call_ids) or "none"))
        lines.append("deeplynx_uris: " + (", ".join(self.uris) or "none"))
        lines.append("artifact_ids: " + (", ".join(self.artifact_ids) or "none"))
        return "\n".join(lines)


def _stub(response: types.FunctionResponse) -> types.FunctionResponse:
    """A one-line stand-in for an old function response that keeps its artifact IDs."""
    anchors = _Anchors()
    anchors.scan(response.response)
    kept = anchors.uris + anchors.artifact_ids
    line = f"[compacted] result of {response.name}"
    if kept:
        line += "; artifacts: " + ", ".join(kept)
    return types.FunctionResponse(id=response.id, name=response.name, response={"result": line})


def _stub_old_responses(contents: list[types.Content]) -> list[types.Content]:
    """Copy of ``contents`` with function responses stubbed in all but the last content."""
    stubbed = []
    for index, content in enumerate(contents):
        parts = content.parts or []
        if index == len(contents) - 1 or not any(p.function_response for p in parts):
            stubbed.append(content)
            continue
        new_parts = [
            types.Part(function_response=_stub(p.function_response)) if p.function_response else p
            for p in parts
        ]
        stubbed.append(types.Content(role=content.role, parts=new_parts))
    return stubbed


def _has_function_response(content: types.Content) -> bool:
    return any(part.function_response for part in content.parts or [])


def _user_text(content: types.Content) -> str:
    if content.role != "user" or _has_function_response(content):
        return ""
    return "\n".join(part.text for part in content.parts or [] if part.text).strip()


def _tail_start(contents: list[types.Content], policy: CompactionPolicy) -> int:
    """Start of the newest contents that fit ``tail_tokens``; a response keeps its call."""
    start = len(contents) - 1
    tokens = policy.count_tokens(contents[start:])
    while start > 0:
        tokens += policy.count_tokens([contents[start - 1]])
        if tokens > policy.tail_tokens:
            break
        start -= 1
    while start > 0 and _has_function_response(contents[start]):
        start -= 1
    return start


def _excerpt(contents: list[types.Content]) -> str:
    lines = []
    for content in contents:
        for part in content.parts or []:
            if part.text:
                lines.append(f"{content.role}: {part.text}")
            if part.function_call:
                call = part.function_call
                args = json.dumps(call.args or {}, default=str)
                lines.append(f"{content.role}: call {call.name} id={call.id} args={args}")
            if part.function_response:
                result = part.function_response
                body = json.dumps(result.response or {}, default=str)[:_EXCERPT_RESULT_CHARS]
                lines.append(f"{content.role}: result of {result.name} id={result.id}: {body}")
    return "\n".join(lines)


def _response_text(response: LlmResponse | None) -> str:
    if response is None or response.content is None:
        return ""
    return "\n".join(part.text for part in response.content.parts or [] if part.text).strip()


def _is_context_window_error(error: Exception) -> bool:
    if type(error).__name__ == "ContextWindowExceededError":
        return True
    message = str(error).lower()
    return any(marker in message for marker in _CONTEXT_WINDOW_MARKERS)


class CompactionPlugin(BasePlugin):
    """Shrinks an oversized model request with a reference-only summary of its middle."""

    def __init__(
        self,
        policy: CompactionPolicy,
        summarizer_model: BaseLlm,
        *,
        client: AsyncLLMClient | None = None,
    ) -> None:
        """``client`` is the summarizer's LLM client when the plugin owns it; ``close`` closes it."""
        super().__init__(name="compaction")
        self.policy = policy
        self.summarizer_model = summarizer_model
        self._client = client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        usage = llm_response.usage_metadata
        if usage is not None and usage.prompt_token_count is not None:
            callback_context.state[PROMPT_TOKENS_KEY] = usage.prompt_token_count
        return None

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        state = callback_context.state
        cooldown = int(state.get(COOLDOWN_KEY, 0) or 0)
        if cooldown > 0:
            state[COOLDOWN_KEY] = cooldown - 1
            return None
        tokens = max(
            int(state.get(PROMPT_TOKENS_KEY, 0) or 0),
            self.policy.count_tokens(llm_request.contents),
        )
        limit = self.policy.trigger_ratio * self.policy.input_window(llm_request.model)
        if tokens > limit:
            await self.compact(llm_request)
            state[COOLDOWN_KEY] = self.policy.cooldown_calls
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> LlmResponse | None:
        if not _is_context_window_error(error):
            return None
        model = getattr(callback_context.get_invocation_context().agent, "canonical_model", None)
        if not isinstance(model, BaseLlm) or not await self.compact(llm_request):
            return None
        callback_context.state[COOLDOWN_KEY] = self.policy.cooldown_calls
        try:
            response = None
            async for response in model.generate_content_async(llm_request):
                pass
            return response
        except Exception as retry_error:
            logger.warning("Compacted retry after a context-window error failed: %s", retry_error)
            return None

    async def compact(self, llm_request: LlmRequest) -> bool:
        """Rewrite ``llm_request.contents`` in place; return whether it was compacted.

        The request is left as it was when there is no middle to drop, the summary call
        fails, or the result is not smaller.
        """
        original = llm_request.contents
        contents = _stub_old_responses(original)
        start = _tail_start(contents, self.policy)
        middle, tail = contents[:start], contents[start:]
        if not middle:
            return False
        try:
            summary = await self._summarize(middle)
        except Exception as error:
            logger.warning("Compaction summary failed; sending the request uncompacted: %s", error)
            return False

        anchors = _Anchors()
        for content in original[:start]:
            anchors.scan_content(content)
        text = (
            f"{REFERENCE_START} ({SUMMARY_PROMPT_VERSION})\n"
            f"Summary of earlier turns:\n{summary}\n\n{anchors.index()}\n{REFERENCE_END}"
        )
        if not any(_user_text(content) for content in tail):
            request = next((t for t in map(_user_text, reversed(middle)) if t), "")
            if request:
                text += f"\n\nThe request still being worked on, restated:\n{request}"
        compacted = [types.Content(role="user", parts=[types.Part(text=text)]), *tail]

        if self.policy.count_tokens(compacted) >= self.policy.count_tokens(original):
            logger.info("Compaction did not shrink the request; sending it uncompacted")
            return False
        llm_request.contents = compacted
        return True

    async def _summarize(self, middle: list[types.Content]) -> str:
        request = LlmRequest(
            model=self.summarizer_model.model,
            contents=[
                types.Content(
                    role="user", parts=[types.Part(text=SUMMARY_PROMPT + _excerpt(middle))]
                )
            ],
        )
        response = None
        async for response in self.summarizer_model.generate_content_async(request):
            pass
        summary = _response_text(response)
        if not summary:
            raise ValueError("the summarizer returned no text")
        return summary
