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

"""Follow-up suggestions in the deep engine come from verified findings only."""

import asyncio
import json

from research_agent import llm_steps
from research_agent.core import deep_runner
from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding


class _RecordingComplete:
    def __init__(self, reply='[{"suggested_query": "creep of Ti at 900 C"}]'):
        self.reply = reply
        self.prompts = []

    async def __call__(self, prompt, *, max_tokens):
        self.prompts.append(prompt)
        return self.reply


FINDINGS = [
    {
        "title": "Creep of Ti",
        "answer": "creeps above 800 C",
        "evidence": "Table 1 reports 810 C onset",
        "url": "https://www.osti.gov/biblio/123",
    }
]


def test_prompt_carries_findings_and_no_answer_or_search_titles():
    complete = _RecordingComplete()

    out = asyncio.run(
        llm_steps.suggest_followup_from_findings("Does Ti creep?", FINDINGS, complete)
    )

    assert out == [{"suggested_query": "creep of Ti at 900 C"}]
    (prompt,) = complete.prompts
    assert "Table 1 reports 810 C onset" in prompt and "creeps above 800 C" in prompt
    assert "CURRENT ANSWER SUMMARY" not in prompt
    assert "https://www.osti.gov/biblio/123" not in prompt


def test_no_findings_means_no_suggestions_and_no_model_call():
    complete = _RecordingComplete()

    assert asyncio.run(llm_steps.suggest_followup_from_findings("q", [], complete)) == []
    assert complete.prompts == []


def test_long_evidence_is_cut_in_the_prompt():
    complete = _RecordingComplete()
    findings = [{**FINDINGS[0], "evidence": "e" * 5000}]

    asyncio.run(llm_steps.suggest_followup_from_findings("q", findings, complete))

    assert "e" * 801 not in complete.prompts[0] and "e" * 800 in complete.prompts[0]


def test_bad_model_reply_gives_no_suggestions():
    complete = _RecordingComplete(reply="not json")

    assert asyncio.run(llm_steps.suggest_followup_from_findings("q", FINDINGS, complete)) == []


def _context(complete, findings):
    ctx = deep_runner.RunContext(
        config=AgentConfig(litellm_base_url="http://unused"),
        complete=complete,
        question="Does Ti creep?",
    )
    ctx.findings.extend(findings)
    ctx.search_hits["123"] = {"title": "Creep of Ti", "url": "https://www.osti.gov/biblio/123"}
    return ctx


def test_final_result_suggestions_come_from_verified_findings():
    complete = _RecordingComplete()
    ctx = _context(
        complete,
        [Finding(source_id="123", answer="creeps above 800 C", evidence="Table 1 onset")],
    )
    final_text = json.dumps({"findings": []})

    final = asyncio.run(deep_runner.build_final_result("Does Ti creep?", final_text, ctx))

    assert final.suggested_queries == [{"suggested_query": "creep of Ti at 900 C"}]
    assert "Table 1 onset" in complete.prompts[-1]
    assert "Evidence-grounded findings" not in complete.prompts[-1]


def test_no_results_run_gets_no_suggestions():
    complete = _RecordingComplete()
    final = asyncio.run(
        deep_runner.build_final_result(
            "Does Ti creep?", json.dumps({"findings": []}), _context(complete, [])
        )
    )

    assert final.status == "no_results"
    assert final.suggested_queries == [] and complete.prompts == []
