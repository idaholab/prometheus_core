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

"""Tests for the ADK context-compaction plugin.

The run uses in-memory ADK services, a stub agent model that records the request it receives,
and a stub summarizer, so no real LLM is involved. The session is seeded with 40 synthetic
events; a small input window drives the trigger through the real ``before_model_callback``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from prometheus_api.adk.plugins.compaction import (
    REFERENCE_START,
    CompactionPlugin,
    CompactionPolicy,
)

APP = "compaction-test"
USER = "user-1"
AGENT = "compaction_agent"
TOOL = "lookup_item"
CYCLES = 10  # four events per cycle: 40 seeded events
URI_COUNT = 6
PADDING = "The engineer reviewed the reactor component drawings in detail. " * 4


class _RecordingLlm(BaseLlm):
    """Agent model that keeps a copy of each request it receives and answers with text."""

    model: str = "stub"
    requests: list[LlmRequest] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request.model_copy(deep=True))
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="ok")]))


class _StubSummarizer(BaseLlm):
    """Summarizer that answers every request with one fixed sentence."""

    model: str = "stub-summarizer"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        text = "The user looked up several items."
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _uri(index: int) -> str:
    return f"deeplynx://org/1/project/2/items/{100 + index}"


def _seed_events() -> list[Event]:
    """40 events: user text, tool call, tool result, model text; 6 results carry a URI."""
    events: list[Event] = []
    for i in range(CYCLES):
        call_id = f"call_{i}"
        result: dict[str, Any] = {"status": "found", "note": PADDING}
        if i < URI_COUNT:
            result.update({"uri": _uri(i), "artifact_id": f"artifact-{i}"})
        events += [
            Event(
                invocation_id=f"inv-{i}",
                author="user",
                content=types.Content(
                    role="user", parts=[types.Part(text=f"Question {i}. {PADDING}")]
                ),
            ),
            Event(
                invocation_id=f"inv-{i}",
                author=AGENT,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                id=call_id, name=TOOL, args={"item": i}
                            )
                        )
                    ],
                ),
            ),
            Event(
                invocation_id=f"inv-{i}",
                author=AGENT,
                content=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=call_id, name=TOOL, response=result
                            )
                        )
                    ],
                ),
            ),
            Event(
                invocation_id=f"inv-{i}",
                author=AGENT,
                content=types.Content(
                    role="model", parts=[types.Part(text=f"Answer {i}. {PADDING}")]
                ),
            ),
        ]
    return events


def _request_text(contents: list[types.Content]) -> str:
    return "\n".join(
        part.model_dump_json(exclude_none=True)
        for content in contents
        for part in content.parts or []
    )


def _shape(content: types.Content) -> tuple[str | None, list[str]]:
    """Role plus the text or the call ID of each part; a stubbed result keeps its call ID."""
    keys = []
    for part in content.parts or []:
        if part.function_call:
            keys.append(f"call:{part.function_call.id}")
        elif part.function_response:
            keys.append(f"result:{part.function_response.id}")
        else:
            keys.append(f"text:{part.text}")
    return content.role, keys


async def _run(plugins: list[BasePlugin]) -> tuple[LlmRequest, list[dict[str, Any]], list[Event]]:
    """Run one turn on a seeded session; return the model request and the stored events."""
    model = _RecordingLlm(requests=[])
    sessions = InMemorySessionService()
    app = App(
        name=APP,
        root_agent=LlmAgent(name=AGENT, model=model, instruction="Answer briefly."),
        plugins=plugins,
    )
    runner = Runner(app=app, session_service=sessions)
    session = await sessions.create_session(app_name=APP, user_id=USER)
    for event in _seed_events():
        await sessions.append_event(session, event)
    stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=session.id)
    assert stored is not None
    before = [event.model_dump() for event in stored.events]
    assert len(before) == 4 * CYCLES

    async for _ in runner.run_async(
        user_id=USER,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="Summarize item 9.")]),
    ):
        pass

    after = await sessions.get_session(app_name=APP, user_id=USER, session_id=session.id)
    assert after is not None
    assert len(model.requests) == 1
    return model.requests[0], before, after.events


async def test_compaction_keeps_anchors() -> None:
    """Covers REQ-016-04."""
    policy = CompactionPolicy(tail_tokens=300, default_input_window=2000, cooldown_calls=0)
    plugin = CompactionPlugin(policy, summarizer_model=_StubSummarizer())

    baseline, _, _ = await _run([])
    request, before, after = await _run([plugin])

    # The trigger fired through before_model_callback: the uncompacted request is over the
    # ratio, and the compacted one is smaller.
    assert policy.count_tokens(baseline.contents) > policy.trigger_ratio * 2000
    assert len(request.contents) < len(baseline.contents)

    # One reference-only message replaces the middle, followed by the tail.
    references = [
        content
        for content in request.contents
        for part in content.parts or []
        if part.text and part.text.startswith(REFERENCE_START)
    ]
    assert len(references) == 1
    assert request.contents[0] is not None and request.contents[0] == references[0]
    tail = request.contents[1:]
    assert tail, "the compacted request has no tail"
    assert [_shape(c) for c in tail] == [_shape(c) for c in baseline.contents[-len(tail) :]]
    assert tail[-1] == baseline.contents[-1]

    # Every anchor of the dropped events survives in the request.
    text = _request_text(request.contents)
    for i in range(URI_COUNT):
        assert _uri(i) in text, f"REQ-016-04: lost {_uri(i)}"
        assert f"artifact-{i}" in text, f"REQ-016-04: lost artifact-{i}"
    for i in range(CYCLES):
        assert f"call_{i}" in text, f"REQ-016-04: lost tool-call ID call_{i}"

    # The stored session events are unchanged.
    assert [event.model_dump() for event in after[: len(before)]] == before


async def test_compaction_absent_leaves_request_unrewritten() -> None:
    """Covers REQ-016-04: without the plugin the same oversized request goes out whole."""
    request, before, after = await _run([])

    assert len(request.contents) == 4 * CYCLES + 1
    assert REFERENCE_START not in _request_text(request.contents)
    assert [event.model_dump() for event in after[: len(before)]] == before


def test_compaction_policy_is_frozen() -> None:
    """Covers REQ-016-04: a policy cannot change after a plugin takes it."""
    policy = CompactionPolicy()

    with pytest.raises(FrozenInstanceError):
        policy.trigger_ratio = 0.9  # type: ignore[misc]


class _ClosingClient:
    """Fake ``AsyncLLMClient`` that counts ``aclose`` calls."""

    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


async def test_compaction_plugin_close_closes_owned_client() -> None:
    """Covers REQ-016-04: the plugin closes the summarizer client it owns."""
    client = _ClosingClient()
    plugin = CompactionPlugin(
        CompactionPolicy(),
        summarizer_model=_StubSummarizer(),
        client=client,  # type: ignore[arg-type]
    )

    await plugin.close()

    assert client.closed == 1
