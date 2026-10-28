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

"""Coverage tests for deep_agent analysis/verification guards and failure paths."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from research_agent.core import deep_agent
from research_agent.core.deep_agent import (
    PaperAnalysisTaskError,
    VerifierProtocolError,
    _analyze_paper,
    _parsed_paper_directory,
    _read_file_paths,
    _source_id_aliases,
    _validated_artifacts,
    _verification_payload,
    build_analyze_paper_tool,
)
from research_agent.core.events import Finding
from tests.test_deep_agent import (
    _analysis_result,
    _FakeRunnable,
    _verification,
    _verification_context,
    _verification_result,
)

QUESTION = "Does titanium creep?"


def _analyze(context, analyzer, verifier, source_id="123", question=QUESTION):
    return asyncio.run(
        _analyze_paper(
            source_id, question, analyzer=analyzer, verifier=verifier, ctx=context
        )
    )


def _read_call(path, call_id="r"):
    return {"name": "read_file", "args": {"file_path": path}, "id": call_id, "type": "tool_call"}


# --- analyzer candidate parsing -------------------------------------------------


def test_analyzer_text_in_content_parts_is_parsed(tmp_path):
    context = _verification_context(tmp_path)
    text = _analysis_result()["messages"][0].content
    analysis = {
        "messages": [
            AIMessage(content=[{"type": "text", "text": text}, {"type": "image"}, "raw"]),
            AIMessage(content=[{"type": "text", "text": "   "}]),
        ]
    }
    verifier = _FakeRunnable(result=_verification_result())

    result = _analyze(context, _FakeRunnable(result=analysis), verifier)

    assert result["source_id"] == "123"
    assert verifier.calls == 1
    assert [f.source_id for f in context.findings] == ["123"]


@pytest.mark.parametrize(
    "content, reason",
    [
        ("I could not find anything useful.", "did not return a JSON object"),
        (json.dumps({"source_id": "123", "answer": "a", "match": "maybe"}), "invalid Finding"),
        (json.dumps({"source_id": "123", "answer": "   "}), "incomplete Finding"),
    ],
)
def test_unusable_analyzer_reply_is_recorded_as_not_used(tmp_path, content, reason):
    context = _verification_context(tmp_path)
    verifier = _FakeRunnable(result=_verification_result())
    analyzer = _FakeRunnable(result={"messages": [AIMessage(content=content)]})

    result = _analyze(context, analyzer, verifier)

    assert result["answered"] is False
    assert reason in result["reason"]
    assert verifier.calls == 0
    assert context.unused_papers["123"]["by"] == "analyzer"
    assert context.findings == []


def test_analyzer_exception_is_an_operational_failure_and_cached(tmp_path):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(error=RuntimeError("provider down"))
    verifier = _FakeRunnable(result=_verification_result())

    first = _analyze(context, analyzer, verifier)
    second = _analyze(context, analyzer, verifier)

    assert first == second
    assert first["answered"] is False
    assert "analyzer failure" in first["reason"]
    assert context.verification_errors == ["123: analyzer_failure"]
    assert analyzer.calls == 1
    assert verifier.calls == 0


# --- source id resolution and request validation --------------------------------


def test_doi_url_aliases_include_slug_and_osti_id():
    assert _source_id_aliases("https://doi.org/10.2172/7338208") == [
        "https://doi.org/10.2172/7338208",
        "10.2172_7338208",
        "7338208",
    ]
    assert _source_id_aliases("DOI:10.1/ab") == ["DOI:10.1/ab", "10.1_ab"]


def test_doi_url_request_resolves_to_parsed_slug(tmp_path):
    source_id = "10.2172_7338208"
    paper_path = f"/papers/{source_id}/paper.md"
    context = _verification_context(tmp_path, source_id)
    analyzer = _FakeRunnable(result=_analysis_result(source_id))
    verifier = _FakeRunnable(
        result=_verification_result(
            source_id=source_id, artifacts=[paper_path], read_path=paper_path
        )
    )

    result = _analyze(context, analyzer, verifier, source_id="https://doi.org/10.2172/7338208")

    assert result["source_id"] == source_id
    assert context.findings[0].source_id == source_id


@pytest.mark.parametrize(
    "source_id, question", [("  ", QUESTION), ("123", "  ")], ids=["no-source", "no-question"]
)
def test_empty_request_is_a_cached_task_path_failure(tmp_path, source_id, question):
    context = _verification_context(tmp_path)
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(result=_verification_result())

    first = _analyze(context, analyzer, verifier, source_id=source_id, question=question)
    context.verification_errors.clear()
    second = _analyze(context, analyzer, verifier, source_id=source_id, question=question)

    assert first == second
    assert first["answered"] is False
    assert "task path failure" in first["reason"]
    # the second call is served from the invalid-request cache: no new error
    assert context.verification_errors == []
    assert analyzer.calls == 0
    expected_id = source_id.strip() or "unknown"
    assert f"do not retry source {expected_id}" in first["reason"]


def test_parsed_directory_guards(tmp_path):
    context = _verification_context(tmp_path)

    with pytest.raises(PaperAnalysisTaskError, match="has not been parsed"):
        _parsed_paper_directory("999", context)

    context.parsed_papers["a"] = {"dir": "   "}
    with pytest.raises(PaperAnalysisTaskError, match="no parsed paper directory"):
        _parsed_paper_directory("a", context)

    context.parsed_papers["b"] = {"dir": "/elsewhere/b"}
    with pytest.raises(PaperAnalysisTaskError, match="invalid parsed directory"):
        _parsed_paper_directory("b", context)

    context.parsed_papers["c"] = {"dir": "/papers/c"}
    with pytest.raises(PaperAnalysisTaskError, match="is unavailable"):
        _parsed_paper_directory("c", context)


def test_missing_parsed_directory_on_disk_fails_analysis(tmp_path):
    context = _verification_context(tmp_path)
    context.parsed_papers["456"] = {"dir": "/papers/456"}
    analyzer = _FakeRunnable(result=_analysis_result("456"))

    result = _analyze(context, analyzer, _FakeRunnable(), source_id="456")

    assert result["answered"] is False
    assert context.verification_errors == ["456: task_path_failure"]
    assert analyzer.calls == 0


# --- verifier artifact and payload validation -----------------------------------


def test_accepted_verification_must_cite_an_artifact(tmp_path):
    context = _verification_context(tmp_path)

    with pytest.raises(VerifierProtocolError, match="did not cite any artifact"):
        _validated_artifacts([], "/papers/123", context, {"/papers/123/paper.md"})


def test_artifact_must_name_a_file_inside_the_directory(tmp_path):
    context = _verification_context(tmp_path)

    with pytest.raises(VerifierProtocolError, match="does not name a file"):
        _validated_artifacts(["/papers/123"], "/papers/123", context, {"/papers/123"})


def test_read_but_missing_artifact_is_rejected(tmp_path):
    context = _verification_context(tmp_path)
    ghost = "/papers/123/tables/ghost.md"

    with pytest.raises(VerifierProtocolError, match="does not exist"):
        _validated_artifacts([ghost], "/papers/123", context, {ghost})


def test_meta_json_citation_is_dropped_and_paper_md_must_be_read(tmp_path):
    context = _verification_context(tmp_path)
    tables = tmp_path / "papers" / "123" / "tables"
    tables.mkdir()
    (tables / "t1.md").write_text("| T | rate |")
    artifacts = ["/papers/123/meta.json", "/papers/123/tables/t1.md"]

    with pytest.raises(VerifierProtocolError, match="independently read paper.md"):
        _validated_artifacts(artifacts, "/papers/123", context, {"/papers/123/tables/t1.md"})

    validated = _validated_artifacts(
        artifacts + ["/papers/123/paper.md"],
        "/papers/123",
        context,
        {"/papers/123/tables/t1.md", "/papers/123/paper.md"},
    )
    assert validated == ["/papers/123/tables/t1.md", "/papers/123/paper.md"]


def test_read_file_paths_skips_malformed_calls_and_counts_grep_matches():
    grep_call = {
        "name": "grep",
        "args": {"pattern": "creep", "output_mode": "content"},
        "id": "g1",
        "type": "tool_call",
    }
    ai = AIMessage(content="", tool_calls=[_read_call("/papers/1/paper.md"), grep_call])
    # tool_calls on AIMessage are normalized dicts; use plain objects for the
    # malformed shapes the guard protects against.
    odd = SimpleNamespace(
        type="ai",
        tool_calls=["not-a-dict", {"name": "read_file", "args": "bad-args"}],
    )
    grep_output = ToolMessage(
        content=[
            {"type": "text", "text": "/papers/1/tables/t1.md:\n"},
            "  3: creep rate 1e-7\n",
            {"type": "text", "text": "/papers/1/meta.json:\n"},
        ],
        tool_call_id="g1",
    )

    paths = _read_file_paths({"messages": [ai, odd, grep_output]})

    assert paths == {"/papers/1/paper.md", "/papers/1/tables/t1.md"}


def test_verification_payload_rejects_non_dict_state():
    with pytest.raises(VerifierProtocolError, match="invalid result state"):
        _verification_payload(["not", "a", "state"])


def test_verification_payload_reads_json_from_ai_content_parts():
    verdict = _verification().model_dump_json()
    state = {
        "messages": [
            AIMessage(content=[{"type": "text", "text": verdict}, "ignored"]),
            AIMessage(content=[{"type": "text", "text": " "}]),
            ToolMessage(content="tool text is never the verdict", tool_call_id="x"),
        ]
    }

    assert _verification_payload(state)["verdict"] == "supported"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"verdict": "maybe"}, "unknown verifier verdict"),
        ({"evidence": "   "}, "omitted answer or evidence"),
    ],
)
def test_bad_verdicts_are_verifier_protocol_failures(tmp_path, caplog, overrides, message):
    context = _verification_context(tmp_path)
    verifier = _FakeRunnable(result=_verification_result(**overrides))

    result = _analyze(context, _FakeRunnable(result=_analysis_result()), verifier)

    assert result["answered"] is False
    assert context.verification_errors == ["123: verifier_protocol_failure"]
    assert context.findings == []
    assert message in caplog.text


def test_existing_finding_for_source_is_kept_not_duplicated(tmp_path):
    context = _verification_context(tmp_path)
    earlier = Finding(source_id="123", answer="Earlier verified answer", evidence="Fig. 1")
    context.findings.append(earlier)
    verifier = _FakeRunnable(result=_verification_result())

    result = _analyze(context, _FakeRunnable(result=_analysis_result()), verifier)

    assert context.findings == [earlier]
    assert result["answer"] == "Earlier verified answer"


# --- the orchestrator-facing tool -----------------------------------------------


def test_analyze_paper_tool_marks_terminal_and_retryable_results(tmp_path, monkeypatch):
    analyzer = _FakeRunnable(result=_analysis_result())
    verifier = _FakeRunnable(result=_verification_result())
    monkeypatch.setattr(deep_agent, "chat_model", lambda config, role: object())
    monkeypatch.setattr("deepagents.create_deep_agent", lambda **kwargs: analyzer)
    monkeypatch.setattr(deep_agent, "build_paper_verifier", lambda config, backend: verifier)
    context = _verification_context(tmp_path)

    tool = build_analyze_paper_tool(context.config, context, backend=object())

    retry = json.loads(asyncio.run(tool.ainvoke({"source_id": "999", "question": QUESTION})))
    assert retry["terminal"] is False
    assert retry["reason"] == "paper has not been parsed"
    assert "instruction" not in retry

    done = json.loads(asyncio.run(tool.ainvoke({"source_id": "123", "question": QUESTION})))
    assert done["terminal"] is True
    assert done["source_id"] == "123"
    assert "do not call analyze_paper" in done["instruction"]


def test_analyzer_with_no_text_and_explicit_decline(tmp_path):
    context = _verification_context(tmp_path)
    verifier = _FakeRunnable(result=_verification_result())
    empty = _FakeRunnable(result={"messages": [AIMessage(content="")]})

    assert "did not return a JSON object" in _analyze(context, empty, verifier)["reason"]

    context.parsed_papers["124"] = {"dir": "/papers/124"}
    (tmp_path / "papers" / "124").mkdir()
    declined = _FakeRunnable(
        result={"messages": [AIMessage(content=json.dumps({"answered": False}))]}
    )
    result = _analyze(context, declined, verifier, source_id="124")
    assert result["reason"] == "paper did not answer the question"
    assert verifier.calls == 0


def test_verifier_without_any_ai_text_is_a_protocol_failure():
    state = {"messages": [ToolMessage(content="x", tool_call_id="t"), AIMessage(content="")]}

    with pytest.raises(VerifierProtocolError, match="neither a structured response"):
        _verification_payload(state)


def test_grep_string_output_counts_and_unknown_match_label_fails(tmp_path, caplog):
    grep_call = {
        "name": "grep",
        "args": {"output_mode": "content"},
        "id": "g",
        "type": "tool_call",
    }
    output = ToolMessage(content="/papers/1/paper.md:\n  1: creep\n", tool_call_id="g")
    paths = _read_file_paths({"messages": [AIMessage(content="", tool_calls=[grep_call]), output]})
    assert paths == {"/papers/1/paper.md"}

    context = _verification_context(tmp_path)
    verifier = _FakeRunnable(result=_verification_result(match="sideways"))
    result = _analyze(context, _FakeRunnable(result=_analysis_result()), verifier)
    assert result["answered"] is False
    assert "unknown verifier match" in caplog.text
