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

"""ResearchRunner dispatches to the deep engine when
``config.engine == "deepagent"``, forwards its AgentEvents unchanged, and
salvages a timeout_partial from the captured Findings when the outer budget
fires - mirroring the pipeline engine's behavior. run_deep itself is stubbed
here; its internals are covered by test_deep_runner_stream.
"""

import asyncio

from research_agent.core import deep_runner as deep_runner_module
from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult, Finding, ProgressEvent
from research_agent.core.runner import ResearchRunner


async def _fake_complete(prompt, *, max_tokens, temperature=0):
    return "stub"


async def _drain(runner, question, run_id):
    events = []
    async for event in runner.run(question, run_id=run_id):
        events.append(event)
    return events


def test_deepagent_engine_forwards_events(monkeypatch):
    async def stub_run_deep(question, config, run_id, *, findings=None, **kwargs):
        yield ProgressEvent(message="working")
        yield FinalResult(status="completed", question=question, answer="done")

    monkeypatch.setattr(deep_runner_module, "run_deep", stub_run_deep)

    config = AgentConfig(
        litellm_base_url="http://unused", engine="deepagent", total_budget_s=900
    )
    runner = ResearchRunner(config, complete=_fake_complete)
    events = asyncio.run(_drain(runner, "q?", "d1"))

    assert isinstance(events[0], ProgressEvent)
    assert isinstance(events[-1], FinalResult)
    assert events[-1].status == "completed"
    assert sum(isinstance(e, FinalResult) for e in events) == 1


def test_deepagent_engine_salvages_timeout_partial(monkeypatch):
    async def hanging_run_deep(question, config, run_id, *, findings=None, **kwargs):
        if findings is not None:
            findings.append(
                Finding(source_id="123", answer="partial", evidence="Table 1")
            )
        await asyncio.sleep(3600)
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(deep_runner_module, "run_deep", hanging_run_deep)

    # total_budget_s - 30 == 1s: the stub runs its prefix (records the finding)
    # before the budget cancels it.
    config = AgentConfig(
        litellm_base_url="http://unused", engine="deepagent", total_budget_s=31
    )
    runner = ResearchRunner(config, complete=_fake_complete)
    events = asyncio.run(_drain(runner, "q?", "d2"))

    final = events[-1]
    assert isinstance(final, FinalResult)
    assert final.status == "timeout_partial"
    assert final.papers_analyzed == 1
    assert final.provenance and final.provenance[0]["source"] == "OSTI #123"
    assert "confidence" not in final.provenance[0]
    assert len(final.findings) == 1


def test_deep_timeout_partial_uses_recorded_titles_and_urls(monkeypatch):
    async def hanging_run_deep(
        question, config, run_id, *, findings=None, search_hits=None, **kwargs
    ):
        search_hits["10.1_ab"] = {
            "title": "Open-access creep study",
            "url": "https://doi.org/10.1/ab",
            "origin": "openalex",
        }
        findings.append(Finding(source_id="10.1_ab", answer="a", evidence="Fig. 2"))
        await asyncio.sleep(3600)
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(deep_runner_module, "run_deep", hanging_run_deep)
    config = AgentConfig(
        litellm_base_url="http://unused", engine="deepagent", total_budget_s=31
    )
    runner = ResearchRunner(config, complete=_fake_complete)
    final = asyncio.run(_drain(runner, "q?", "d3"))[-1]

    assert final.status == "timeout_partial"
    assert final.provenance[0]["title"] == "Open-access creep study"
    assert final.provenance[0]["url"] == "https://doi.org/10.1/ab"
