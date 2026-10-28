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

"""Coverage tests for synthesis text extraction and its failure fallback."""

import asyncio
from types import SimpleNamespace

import pytest

from research_agent.core import synthesis
from research_agent.core.config import AgentConfig


def _msg(kind, content):
    return SimpleNamespace(type=kind, content=content)


def test_last_ai_text_skips_non_ai_and_joins_text_parts():
    state = {
        "messages": [
            _msg("ai", "older answer"),
            _msg(
                "ai",
                [
                    {"type": "text", "text": " Ti creeps "},
                    {"type": "tool_use", "text": "ignored"},
                    "not-a-dict",
                    {"type": "text", "text": "(Paper 1). "},
                ],
            ),
            _msg("tool", "tool output is not an answer"),
        ]
    }

    assert synthesis._last_ai_text(state) == "Ti creeps (Paper 1)."


def test_last_ai_text_returns_empty_when_no_ai_text():
    state = {"messages": [_msg("human", "hi"), _msg("ai", "   "), _msg("ai", [])]}

    assert synthesis._last_ai_text(state) == ""
    assert synthesis._last_ai_text({"messages": None}) == ""
    assert synthesis._last_ai_text({}) == ""


@pytest.mark.real_synthesis
def test_synthesize_falls_back_to_none_when_build_fails(monkeypatch):
    built = []

    def broken_build(config, payload, on_evaluation):
        built.append(payload)
        raise RuntimeError("cannot build agent")

    monkeypatch.setattr(synthesis, "_build_synthesizer", broken_build)
    config = AgentConfig(litellm_base_url="http://unused")
    answers = [{"title": "Ti", "answer": "creeps", "evidence": "Table 1"}]

    result = asyncio.run(
        synthesis.synthesize("Does Ti creep?", answers, config, seconds_left=900)
    )

    assert result is None
    assert built and built[0][0]["paper"] == 1

