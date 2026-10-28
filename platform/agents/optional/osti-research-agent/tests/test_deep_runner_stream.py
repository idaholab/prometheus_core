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

"""Verify that run_deep translates LangGraph streams into AgentEvents and
parses the orchestrator's final JSON into a FinalResult, with a clean fallback
for unparseable final messages. Tests use a scripted fake graph without an LLM
or deepagents.
"""

import asyncio
import json

from langchain_core.messages import AIMessage, ToolMessage

from research_agent import llm_steps
from research_agent.core import deep_runner
from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult, ProgressEvent


class _FakeGraph:
    """Yields a scripted list of (stream_mode, chunk) tuples from astream."""

    def __init__(self, script):
        self._script = script

    async def astream(self, _input, *, stream_mode=None, config=None):
        for item in self._script:
            yield item


def _finding_json(source_id="123"):
    return json.dumps(
        {
            "source_id": source_id,
            "answer": "Titanium creeps above 800C",
            "evidence": "Table 1 reports creep rates",
            "excerpt": "creep onset near 810C",
            "artifacts": ["/papers/123/tables/table_01.md"],
        }
    )


async def _fake_complete(prompt, *, max_tokens, temperature=0):
    return "stub"


def _config():
    return AgentConfig(
        litellm_base_url="http://unused", engine="deepagent", total_budget_s=900
    )


def _run(script, monkeypatch, final_text):
    # suggest_followup_from_findings would otherwise make a real LLM call.
    async def no_followups(**kwargs):
        return [{"suggested_query": "next?"}]

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)

    ai_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_osti",
                "args": {"query": "titanium"},
                "id": "c1",
                "type": "tool_call",
            }
        ],
    )
    task_result = ToolMessage(
        content=_finding_json(),
        name="analyze_paper",
        tool_call_id="c1",
    )
    final_ai = AIMessage(content=final_text)

    full_script = [
        ("custom", {"message": "Searching OSTI for: titanium", "detail": {"n": 1}}),
        ("updates", {"model": {"messages": [ai_call]}}),
        ("updates", {"tools": {"messages": [task_result]}}),
        ("updates", {"model": {"messages": [final_ai]}}),
    ] + script

    monkeypatch.setattr(
        deep_runner, "build_research_agent", lambda config, ctx: _FakeGraph(full_script)
    )

    async def go():
        events = []
        async for event in deep_runner.run_deep(
            "does titanium creep?",
            _config(),
            "run-1",
            complete=_fake_complete,
        ):
            events.append(event)
        return events

    return asyncio.run(go())


def test_stream_translates_events_and_parses_final(monkeypatch):
    final_text = json.dumps(
        {
            "answer": "Titanium creeps above 800C (Paper 1).",
            "findings": [json.loads(_finding_json())],
        }
    )
    events = _run([], monkeypatch, final_text)

    progress = [e for e in events if isinstance(e, ProgressEvent)]
    finals = [e for e in events if isinstance(e, FinalResult)]

    # custom chunk -> a status ProgressEvent
    assert any(e.message == "Searching OSTI for: titanium" for e in progress)
    # AIMessage tool call -> a tool_call ProgressEvent tagged with the tool name
    assert any(
        e.kind == "tool_call" and (e.detail or {}).get("tool") == "search_osti"
        for e in progress
    )

    assert len(finals) == 1
    final = finals[0]
    assert final.status == "completed"
    assert len(final.findings) == 1
    assert final.findings[0].source_id == "123"
    assert final.provenance[0]["url"] == "https://www.osti.gov/biblio/123"
    assert "confidence" not in final.provenance[0]
    assert "[Paper 1](https://www.osti.gov/biblio/123)" in final.answer
    assert final.suggested_queries == [{"suggested_query": "next?"}]


def test_finding_captured_from_analyze_paper_toolmessage(monkeypatch):
    # Final message carries no findings array; run_deep must fall back to the
    # finding it captured off the analyze_paper ToolMessage during the stream.
    final_text = json.dumps({"answer": "Titanium creeps (Paper 1)."})
    events = _run([], monkeypatch, final_text)

    final = [e for e in events if isinstance(e, FinalResult)][0]
    assert final.status == "completed"
    assert len(final.findings) == 1
    assert final.findings[0].source_id == "123"


def test_malformed_final_falls_back_to_error(monkeypatch):
    events = _run([], monkeypatch, "Sorry, I was unable to produce a JSON answer.")

    final = [e for e in events if isinstance(e, FinalResult)][0]
    assert final.status == "error"
    assert "unable to produce" in final.answer
    # findings captured off the stream are still preserved for the caller
    assert len(final.findings) == 1


def test_final_answer_uses_captured_findings_only(monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)

    context = deep_runner.RunContext(
        config=_config(),
        complete=_fake_complete,
        question="does titanium creep?",
    )
    context.findings.append(
        deep_runner.Finding(
            source_id="123",
            answer="Unsupported analyzer explanation",
            evidence="Table 1 reports the measured value",
        )
    )
    final_text = json.dumps(
        {
            "answer": "Unsupported estimate from search snippets.",
            "findings": [json.loads(_finding_json())],
        }
    )

    final = asyncio.run(
        deep_runner.build_final_result("does titanium creep?", final_text, context)
    )

    assert "Unsupported estimate" not in final.answer
    assert "Titanium creeps above 800C" not in final.answer
    assert "Unsupported analyzer explanation" not in final.answer
    assert "Table 1 reports the measured value" in final.answer
    assert "[Paper 1](https://www.osti.gov/biblio/123)" in final.answer


def test_orchestrator_findings_cannot_bypass_verification(monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    context = deep_runner.RunContext(
        config=_config(),
        complete=_fake_complete,
        question="does titanium creep?",
    )
    final_text = json.dumps(
        {
            "answer": "Unsupported cached answer.",
            "findings": [json.loads(_finding_json())],
        }
    )

    final = asyncio.run(
        deep_runner.build_final_result("does titanium creep?", final_text, context)
    )

    assert final.status == "no_results"
    assert final.findings == []
    assert "Unsupported cached answer" not in final.answer
    assert "No source-verified findings" in final.answer


def test_total_verifier_failure_returns_error(monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    context = deep_runner.RunContext(
        config=_config(),
        complete=_fake_complete,
        question="does titanium creep?",
    )
    context.verification_errors.append("123: RuntimeError")

    final = asyncio.run(
        deep_runner.build_final_result(
            "does titanium creep?",
            json.dumps({"answer": "Unsupported candidate.", "findings": []}),
            context,
        )
    )

    assert final.status == "error"
    assert final.findings == []
    assert "source verification failed" in final.answer


def test_verified_findings_survive_other_verifier_failures(monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    context = deep_runner.RunContext(
        config=_config(),
        complete=_fake_complete,
        question="does titanium creep?",
    )
    context.findings.append(
        deep_runner.Finding(
            source_id="123",
            answer="Verified result",
            evidence="Table 1 reports the measured value",
        )
    )
    context.verification_errors.append("999: RuntimeError")

    final = asyncio.run(
        deep_runner.build_final_result(
            "does titanium creep?",
            json.dumps({"answer": "orchestrator output", "findings": []}),
            context,
        )
    )

    assert final.status == "completed"
    assert len(final.findings) == 1
    assert "Table 1 reports the measured value" in final.answer


def _run_recording_workdir(monkeypatch, tmp_path, *, fail=False):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    seen = []

    class _Graph:
        def __init__(self, ctx):
            self._ctx = ctx

        async def astream(self, _input, *, stream_mode=None, config=None):
            paper = self._ctx.run_workdir / "papers" / "1" / "paper.md"
            paper.parent.mkdir(parents=True)
            paper.write_text("text")
            seen.append(self._ctx.run_workdir)
            if fail:
                raise RuntimeError("boom")
            yield ("updates", {"model": {"messages": [AIMessage(content="{}")]}})

    monkeypatch.setattr(
        deep_runner, "build_research_agent", lambda config, ctx: _Graph(ctx)
    )
    config = _config().model_copy(update={"workdir": tmp_path})

    async def go():
        async for _ in deep_runner.run_deep(
            "q", config, "conv-1", complete=_fake_complete
        ):
            pass

    return go, seen


def test_run_workdir_is_unique_per_turn_and_removed(monkeypatch, tmp_path):
    go, seen = _run_recording_workdir(monkeypatch, tmp_path)
    asyncio.run(go())
    asyncio.run(go())

    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(p.parent == tmp_path and p.name.startswith("conv-1-") for p in seen)
    assert not any(p.exists() for p in seen)


def test_run_workdir_removed_when_run_fails(monkeypatch, tmp_path):
    go, seen = _run_recording_workdir(monkeypatch, tmp_path, fail=True)
    try:
        asyncio.run(go())
    except RuntimeError:
        pass

    assert seen and not seen[0].exists()


def test_papers_analyzed_counts_every_analysis_not_just_findings(monkeypatch):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    context = deep_runner.RunContext(
        config=_config(), complete=_fake_complete, question="q"
    )
    context.papers_attempted = 3  # one of the three never parsed
    context.findings.append(
        deep_runner.Finding(source_id="1", answer="a", evidence="Table 1")
    )
    context.paper_analysis_results = {
        "1": {"source_id": "1", "answer": "a"},
        "2": {"answered": False, "reason": "not supported"},
    }
    final_text = json.dumps({"findings": [], "answer": ""})

    final = asyncio.run(deep_runner.build_final_result("q", final_text, context))

    assert final.papers_analyzed == 2


class _RecordingKnowledge:
    def __init__(self):
        self.cached = []

    async def cache_answer(self, question, answer, sources):
        self.cached.append((question, answer, sources))


def _final_with_knowledge(monkeypatch, *, with_finding):
    async def no_followups(**kwargs):
        return []

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    context = deep_runner.RunContext(
        config=_config(), complete=_fake_complete, question="q"
    )
    context.knowledge = _RecordingKnowledge()
    if with_finding:
        context.findings.append(
            deep_runner.Finding(source_id="123", answer="a", evidence="Table 1")
        )
    final_text = json.dumps({"findings": [], "answer": ""})
    final = asyncio.run(deep_runner.build_final_result("q", final_text, context))
    return final, context.knowledge.cached


def test_completed_answer_is_cached(monkeypatch):
    final, cached = _final_with_knowledge(monkeypatch, with_finding=True)

    assert final.status == "completed"
    assert cached == [("q", final.answer, final.provenance)]


def test_no_results_answer_is_not_cached(monkeypatch):
    final, cached = _final_with_knowledge(monkeypatch, with_finding=False)

    assert final.status == "no_results"
    assert cached == []


def _final_for_synthesis(monkeypatch, synthesized):
    from research_agent.core import synthesis

    async def no_followups(**kwargs):
        return []

    async def fake_synthesize(question, answers, config, *, seconds_left):
        assert [a["osti_id"] for a in answers] == ["123"]
        return synthesized

    monkeypatch.setattr(llm_steps, "suggest_followup_from_findings", no_followups)
    monkeypatch.setattr(synthesis, "synthesize", fake_synthesize)
    context = deep_runner.RunContext(
        config=_config(), complete=_fake_complete, question="q"
    )
    context.findings.append(
        deep_runner.Finding(source_id="123", answer="a", evidence="Table 1 value")
    )
    final_text = json.dumps({"findings": [json.loads(_finding_json())]})
    return asyncio.run(deep_runner.build_final_result("q", final_text, context))


def test_graded_synthesis_becomes_the_linkified_answer(monkeypatch):
    final = _final_for_synthesis(monkeypatch, "Ti creeps (Paper 1).")

    assert final.status == "completed"
    assert final.answer == "Ti creeps ([Paper 1](https://www.osti.gov/biblio/123))."


def test_findings_only_final_message_falls_back_to_per_paper_answer(monkeypatch):
    final = _final_for_synthesis(monkeypatch, None)

    assert final.status == "completed"
    assert "Table 1 value" in final.answer
