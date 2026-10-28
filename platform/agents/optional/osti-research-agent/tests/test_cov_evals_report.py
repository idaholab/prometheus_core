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

"""Coverage for the plain-text terminal summary and Markdown links without transcripts."""

from evals import report as render
from evals import scoring

_PASS = {
    "engine": "deepagent", "status": "completed", "status_match": True,
    "provenance_ok": True, "citation_link_rate": 1.0, "source_hit_rate": 1.0,
    "fact_match": 1.0, "wall_s": 30.0,
}


def _report(records):
    return {"questions": len(records), "engines": ["deepagent"], "records": records,
            "aggregate": scoring.aggregate(records)}


def test_an_unrecognised_failure_reason_gets_no_explanation(monkeypatch):
    monkeypatch.setattr(render, "failures", lambda record: ["something new"])

    assert render.explained_failures({}) == [("something new", "")]


def test_terminal_summary_lists_failures_caps_them_and_counts_judge_errors():
    records = [
        {**_PASS, "id": "ok"},
        {**_PASS, "id": "bad-status", "status_match": False},
        {**_PASS, "id": "no-sources", "provenance_ok": False},
        {**_PASS, "id": "unjudged", "judge_error": "down"},
    ]

    text = render.terminal_summary(_report(records), max_failures=2)
    lines = text.splitlines()

    assert lines[0] == "OSTI evaluation: 4 question(s), engines: deepagent"
    header = lines[2].split()
    assert header[:3] == ["engine", "passed", "status"]
    assert set(lines[3]) == {"-", " "}
    assert lines[4].split()[:2] == ["deepagent", "1/4"]
    assert "Failed (3):" in lines
    assert "  [deepagent] bad-status: status 'completed' not the expected one" in lines
    assert "  [deepagent] no-sources: completed with no sources" in lines
    assert "unjudged: not judged" not in text
    assert "  ... and 1 more (see report.md)" in lines
    assert "Judge errors (1): those questions are unjudged and count as failed." in lines
    assert lines[-1] == render._CAVEAT


def test_terminal_summary_for_an_all_pass_run():
    text = render.terminal_summary(_report([{**_PASS, "id": "ok"}]))

    assert "Every question passed." in text
    assert "Failed" not in text and "Judge errors" not in text


def test_markdown_ids_are_plain_without_a_transcripts_dir():
    record = {**_PASS, "id": "bad", "status_match": False}

    markdown = render.markdown_report(_report([record]))

    assert "| deepagent | bad | status 'completed' not the expected one" in markdown
    assert "result.json" not in markdown
