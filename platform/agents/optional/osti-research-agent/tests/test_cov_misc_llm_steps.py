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
"""Lenient JSON extraction and follow-up suggestion filtering in llm_steps."""

import asyncio
import json

from research_agent import llm_steps

FINDINGS = [{"title": "Creep of Ti", "answer": "n = 5", "evidence": "Table 2"}]


def test_bad_json_in_a_code_block_and_in_raw_text_yields_none():
    assert llm_steps.extract_json_from_text("```json\n{not: valid}\n```") is None


def test_a_fenced_block_wins_over_other_json_in_the_reply():
    text = 'Here: ```json\n[{"query": "a"}]\n``` (not {"b": 2})'
    assert llm_steps.extract_json_from_text(text) == [{"query": "a"}]


def _suggest(reply, limit=3):
    async def complete(prompt, *, max_tokens):
        assert "Creep of Ti" in prompt
        if isinstance(reply, Exception):
            raise reply
        return reply

    return asyncio.run(
        llm_steps.suggest_followup_from_findings("q?", FINDINGS, complete, limit=limit)
    )


def test_suggestions_accept_strings_and_skip_blanks_and_duplicates():
    reply = json.dumps(
        ["creep of Ti-6Al-4V", "", None, {"query": "CREEP OF TI-6AL-4V"},
         {"suggested_query": "oxidation of Ti"}]
    )

    out = _suggest(reply)

    assert out == [
        {"suggested_query": "creep of Ti-6Al-4V"},
        {"suggested_query": "oxidation of Ti"},
    ]


def test_suggestions_stop_at_the_limit():
    out = _suggest(json.dumps(["a", "b", "c", "d"]), limit=2)

    assert out == [{"suggested_query": "a"}, {"suggested_query": "b"}]


def test_a_model_failure_yields_no_suggestions(caplog):
    out = _suggest(RuntimeError("model down"))

    assert out == []
    assert "model down" in caplog.text
