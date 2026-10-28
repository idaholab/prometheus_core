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

"""Coverage tests for deep_runner stream translation and its edge-case guards."""

import asyncio
import json

from langchain_core.messages import AIMessage, ToolMessage

from research_agent import llm_steps
from research_agent.core import deep_runner
from research_agent.core.events import Finding, ProgressEvent
from tests.test_deep_runner_stream import _config, _fake_complete, _FakeGraph, _finding_json


def _ctx():
    return deep_runner.RunContext(config=_config(), complete=_fake_complete, question="q")


def test_tool_call_status_names_the_query_per_search_tool():
    status = deep_runner._tool_call_status

    assert status("search_scholarly", {"query": "creep"}) == (
        "Searching open literature for: creep"
    )
    assert status("search_web", {"query": "creep"}) == "Searching the web for: creep"
    assert status("download_paper", {"query": "ignored"}) == "Downloading paper..."
    assert status("search_osti", "not-a-dict") == "Searching OSTI database..."
    assert status("mystery_tool", {}) == "Running mystery_tool..."


def test_capture_finding_ignores_unusable_payloads():
    ctx = _ctx()

    deep_runner._capture_finding("not json at all", ctx)
    deep_runner._capture_finding(json.dumps({"answered": False, "source_id": "1"}), ctx)
    deep_runner._capture_finding(json.dumps({"source_id": "1", "answer": ""}), ctx)
    deep_runner._capture_finding(json.dumps({"answer": "no id"}), ctx)

    assert ctx.findings == []


def test_capture_finding_skips_duplicates_and_uncoercible_values():
    ctx = _ctx()

    deep_runner._capture_finding(_finding_json("123"), ctx)
    deep_runner._capture_finding(_finding_json("123"), ctx)
    # artifacts=5 cannot become a list; excerpt as a dict fails validation.
    deep_runner._capture_finding(
        json.dumps({"source_id": "9", "answer": "a", "artifacts": 5}), ctx
    )
    deep_runner._capture_finding(
        json.dumps({"source_id": "8", "answer": "a", "excerpt": {"x": 1}}), ctx
    )

    assert [f.source_id for f in ctx.findings] == ["123"]


def test_translate_update_skips_non_dicts_and_emits_todo_updates():
    ctx = _ctx()
    todos = [{"content": "search", "status": "pending"}]

    assert list(deep_runner.translate_update(["not", "a", "dict"], ctx)) == []
    events = list(
        deep_runner.translate_update({"skip": "text", "planner": {"todos": todos}}, ctx)
    )

    assert len(events) == 1
    assert events[0].kind == "todo_update"
    assert events[0].detail == {"todos": todos}


def test_message_text_handles_part_lists_and_other_content():
    parts = AIMessage(
        content=["Ti ", {"type": "text", "text": "creeps"}, {"type": "image", "url": "x"}]
    )
    assert deep_runner._message_text(parts) == "Ti creeps"

    class _Odd:
        content = 42

    class _Empty:
        content = None

    assert deep_runner._message_text(_Odd()) == "42"
    assert deep_runner._message_text(_Empty()) == ""


def test_last_ai_text_ignores_non_dict_chunks_and_nodes():
    assert deep_runner._last_ai_text("not a dict") is None
    chunk = {
        "skip": None,
        "model": {"messages": [AIMessage(content="first"), AIMessage(content="  ")]},
    }
    assert deep_runner._last_ai_text(chunk) == "first"


def test_weaker_provenance_lists_each_abstract_once():
    ctx = _ctx()
    item = {"source_id": "55", "title": "T", "url": "https://u", "quote": "q" * 600}
    ctx.abstract_evidence.extend([item, dict(item, quote="other")])

    provenance = deep_runner._weaker_provenance(ctx)

    assert len(provenance) == 1
    assert provenance[0]["source"] == "abstract: 55"
    assert len(provenance[0]["excerpt"]) == 500


def test_unread_results_skip_parse_failures_and_analyzed_papers():
    ctx = _ctx()
    ctx.search_hits.update(
        {"1": {"title": "a"}, "2": {"title": "b"}, "3": {"title": "c"}}
    )
    ctx.parse_failures["1"] = "bad pdf"
    ctx.paper_analysis_results["2"] = {"answered": False}

    assert [sid for sid, _ in deep_runner._unread_results(ctx)] == ["3"]


def test_run_deep_shares_caller_findings_and_search_hits(monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    seen = {}

    def build(config, ctx):
        seen["ctx"] = ctx
        tool = ToolMessage(content=_finding_json("77"), name="analyze_paper", tool_call_id="c")
        final = AIMessage(content=json.dumps({"findings": []}))
        return _FakeGraph(
            [
                ("custom", {"no_message": True}),
                ("updates", {"tools": {"messages": [tool]}}),
                ("updates", {"model": {"messages": [final]}}),
            ]
        )

    monkeypatch.setattr(deep_runner, "build_research_agent", build)
    findings: list = []
    hits = {"77": {"title": "Shared hit", "url": "https://example/77"}}

    async def go():
        return [
            e
            async for e in deep_runner.run_deep(
                "q", _config(), "r", complete=_fake_complete, findings=findings,
                search_hits=hits,
            )
        ]

    events = asyncio.run(go())

    assert seen["ctx"].findings is findings
    assert seen["ctx"].search_hits is hits
    assert [f.source_id for f in findings] == ["77"]
    assert isinstance(findings[0], Finding)
    final = events[-1]
    assert final.status == "completed"
    assert final.provenance[0]["title"] == "Shared hit"
    # the custom chunk without a message produced no progress event
    assert not any(
        isinstance(e, ProgressEvent) and e.detail == {"no_message": True} for e in events
    )
