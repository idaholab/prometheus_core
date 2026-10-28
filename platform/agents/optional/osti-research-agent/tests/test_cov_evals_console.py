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

"""Coverage for the rich console helpers: styles, overflow, judge lines."""

from evals import console as rich_out
from evals import scoring

_BASE = {
    "engine": "deepagent", "status": "completed", "status_match": True,
    "provenance_ok": True, "citation_link_rate": 1.0, "source_hit_rate": 1.0,
    "fact_match": 1.0, "wall_s": 12.0,
}


def _report(records):
    return {"questions": len(records), "engines": ["deepagent"], "records": records,
            "aggregate": scoring.aggregate(records), "complete": True}


def test_unscored_values_and_non_numeric_cells_are_dim_or_unstyled():
    assert rich_out._score_style(None) == "dim"
    assert rich_out._score_style(5) == "green" and rich_out._score_style(2) == "red"
    assert rich_out._fraction_style("-") == ""
    assert rich_out._fraction_style("0/3") == "red"
    assert rich_out._fraction_style("1/3") == "yellow"
    assert rich_out._rate_style("-") == "dim"
    assert rich_out._rate_style("0.50") == "yellow" and rich_out._rate_style("0.1") == "red"


def test_failures_table_caps_rows_and_says_how_many_more():
    records = [{**_BASE, "id": f"q{i}", "status_match": False} for i in range(3)]

    table = rich_out.failures_table(_report(records), max_failures=2)

    assert table.row_count == 2
    assert table.caption == "... and 1 more in report.md"


def test_why_shows_the_judge_rationale_once_for_several_low_scores():
    record = {**_BASE, "id": "q", "judge_groundedness": 2, "judge_completeness": 1,
              "judge_rationale": "Unsupported numbers."}

    text = rich_out._why(record).plain

    assert text.count("Unsupported numbers.") == 1
    assert text.splitlines() == [
        "judge groundedness 2/5: Unsupported numbers.",
        "judge completeness 1/5",
    ]


def test_summary_counts_judge_errors_as_unjudged():
    record = {**_BASE, "id": "q-err", "judge_error": "judge reply had no JSON object"}

    text = rich_out.plain_summary(_report([record]))

    assert "Judge errors (1): those questions are unjudged and count as failed." in text
    assert "Failed (1)" in text


def test_result_line_marks_a_judge_error_when_nothing_was_scored():
    record = {**_BASE, "id": "q-err", "judge_error": "down"}

    line = rich_out.result_line(record)

    assert "judge error" in line.plain
    assert line.plain.startswith(" FAIL ") and "not judged" in line.plain
    styles = {str(span.style) for span in line.spans}
    assert "yellow" in styles
