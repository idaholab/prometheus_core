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

"""specs/006-report.md: the markdown `speccheck report` writes, read as a reader would."""

from __future__ import annotations

import pytest

from tests.requirements.conftest import Project

CI = {
    "leg": "3.12",
    "job": "unit",
    "sha": "d" * 40,
    "run_url": "https://github.com/o/r/actions/runs/7/attempts/2",
    "job_url": "https://github.com/o/r/actions/runs/7/job/8",
}
"""A results file's CI block, from a re-run with a job ID."""
ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""The run `report` is in: links must be under its server and repository."""


def rows(text: str) -> list[list[str]]:
    """Every requirement row of the report's tables, split into cells."""
    return [[c.strip() for c in line.strip("|").split(" | ")] for line in text.splitlines() if line.startswith("| T-")]


@pytest.fixture
def reported(project: Project) -> Project:
    """A project with one passing, one failing and one unclaimed requirement, and a results file."""
    project.spec(
        "- T-REQ-001-01: Passes.\n- T-REQ-001-02: Fails.\n- T-REQ-001-03: Nobody claims it.", title="The thing"
    )
    project.results(
        "unit.jsonl",
        "unit",
        [("tests/t.py::test_ok", ["T-REQ-001-01"], "passed"), ("tests/t.py::test_bad", ["T-REQ-001-02"], "failed")],
        ci=CI,
    )
    return project


@pytest.mark.covers("SPC-REQ-006-01")
def test_summary_counts_and_tables(reported: Project):
    """A summary line, a count per status, then the spec's table with what needs attention first."""
    text = reported.speccheck("report", "unit.jsonl").out
    assert text.startswith("# speccheck requirements\n\n3 requirements: 1 failed, 1 unclaimed, 1 passed\n")
    assert "❌ failed: 1 · ❌ unclaimed: 1 · ✅ passed: 1" in text
    assert "## 001 The thing" in text
    assert [(r[0], r[1]) for r in rows(text)] == [
        ("T-REQ-001-02", "❌ failed"),
        ("T-REQ-001-03", "❌ unclaimed"),
        ("T-REQ-001-01", "✅ passed"),
    ]
    assert rows(text)[2][2] == "Passes\\."


@pytest.mark.covers("SPC-REQ-006-02")
def test_evidence_names_the_test_and_links_the_job(reported: Project):
    """Test, outcome, producer, leg, and a link to the job itself."""
    evidence = rows(reported.speccheck("report", "unit.jsonl", env=ENV).out)[2][3]
    assert evidence == (
        "test `tests/t.py::test_ok` passed in unit 3\\.12 ([job](https://github.com/o/r/actions/runs/7/job/8))"
    )


@pytest.mark.covers("SPC-REQ-006-02")
def test_without_a_job_id_it_links_the_run(project: Project):
    """The fallback link is the run attempt."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": CI["run_url"]})
    assert (
        "([job](https://github.com/o/r/actions/runs/7/attempts/2))"
        in project.speccheck("report", "u.jsonl", env=ENV).out
    )


@pytest.mark.covers("SPC-REQ-006-03")
def test_untrusted_text_cant_inject_markdown_or_links(project: Project):
    """A test name with a link, HTML, a pipe and a backtick stays inert text in its cell, and a bad URL isn't linked.

    The test name is a code span, where markdown and HTML mean nothing, with its backtick dropped
    so it can't close the span; the leg, outside the span, is backslash-escaped.
    """
    project.spec("- T-REQ-001-01: One.")
    evil = "t[click](https://evil)<img src=x onerror=1>|`"
    project.results(
        "u.jsonl", "unit", [(evil, ["T-REQ-001-01"], "passed")], ci={"leg": "a|b", "job_url": "javascript:x"}
    )
    text = project.speccheck("report", "u.jsonl").out
    row = next(line for line in text.splitlines() if line.startswith("| T-REQ-001-01"))
    assert row.count(" | ") == 3
    assert rows(text)[0][3] == "test `t[click](https://evil)<img src=x onerror=1>\\|` passed in unit a\\|b"
    assert "javascript" not in text and "[job]" not in row


@pytest.mark.covers("SPC-REQ-006-03")
@pytest.mark.parametrize(
    ("url", "env"),
    [
        ("https://evil.example/o/r/actions/runs/7/job/8", ENV),
        ("https://github.com/evil/r/actions/runs/7/job/8", ENV),
        ("https://github.com/o/r/actions/runs/7/job/8\n", ENV),
        ("https://github.com/o/r/actions/runs/7/job/8", {}),
    ],
)
def test_only_this_runs_repository_is_linked(project: Project, url: str, env: dict):
    """A run or job URL on another host or repository isn't linked, and outside CI nothing is."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": url, "run_url": url})
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert "[job]" not in text and "- Runs: none" in text
    assert "evil" not in text


@pytest.mark.covers("SPC-REQ-006-03")
def test_long_text_is_capped(project: Project):
    """A huge test name doesn't make a huge cell."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("x" * 900, ["T-REQ-001-01"], "passed")])
    row = next(line for line in project.speccheck("report", "u.jsonl").out.splitlines() if line.startswith("| T-REQ"))
    assert len(row) < 400 and "…" in row


@pytest.mark.covers("SPC-REQ-006-04")
def test_the_step_summary(reported: Project):
    """Appended, with counts, problems and only the rows that need attention, and a pointer to the artifact."""
    reported.write("summary.md", "an earlier step's summary\n")
    run = reported.speccheck("report", "unit.jsonl", "--summary", "summary.md")
    assert run.code == 0
    text = (reported.root / "summary.md").read_text()
    assert text.startswith("an earlier step's summary\n### speccheck requirements\n")
    assert [r[0] for r in rows(text)] == ["T-REQ-001-02", "T-REQ-001-03"]
    assert "**2 problems**" in text and "The full report is in the `speccheck-report` artifact." in text


@pytest.mark.covers("SPC-REQ-006-04")
def test_the_step_summary_stays_under_the_limit(project: Project):
    """Thousands of unclaimed requirements still give a summary under GitHub's 1 MiB."""
    body = "\n".join(f"- T-REQ-001-{n:02}: {'Long requirement text. ' * 20}" for n in range(1, 100))
    project.spec(body)
    project.results("u.jsonl", "unit", [(f"t{'x' * 900}{n}", ["T-REQ-001-01"], "failed") for n in range(3000)])
    project.speccheck("report", "u.jsonl", "--summary", "s.md")
    assert len((project.root / "s.md").read_bytes()) <= 1024 * 1024


@pytest.mark.covers("SPC-REQ-006-05")
def test_the_inputs(reported: Project):
    """Commit, runs, producers reported and missing."""
    reported.write("speccheck.toml", 'specs = "specs"\nid-prefix = "T"\n[producers.unit]\n[producers.docker]\n')
    reported.speccheck("report", "unit.jsonl", "--complete", "--output", "out/report.md", env=ENV)
    text = (reported.root / "out" / "report.md").read_text()
    inputs = text.split("## Inputs", 1)[1]
    assert "- Commit: dddddddddddd" in inputs
    assert "- Runs: [7/attempts/2](https://github.com/o/r/actions/runs/7/attempts/2)" in inputs
    assert "- Producers reported: unit" in inputs and "- Producers missing: docker" in inputs


@pytest.mark.covers("SPC-REQ-006-06")
def test_report_exits_0_when_verify_fails(reported: Project):
    """The same inputs fail verify and still give a report, with exit 0."""
    assert reported.speccheck("verify", "unit.jsonl").code == 1
    run = reported.speccheck("report", "unit.jsonl", "--output", "r.md")
    assert run.code == 0 and (reported.root / "r.md").is_file()
