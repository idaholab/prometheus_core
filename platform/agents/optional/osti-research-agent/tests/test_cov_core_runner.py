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

"""Coverage tests for ResearchRunner error, zero-budget and empty-timeout paths."""

import asyncio

from research_agent.core import deep_runner as deep_runner_module
from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult, ProgressEvent
from research_agent.core.runner import ResearchRunner, _deep_timeout_result
from tests.test_runner_deep import _drain, _fake_complete


def test_deep_engine_exception_becomes_error_final_result(monkeypatch):
    async def failing_run_deep(question, config, run_id, **kwargs):
        yield ProgressEvent(message="starting")
        raise RuntimeError("orchestrator exploded")

    monkeypatch.setattr(deep_runner_module, "run_deep", failing_run_deep)
    config = AgentConfig(litellm_base_url="http://unused", total_budget_s=900)
    runner = ResearchRunner(config, complete=_fake_complete)

    events = asyncio.run(_drain(runner, "q?", "e1"))

    assert isinstance(events[0], ProgressEvent)
    final = events[-1]
    assert isinstance(final, FinalResult)
    assert final.status == "error"
    assert final.question == "q?"
    assert final.answer == "orchestrator exploded"


def test_zero_budget_times_out_immediately_without_findings(monkeypatch):
    started = []

    async def hanging_run_deep(question, config, run_id, **kwargs):
        started.append(run_id)
        await asyncio.sleep(3600)
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(deep_runner_module, "run_deep", hanging_run_deep)
    # total_budget_s - 30 == 0: the budget is already exhausted on entry.
    config = AgentConfig(litellm_base_url="http://unused", total_budget_s=30)
    runner = ResearchRunner(config, complete=_fake_complete)

    events = asyncio.run(_drain(runner, "q?", "e2"))

    assert len(events) == 1
    final = events[0]
    assert final.status == "timeout_partial"
    assert final.papers_analyzed == 0
    assert final.provenance == []
    assert "before finding any results" in final.answer


def test_timeout_result_without_findings_has_empty_provenance():
    result = _deep_timeout_result("q?", [], {"x": {"title": "unused"}})

    assert result.status == "timeout_partial"
    assert result.answer == (
        "Research timed out after reaching the time budget before finding any results."
    )
    assert result.findings == []
    assert result.searched_papers == {"x": {"title": "unused"}}
