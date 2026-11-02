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

"""`speccheck report`: the markdown, its links, its escaping and the summary."""

from __future__ import annotations

import pytest

from speccheck.actions import report
from tests.conftest import Repo

CI = {
    "leg": "3.12",
    "job": "unit",
    "sha": "b" * 40,
    "run_url": "https://github.com/o/r/actions/runs/7/attempts/1",
    "job_url": "https://github.com/o/r/actions/runs/7/job/8",
}
"""A results file's CI block with a job link."""


def two_requirements(repo: Repo) -> None:
    """One passing requirement and one unclaimed."""
    repo.spec("- T-REQ-001-01: Passes.\n- T-REQ-001-02: Nobody claims it.", title="The thing")
    repo.results("unit.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "passed")], ci=CI)


@pytest.mark.covers("SPC-REQ-006-01")
def test_the_full_report(repo: Repo):
    """Summary, counts, problems, and one table per spec with the failures first."""
    two_requirements(repo)
    run = repo.run("report", "unit.jsonl")
    assert run.code == 0
    text = run.out
    assert text.startswith("# speccheck requirements\n\n2 requirements: 1 unclaimed, 1 passed\n")
    assert "## Problems (1)" in text
    assert "## 001 The thing" in text
    rows = [line for line in text.splitlines() if line.startswith("| T-REQ")]
    assert [row.split(" | ")[0] for row in rows] == ["| T-REQ-001-02", "| T-REQ-001-01"]


@pytest.mark.covers("SPC-REQ-006-02")
def test_evidence_links_to_the_job(repo: Repo):
    """Test, outcome, producer and leg, and the job link; the run when there's no job ID."""
    two_requirements(repo)
    text = repo.run("report", "unit.jsonl").out
    assert (
        "test `tests/t\\.py::test\\_a` passed in unit 3\\.12 ([job](https://github.com/o/r/actions/runs/7/job/8))"
        in text
    )
    repo.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": CI["run_url"]})
    assert "([job](https://github.com/o/r/actions/runs/7/attempts/1))" in repo.run("report", "unit.jsonl").out


@pytest.mark.covers("SPC-REQ-006-02")
def test_a_ci_job_and_a_waiting_requirement(repo: Repo):
    """A CI job's result says `job`; a requirement nobody reported for says who it waits on."""
    repo.write(
        "speccheck.toml",
        'specs = "specs"\nid-prefix = "T"\n[producers.unit]\n[ci.publish]\ncovers = ["T-REQ-001-01"]\n',
    )
    repo.spec("- T-REQ-001-01: Published.\n- T-REQ-001-02: Tested.")
    repo.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01"], "passed")], kind="ci")
    text = repo.run("report", "p.jsonl").out
    assert "job `publish` passed in publish" in text
    assert "waiting on unit" in text


@pytest.mark.covers("SPC-REQ-006-02")
def test_many_results_are_counted(repo: Repo, monkeypatch: pytest.MonkeyPatch):
    """After MAX_EVIDENCE results, the rest are a count."""
    monkeypatch.setattr(report, "MAX_EVIDENCE", 2)
    repo.spec("- T-REQ-001-01: It.")
    repo.results("u.jsonl", "unit", [(f"t{n}", ["T-REQ-001-01"], "passed") for n in range(4)])
    assert "<br>and 2 more" in repo.run("report", "u.jsonl").out


@pytest.mark.covers("SPC-REQ-006-03")
class TestEscaping:
    """Untrusted strings in markdown."""

    def test_markdown_and_html_are_escaped(self, repo: Repo):
        """A test name can't add a link, an image, HTML or a table column."""
        repo.spec("- T-REQ-001-01: It.")
        evil = "t[x](https://evil)<img src=x>|`"
        repo.results("u.jsonl", "unit", [(evil, ["T-REQ-001-01"], "passed")], ci={"leg": "a|b"})
        text = repo.run("report", "u.jsonl").out
        row = next(line for line in text.splitlines() if line.startswith("| T-REQ-001-01"))
        assert "\\]\\(https://evil\\)" in row and "\\<img src=x\\>" in row
        assert "](https://evil)" not in row.replace("\\]\\(", "") and "<img" not in row.replace("\\<img", "")
        assert row.count(" | ") == 3 and "a\\|b" in row

    def test_text_is_one_line_and_capped(self):
        """Newlines collapse, and long text is cut."""
        assert report.escape("a\nb") == "a b"
        assert report.escape("x" * 300, 10) == "x" * 9 + "…"

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "https://evil.example/o/r/actions/runs/1/job/2)[x](y",
            "http://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/pulls/1",
            None,
            3,
        ],
    )
    def test_only_run_and_job_urls_are_linked(self, url):
        """Anything that isn't a run or job URL of the expected shape gives no link."""
        assert report.safe_url(url) == ""

    def test_good_urls(self):
        """Run, attempt and job URLs, on any host."""
        for url in (
            "https://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/actions/runs/1/attempts/2",
            "https://ghe.example:8443/o/r/actions/runs/1/job/3",
        ):
            assert report.safe_url(url) == url

    def test_an_unsafe_url_in_a_file_is_not_linked(self, repo: Repo):
        """A results file's own `job_url` is checked before it becomes a link."""
        repo.spec("- T-REQ-001-01: It.")
        repo.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={"job_url": "javascript:x"})
        text = repo.run("report", "u.jsonl").out
        assert "javascript" not in text and "[job]" not in text


@pytest.mark.covers("SPC-REQ-006-04")
class TestSummary:
    """The step summary."""

    def test_only_the_rows_that_need_attention(self, repo: Repo):
        """Appended to the file, with the problems and the unclaimed row, not the passed one."""
        two_requirements(repo)
        repo.write("summary.md", "earlier step\n")
        run = repo.run("report", "unit.jsonl", "--summary", "summary.md")
        assert run.code == 0 and run.out == "speccheck report: 2 requirements: 1 unclaimed, 1 passed\n"
        text = (repo.root / "summary.md").read_text()
        assert text.startswith("earlier step\n### speccheck requirements")
        assert "T-REQ-001-02" in text and "| T-REQ-001-01 |" not in text
        assert "**1 problems**" in text

    def test_it_stays_under_the_limit(self, repo: Repo, monkeypatch: pytest.MonkeyPatch):
        """A huge summary is cut at a line, with a note."""
        monkeypatch.setattr(report, "SUMMARY_LIMIT", 200)
        repo.spec("\n".join(f"- T-REQ-001-{n:02}: Unclaimed requirement number {n}." for n in range(1, 30)))
        repo.run("report", "--summary", "s.md")
        text = (repo.root / "s.md").read_text()
        assert len(text.encode()) < 300
        assert text.endswith("… cut to fit the step summary; see the artifact.\n")


@pytest.mark.covers("SPC-REQ-006-05")
def test_the_inputs_are_listed(repo: Repo):
    """Commit, runs, and which producers reported or were missing."""
    repo.write("speccheck.toml", 'specs = "specs"\nid-prefix = "T"\n[producers.unit]\n[producers.docker]\n')
    two_requirements(repo)
    repo.run("report", "unit.jsonl", "--complete", "--output", "out/report.md")
    text = (repo.root / "out" / "report.md").read_text()
    assert "- Commit: bbbbbbbbbbbb" in text
    assert "- Runs: [7/attempts/1](https://github.com/o/r/actions/runs/7/attempts/1)" in text
    assert "- Producers reported: unit" in text
    assert "- Producers missing: docker" in text


@pytest.mark.covers("SPC-REQ-006-05")
def test_inputs_outside_ci(repo: Repo):
    """No CI block: the report says so."""
    repo.spec("- T-REQ-001-01: It. ⚠ untested")
    text = repo.run("report").out
    assert "- Commit: unknown (not run in CI)" in text and "- Runs: none" in text and "## Problems" not in text
    repo.run("report", "--summary", "s.md")
    summary = (repo.root / "s.md").read_text()
    assert "| ID |" not in summary and "problems" not in summary


@pytest.mark.covers("SPC-REQ-006-06", "SPC-REQ-008-04")
def test_report_exits_0_on_failures_and_gives_json(repo: Repo):
    """The report is published even when verify fails, and `--json` is the same data."""
    two_requirements(repo)
    run = repo.run("report", "unit.jsonl", "--json")
    body = run.json()
    assert run.code == 0 and body["ok"] is True and body["command"] == "report"
    assert body["title"] == "speccheck requirements"
    assert [r["status"] for r in body["requirements"]] == ["passed", "unclaimed"]
    assert len(body["problems"]) == 1
