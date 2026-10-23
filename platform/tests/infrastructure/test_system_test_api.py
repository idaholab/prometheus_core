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

"""Unit coverage for the concise full-system test helpers."""

from __future__ import annotations

import asyncio

import pytest

from prometheus_api.contract import ConversationResponse
from system import prometheus
from system.a2a_client import ChatFinalEvent, ChatProgressEvent


class _FakeSession:
    conversation_id = "conv-test"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def stream(self, text, **kwargs):
        self.calls.append((text, kwargs))
        yield ChatProgressEvent(message="Working...")
        yield ChatFinalEvent(response=self.responses.pop(0))


def test_prompt_and_submit_parameters_return_assertion_friendly_results() -> None:
    needs_info = ConversationResponse(
        conversation_id="conv-test",
        status="needs_info",
        message="Dimensions required.",
        followup_questions=[
            {
                "field": "input_data.rod_diameter",
                "question": "Rod diameter (m)",
                "type": "number",
            }
        ],
    )
    completed = ConversationResponse(
        conversation_id="conv-test",
        status="completed",
        report="Created the requested valve.",
        artifacts=[
            {
                "artifact_id": "step-1",
                "name": "valve.step",
                "mime_type": "application/step",
            },
            {
                "artifact_id": "stl-1",
                "name": "valve.stl",
                "mime_type": "application/stl",
            },
        ],
    )
    session = _FakeSession([needs_info, completed])
    chat = prometheus.Chat(session)

    first = asyncio.run(prometheus.prompt(chat, "Create a butterfly valve."))
    prometheus.expect_parameter_request(first, ["rod_diameter"])
    assert first.progress == ("Working...",)
    assert first.parameters[0].path == "input_data.rod_diameter"

    second = asyncio.run(prometheus.submit_parameters(chat, {"rod_diameter": 0.08}))
    assert second.text == "Created the requested valve."
    assert [artifact.type for artifact in second.artifacts] == [
        "application/step",
        "application/stl",
    ]
    assert second.new_artifacts == second.artifacts
    assert session.calls[1] == (
        "Create a butterfly valve.",
        {"followup_answers": {"rod_diameter": 0.08}},
    )


def test_expect_parameter_request_reports_name_differences() -> None:
    result = prometheus.Result(
        chat_id="conv-test",
        status="needs_info",
        text="Need input.",
        parameters=(
            prometheus.ParameterRequest(
                name="rod_diameter",
                path="input_data.rod_diameter",
                prompt="Rod diameter",
                type="number",
                options=None,
                raw={},
            ),
        ),
        artifacts=(),
        new_artifacts=(),
        progress=(),
        raw=ConversationResponse(conversation_id="conv-test", status="needs_info"),
    )

    with pytest.raises(AssertionError, match="expected.*hole_diameter.*rod_diameter"):
        prometheus.expect_parameter_request(result, ["rod_diameter", "hole_diameter"])


def test_is_similar_uses_llm_gateway_and_parses_json(monkeypatch) -> None:
    captured = {}

    class _Client:
        def __init__(self, *, config, app_name):
            captured.update({"config": config, "app_name": app_name})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def chat(self, messages, **kwargs):
            captured.update({"messages": messages, "kwargs": kwargs})
            return type(
                "Response",
                (),
                {"text": '{"similar": true, "reason": "Same outcome"}'},
            )()

    config = object()
    monkeypatch.setattr(
        prometheus.LLMConfig,
        "from_env",
        classmethod(lambda cls: config),
    )
    monkeypatch.setattr(prometheus, "AsyncLLMClient", _Client)

    result = asyncio.run(
        prometheus.is_similar(
            "Valve geometry created successfully.",
            "Created a butterfly valve.",
        )
    )

    assert result is True
    assert captured["config"] is config
    assert captured["app_name"] == "Prometheus System Test Judge"
    assert captured["kwargs"]["model"] == "medium"
