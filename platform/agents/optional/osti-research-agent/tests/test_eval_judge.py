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

"""The evaluation's LLM judge, with a fake completion function, and the
progress bar. No model, network, or terminal is needed."""

import asyncio
import json

import pytest

from evals import judge
from evals import report as render
from evals import run as eval_run
from evals import scoring
from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult

UQ_SPEC = {
    "id": "uq-one",
    "question": "What input ranges did FUMAC use for IFA-650.10?",
    "notes": "Ref: fuel conductivity sd 5%, bounds 0.90-1.10. Answer lives in a table. "
    "Access: OPEN (euronuclear.org).",
}
RESULT = {
    "status": "completed",
    "answer": "Fuel conductivity had sd 5% (Paper 1).",
    "findings": [{"source_id": "1", "answer": "sd 5%", "evidence": "Table 2: sd 5%"}],
}


class _Complete:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    async def __call__(self, prompt, *, max_tokens):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _verdict(**overrides):
    values = {"groundedness": 5, "completeness": 4, "reference_agreement": 3,
              "rationale": "Misses the gap conductivity range."}
    values.update(overrides)
    return json.dumps(values)


def test_reference_notes_drop_the_access_tag():
    assert judge.reference_notes(UQ_SPEC) == (
        "Ref: fuel conductivity sd 5%, bounds 0.90-1.10. Answer lives in a table."
    )
    assert judge.reference_notes({"notes": ""}) == ""


@pytest.mark.parametrize(
    "notes, graded",
    [
        ("Replaces an older question. Ref: Faure et al. (2023). Three inputs.", True),
        ("Ref (AGR-2 part): INL/EXT-21-64589 on TRISO failure.", True),
        ("Pinned anchor: 59 runs.", True),
        ("No literature answer exists; expect honest no_results.", True),
        ("Pass only if it says the parameter is not listed.", True),
        ("No single correct value. A good answer explains purpose.", True),
        ("Preprint-heavy topic; exercises the arXiv path.", False),
        ("Very broad; tests budget discipline.", False),
    ],
)
def test_only_notes_that_say_what_is_right_are_graded(notes, graded):
    assert bool(judge.reference_notes({"notes": notes})) is graded


def test_prompt_carries_answer_findings_and_reference_but_not_access():
    prompt = judge.build_prompt(RESULT, UQ_SPEC)

    assert "Fuel conductivity had sd 5% (Paper 1)." in prompt
    assert "Table 2: sd 5%" in prompt
    assert "bounds 0.90-1.10" in prompt
    assert "euronuclear.org" not in prompt and "$" not in prompt


def test_judge_scores_merge_into_the_record():
    complete = _Complete("Here you go: " + _verdict())

    fields = asyncio.run(judge.judge_result(RESULT, UQ_SPEC, complete))

    assert fields == {
        "judge_groundedness": 5,
        "judge_completeness": 4,
        "judge_reference_agreement": 3,
        "judge_rationale": "Misses the gap conductivity range.",
    }


def test_reference_agreement_is_dropped_without_notes():
    fields = asyncio.run(
        judge.judge_result(RESULT, {"id": "core", "question": "q"}, _Complete(_verdict()))
    )

    assert fields["judge_reference_agreement"] is None
    assert "reviewer_notes>\nnone\n" in judge.build_prompt(RESULT, {"question": "q"})


@pytest.mark.parametrize(
    "reply",
    [
        "no json here",
        _verdict(groundedness=9),
        _verdict(completeness="good"),
        _verdict(reference_agreement=None),  # notes exist, so it must be scored
        RuntimeError("judge model down"),
    ],
)
def test_judge_failures_become_judge_error(reply):
    fields = asyncio.run(judge.judge_result(RESULT, UQ_SPEC, _Complete(reply)))

    assert list(fields) == ["judge_error"]


def test_low_judge_score_fails_the_question_with_a_reason():
    record = {"status_match": True, "provenance_ok": True, "citation_link_rate": 1.0,
              "source_hit_rate": 1.0, "fact_match": 1.0,
              "judge_groundedness": 5, "judge_completeness": 4,
              "judge_reference_agreement": 3}

    assert render.failures(record) == ["judge reference agreement 3/5"]
    assert judge.judge_passed(record) is False
    assert judge.judge_passed({**record, "judge_reference_agreement": 4}) is True
    assert judge.judge_passed({}) is None


def test_report_and_judge_agree_on_the_pass_score():
    assert render.JUDGE_PASS_SCORE == judge.PASS_SCORE


def test_run_judges_each_question_and_reports_scores(tmp_path, monkeypatch, capsys):
    questions = tmp_path / "questions.yaml"
    questions.write_text(
        "questions:\n"
        "  - id: uq-one\n"
        "    question: What input ranges did FUMAC use?\n"
        "    notes: 'Ref: sd 5%. Access: OPEN.'\n"
    )
    monkeypatch.setattr(
        eval_run, "_load_agent_config", lambda: AgentConfig(litellm_base_url="http://u")
    )

    class _Runner:
        def __init__(self, config):
            pass

        async def run(self, question, *, run_id):
            yield FinalResult(**RESULT, question=question,
                              provenance=[{"source": "OSTI #1", "url": "u"}])

    complete = _Complete(_verdict())
    monkeypatch.setattr(eval_run, "ResearchRunner", _Runner)
    monkeypatch.setattr(eval_run.judge, "make_complete", lambda config: complete)

    report_path = tmp_path / "r" / "report.json"
    asyncio.run(eval_run._main([
        "--questions", str(questions), "--engines", "deepagent", "--no-redis",
        "--report", str(report_path), "--workdir", str(tmp_path / "r" / "out"),
    ]))

    (record,) = json.loads(report_path.read_text())["records"]
    assert record["judge_reference_agreement"] == 3
    assert "Ref: sd 5%." in complete.prompts[0] and "OPEN" not in complete.prompts[0]
    markdown = report_path.with_suffix(".md").read_text()
    assert "## Judge notes" in markdown and "Misses the gap conductivity range." in markdown
    err = capsys.readouterr().err
    assert "FAIL  uq-one" in err and "judge ground=5 complete=4 ref=3" in err


def test_score_result_is_unchanged_by_the_judge_fields():
    # The judge adds judge_* keys; the automatic checks are computed as before.
    record = scoring.score_result({**RESULT, "_engine": "deepagent"}, UQ_SPEC)

    assert not any(k.startswith("judge_") for k in record)


def test_judge_sees_each_findings_match_label():
    result = {**RESULT, "findings": [
        {"source_id": "1", "match": "nearest", "answer": "a", "evidence": "e"},
        {"source_id": "2", "answer": "b", "evidence": "f"},  # older results: exact
    ]}

    prompt = judge.build_prompt(result, UQ_SPEC)

    assert '"match": "nearest"' in prompt and '"match": "exact"' in prompt


def test_completeness_has_an_explicit_scale_for_nearest_data():
    text = " ".join(judge._PROMPT.template.split())

    assert "5 = the asked value at the asked conditions, from an \"exact\" finding" in text
    assert "3 = no exact finding or sound estimate, but correctly labelled \"nearest\"" in text
    assert "2 = only nearest data that is loosely related" in text
    # Stating the gap is required, not rewarded on its own.
    assert "not a reason for a higher score" in text


class _Sequence:
    """Returns each reply in turn, one per call."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), 0

    async def __call__(self, prompt, *, max_tokens):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


# A rationale with an unescaped quote: the "Expecting ',' delimiter" case.
BROKEN = (
    '{"groundedness": 5, "completeness": 3, "reference_agreement": 2, '
    '"rationale": "It labels the 550 C data as "nearest" and states the gap."}'
)


def test_a_rationale_with_an_unescaped_quote_is_still_scored():
    import json as _json

    with pytest.raises(_json.JSONDecodeError):
        _json.loads(BROKEN)

    verdict = judge.parse_verdict(BROKEN, has_notes=True)

    assert (verdict["groundedness"], verdict["completeness"], verdict["reference_agreement"]) == (
        5, 3, 2
    )
    assert verdict["rationale"] == 'It labels the 550 C data as "nearest" and states the gap.'


def test_an_unusable_reply_is_retried_once():
    complete = _Sequence("not json at all", _verdict())

    fields = asyncio.run(judge.judge_result(RESULT, UQ_SPEC, complete))

    assert complete.calls == 2 and fields["judge_completeness"] == 4


def test_two_unusable_replies_leave_the_question_unjudged():
    complete = _Sequence("nope", RuntimeError("down"))

    fields = asyncio.run(judge.judge_result(RESULT, UQ_SPEC, complete))

    assert complete.calls == judge.JUDGE_ATTEMPTS and list(fields) == ["judge_error"]


def test_an_unjudged_question_does_not_pass():
    record = {"status_match": True, "provenance_ok": True, "citation_link_rate": 1.0,
              "source_hit_rate": 1.0, "fact_match": 1.0,
              "judge_error": "judge reply is not valid JSON"}

    assert render.failures(record) == ["not judged"]
    explained = dict(render.explained_failures(record))
    assert "could not be scored" in explained["not judged"]
    assert "rerun this question with --id" in explained["not judged"]


def test_the_judge_is_told_to_escape_quotes():
    text = " ".join(judge._PROMPT.template.split())

    assert 'write quotation marks as \\" or use single quotes' in text
