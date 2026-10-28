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

"""Which files the verifier saw: read_file calls, and content-mode grep
matches, using deepagents' own grep output format."""

import asyncio

from deepagents.backends.utils import format_grep_matches
from langchain_core.messages import AIMessage, ToolMessage

from research_agent.core import deep_agent
from tests.test_deep_agent import (
    _FakeRunnable,
    _analysis_result,
    _verification,
    _verification_context,
)

PAPER = "/papers/123/paper.md"
TABLE = "/papers/123/tables/table_01.md"


def _call(name, call_id, **args):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _grep(call_id, output_mode, matches):
    return [
        AIMessage(content="", tool_calls=[
            _call("grep", call_id, pattern="800", path="/papers/123", output_mode=output_mode)
        ]),
        ToolMessage(
            content=format_grep_matches(matches, output_mode),
            name="grep",
            tool_call_id=call_id,
        ),
    ]


def _match(path, line=12, text="Measured creep begins above 800 C."):
    return {"path": path, "line": line, "text": text}


def test_read_file_counts():
    read = AIMessage(content="", tool_calls=[_call("read_file", "r", file_path=PAPER)])
    result = {"messages": [read]}

    assert deep_agent._read_file_paths(result) == {PAPER}


def test_content_grep_counts_each_file_it_shows_text_from():
    result = {"messages": _grep("g", "content", [_match(PAPER), _match(TABLE, 3)])}

    assert deep_agent._read_file_paths(result) == {PAPER, TABLE}


def test_content_grep_with_context_counts_too():
    match = {**_match(PAPER), "context_before": [{"line": 11, "text": "Results"}],
             "context_after": []}
    result = {"messages": _grep("g", "content", [match])}

    assert deep_agent._read_file_paths(result) == {PAPER}


def test_a_file_name_listing_or_count_does_not_count():
    listing = {"messages": _grep("g", "files_with_matches", [_match(PAPER)])}
    counts = {"messages": _grep("g", "count", [_match(PAPER)])}

    assert deep_agent._read_file_paths(listing) == set()
    assert deep_agent._read_file_paths(counts) == set()


def test_a_grep_with_no_matches_does_not_count():
    result = {"messages": _grep("g", "content", [])}

    assert deep_agent._read_file_paths(result) == set()


def test_a_tool_result_without_a_content_grep_call_does_not_count():
    # Matches text from another tool must not be taken as a read.
    result = {"messages": [
        AIMessage(content="", tool_calls=[_call("ls", "l", path="/papers/123")]),
        ToolMessage(content=f"{PAPER}:\n  12: text", name="ls", tool_call_id="l"),
    ]}

    assert deep_agent._read_file_paths(result) == set()


def test_a_verifier_that_grepped_paper_md_is_accepted(tmp_path):
    context = _verification_context(tmp_path)
    verification = {
        "structured_response": _verification(artifacts=[PAPER]),
        "messages": _grep("g", "content", [_match(PAPER)]),
    }

    result = asyncio.run(
        deep_agent._analyze_paper(
            "123", "Does titanium creep?",
            analyzer=_FakeRunnable(result=_analysis_result()),
            verifier=_FakeRunnable(result=verification),
            ctx=context,
        )
    )

    assert result["source_id"] == "123" and context.verification_errors == []


def test_a_verifier_that_only_listed_files_is_still_refused(tmp_path):
    context = _verification_context(tmp_path)
    verification = {
        "structured_response": _verification(artifacts=[PAPER]),
        "messages": _grep("g", "files_with_matches", [_match(PAPER)]),
    }

    result = asyncio.run(
        deep_agent._analyze_paper(
            "123", "Does titanium creep?",
            analyzer=_FakeRunnable(result=_analysis_result()),
            verifier=_FakeRunnable(result=verification),
            ctx=context,
        )
    )

    assert result["answered"] is False
    assert context.verification_errors == ["123: verifier_protocol_failure"]


def _verify_with(tmp_path, artifacts, messages):
    context = _verification_context(tmp_path)
    (tmp_path / "papers" / "123" / "tables").mkdir(exist_ok=True)
    (tmp_path / "papers" / "123" / "tables" / "table_01.md").write_text("| 800 |")
    verification = {
        "structured_response": _verification(artifacts=artifacts),
        "messages": messages,
    }
    result = asyncio.run(
        deep_agent._analyze_paper(
            "123", "Does titanium creep?",
            analyzer=_FakeRunnable(result=_analysis_result()),
            verifier=_FakeRunnable(result=verification),
            ctx=context,
        )
    )
    return result, context


def _read(path, call_id="r"):
    return AIMessage(content="", tool_calls=[_call("read_file", call_id, file_path=path)])


def test_an_unread_meta_json_citation_is_dropped_not_fatal(tmp_path):
    result, context = _verify_with(
        tmp_path, [PAPER, "/papers/123/meta.json"], [_read(PAPER)]
    )

    assert result["source_id"] == "123" and context.verification_errors == []
    assert context.findings[0].artifacts == [PAPER]


def test_a_read_meta_json_citation_is_kept(tmp_path):
    result, context = _verify_with(
        tmp_path, [PAPER, "/papers/123/meta.json"],
        [_read(PAPER), _read("/papers/123/meta.json", "m")],
    )

    assert context.findings[0].artifacts == [PAPER, "/papers/123/meta.json"]


def test_an_unread_evidence_file_still_fails_the_finding(tmp_path):
    result, context = _verify_with(tmp_path, [PAPER, TABLE], [_read(PAPER)])

    assert result["answered"] is False
    assert context.verification_errors == ["123: verifier_protocol_failure"]
