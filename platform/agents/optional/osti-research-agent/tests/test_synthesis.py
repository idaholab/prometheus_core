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

"""Drive the graded cross-paper synthesis through the real RubricMiddleware
with fake chat models: the writer returns scripted drafts, the grader returns
scripted tool calls and GraderResponse verdicts."""

import asyncio
import inspect
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from research_agent.core import synthesis
from research_agent.core.config import AgentConfig

pytestmark = [
    pytest.mark.real_synthesis,
    pytest.mark.filterwarnings(
        "ignore::langchain_core._api.beta_decorator.LangChainBetaWarning"
    ),
]


class _FakeChat(BaseChatModel):
    responses: list
    seen: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


def _read_findings():
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "read_verified_findings", "args": {}, "id": "r", "type": "tool_call"}
        ],
    )


def _grade(result):
    passed = result == "satisfied"
    criterion = {"name": "claims are cited", "passed": passed}
    if not passed:
        criterion["gap"] = "the second sentence has no citation"
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "GraderResponse",
                "id": f"g-{result}",
                "type": "tool_call",
                "args": {"result": result, "explanation": "x", "criteria": [criterion]},
            }
        ],
    )


ANSWERS = [
    {"title": "Creep of Ti", "answer": "creeps above 800 C", "evidence": "Table 1"},
    {"title": "Ti at 900 C", "answer": "creep rate doubles", "evidence": "Fig. 2"},
]
GOOD = "Titanium creeps above 800 C (Paper 1), faster at 900 C (Paper 2)."


def _run(monkeypatch, writer, grader, *, answers=ANSWERS, seconds_left=900):
    models = {"orchestrator": writer, "verifier": grader}
    calls = []

    def chat_model(config, role, **kwargs):
        calls.append((role, kwargs))
        return models[role]

    monkeypatch.setattr(synthesis, "chat_model", chat_model)
    _run.calls = calls
    config = AgentConfig(litellm_base_url="http://unused")
    return asyncio.run(
        synthesis.synthesize("Does Ti creep?", answers, config, seconds_left=seconds_left)
    )


def test_satisfied_synthesis_is_used(monkeypatch):
    grader = _FakeChat(responses=[_read_findings(), _grade("satisfied")])
    writer = _FakeChat(responses=[AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) == GOOD


def test_grader_reads_the_full_findings_through_its_tool(monkeypatch):
    long_evidence = "x" * 5000 + " END-OF-EVIDENCE"
    answers = [{**ANSWERS[0], "evidence": long_evidence}]
    grader = _FakeChat(responses=[_read_findings(), _grade("satisfied")])
    writer = _FakeChat(responses=[AIMessage(content="Creeps (Paper 1).")])

    assert _run(monkeypatch, writer, grader, answers=answers) == "Creeps (Paper 1)."
    tool_results = [m.content for m in grader.seen[-1] if m.type == "tool"]
    assert any("END-OF-EVIDENCE" in content for content in tool_results)


def test_revision_is_used_once_the_grader_is_satisfied(monkeypatch):
    grader = _FakeChat(
        responses=[_read_findings(), _grade("needs_revision"), _grade("satisfied")]
    )
    writer = _FakeChat(responses=[AIMessage(content="Creeps. (Paper 1)"), AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) == GOOD


def test_unsatisfied_grader_falls_back(monkeypatch):
    grader = _FakeChat(
        responses=[_read_findings(), _grade("needs_revision"), _grade("needs_revision")]
    )
    writer = _FakeChat(responses=[AIMessage(content=GOOD), AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) is None  # max_iterations_reached


def test_grader_error_falls_back(monkeypatch):
    class _Broken(_FakeChat):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("provider down")

    writer = _FakeChat(responses=[AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, _Broken(responses=[])) is None


def test_out_of_range_citation_falls_back_even_when_satisfied(monkeypatch):
    grader = _FakeChat(responses=[_read_findings(), _grade("satisfied")])
    writer = _FakeChat(responses=[AIMessage(content="Creeps (Paper 7).")])

    assert _run(monkeypatch, writer, grader) is None


def test_answer_too_long_to_grade_falls_back_even_when_satisfied(monkeypatch):
    grader = _FakeChat(responses=[_read_findings(), _grade("satisfied")])
    long_answer = "Titanium creeps (Paper 1). " * 200
    writer = _FakeChat(responses=[AIMessage(content=long_answer)])

    assert _run(monkeypatch, writer, grader) is None


def test_no_time_left_skips_synthesis(monkeypatch):
    writer = _FakeChat(responses=[])
    grader = _FakeChat(responses=[])

    assert _run(monkeypatch, writer, grader, seconds_left=5) is None
    assert writer.seen == [] and grader.seen == []


def test_findings_are_numbered_like_the_citations():
    payload = synthesis.findings_payload(ANSWERS)

    assert [p["paper"] for p in payload] == [1, 2]
    assert json.loads(json.dumps(payload))[1]["title"] == "Ti at 900 C"


def test_rubric_middleware_contract_still_holds():
    """RubricMiddleware is @beta: fail here, not silently at runtime, if an
    upgrade changes what synthesis relies on."""
    from deepagents.middleware import rubric

    params = inspect.signature(rubric.RubricMiddleware.__init__).parameters
    assert {"model", "tools", "max_iterations", "on_evaluation"} <= set(params)
    # The answer limit assumes the grader sees at least this much per message.
    assert rubric._MAX_TRANSCRIPT_CHARS_PER_MESSAGE >= 4000
    assert synthesis.MAX_ANSWER_CHARS < rubric._MAX_TRANSCRIPT_CHARS_PER_MESSAGE
    assert callable(rubric._build_grader_transcript)


def test_grader_model_never_forces_a_tool_choice(monkeypatch):
    grader = _FakeChat(responses=[_read_findings(), _grade("satisfied")])
    writer = _FakeChat(responses=[AIMessage(content=GOOD)])
    _run(monkeypatch, writer, grader)

    assert ("verifier", {"forced_tool_choice": False}) in _run.calls
    assert ("orchestrator", {}) in _run.calls


def _grade_as_text(result, prose=""):
    passed = result == "satisfied"
    criterion = {"name": "claims are cited", "passed": passed}
    if not passed:
        criterion["gap"] = "the second sentence has no citation"
    verdict = {"result": result, "explanation": "x", "criteria": [criterion]}
    return AIMessage(content=prose + json.dumps(verdict))


def test_a_grader_verdict_in_text_is_used(monkeypatch):
    # Bedrock can't force the GraderResponse tool call, so the grader may
    # answer in text; that verdict must not be lost as grader_error.
    grader = _FakeChat(responses=[_read_findings(), _grade_as_text("satisfied")])
    writer = _FakeChat(responses=[AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) == GOOD


def test_a_text_verdict_can_ask_for_a_revision(monkeypatch):
    grader = _FakeChat(responses=[
        _read_findings(),
        _grade_as_text("needs_revision", prose="Here is my verdict: "),
        _grade_as_text("satisfied"),
    ])
    writer = _FakeChat(responses=[AIMessage(content="Creeps. (Paper 1)"), AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) == GOOD


def test_a_text_reply_without_a_verdict_still_falls_back(monkeypatch):
    grader = _FakeChat(responses=[_read_findings(), AIMessage(content="Looks good to me.")])
    writer = _FakeChat(responses=[AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) is None


def test_an_inconsistent_text_verdict_is_refused(monkeypatch):
    # "satisfied" with a failing criterion is invalid GraderResponse.
    bad = {"result": "satisfied", "explanation": "x",
           "criteria": [{"name": "c", "passed": False, "gap": "g"}]}
    grader = _FakeChat(responses=[_read_findings(), AIMessage(content=json.dumps(bad))])
    writer = _FakeChat(responses=[AIMessage(content=GOOD)])

    assert _run(monkeypatch, writer, grader) is None


def test_the_rubric_shows_the_text_verdict_format():
    rubric = (synthesis._PROMPTS_DIR / "synthesis_rubric.md").read_text()

    assert "reply with only its JSON object" in rubric
    assert '"result": "satisfied" | "needs_revision" | "failed"' in rubric
