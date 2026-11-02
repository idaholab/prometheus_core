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

"""`speccheck report`: escaping, links, rows, the full report and the summary, on evaluations built in memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from speccheck import evidence, results
from speccheck.actions import report
from speccheck.specs import Problem
from tests.unit.conftest import make_config, make_ctx, make_requirement, make_spec, make_specs, namespace, out

JOB_URL = "https://github.com/o/r/actions/runs/7/job/8"
"""A job link."""
RUN_URL = "https://github.com/o/r/actions/runs/7/attempts/1"
"""A run attempt's link."""
CI = {"leg": "3.12", "job": "unit", "sha": "b" * 40, "run_url": RUN_URL, "job_url": JOB_URL}
"""A results file's CI block with a job link."""


def source(producer: str = "unit", ci: dict | None = None) -> results.ResultsFile:
    """A results file to hang evidence on."""
    return results.ResultsFile(producer=producer, ci=ci)


def status(
    name: str, *found: tuple[str, str], text: str = "It.", line: int = 0, ci: dict | None = None, kind: str = "test"
) -> evidence.Status:
    """A status of a fresh requirement, with `(test, outcome)` evidence from `unit`."""
    requirement = make_requirement(make_spec(), text, line=line)
    from_file = source(ci=ci)
    items = [evidence.Evidence(results.Result(t, [requirement.id], o, kind=kind), from_file) for t, o in found]
    return evidence.Status(requirement, name, items)


def evaluation(
    *statuses: evidence.Status, problems=(), files=(), reported=("unit",), missing=()
) -> evidence.Evaluation:
    """An evaluation of the given statuses."""
    return evidence.Evaluation(list(statuses), list(problems), list(reported), list(missing), list(files))


class TestEscape:
    """Untrusted strings in markdown."""

    def test_special_characters(self):
        """Markdown and HTML are backslashed."""
        assert report.escape("t[x](https://evil)<img>|`") == r"t\[x\]\(https://evil\)\<img\>\|\`"

    def test_one_line_and_capped(self):
        """Whitespace collapses, and long text is cut."""
        assert report.escape("a\n b\tc") == "a b c"
        assert report.escape("x" * 300, 10) == "x" * 9 + "…"
        assert report.escape(3) == "3"


class TestCode:
    """Untrusted strings in an inline code span, where markdown shows backslashes as they are."""

    def test_literal_text_without_backticks(self):
        """Markdown characters stay as written; a backtick is dropped so the span can't close early."""
        assert report.code("tests/t.py::test_a[x*](y)<b>", in_table=False) == "`tests/t.py::test_a[x*](y)<b>`"
        assert report.code("a`b``c", in_table=False) == "`abc`"

    def test_a_pipe_in_a_table(self):
        """GFM splits a row on `|` before it reads the span, so it is written `\\|` there only."""
        assert report.code("a|b", in_table=True) == r"`a\|b`"
        assert report.code("a|b", in_table=False) == "`a|b`"

    def test_one_line_and_capped(self):
        """Whitespace collapses, and long text is cut, after the backticks are gone."""
        assert report.code("a\n b", in_table=False) == "`a b`"
        assert report.code("`" * 5 + "x" * 20, 10, in_table=False) == "`" + "x" * 9 + "…`"


class TestSafeUrl:
    """Only run and job URLs of the shape this tool builds are linked."""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "https://evil.example/o/r/actions/runs/1/job/2)[x](y",
            "http://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/pulls/1",
            "https://github.com/o/r/actions/runs/x",
            None,
            3,
        ],
    )
    def test_rejected(self, url):
        """Anything else gives no link."""
        assert report.safe_url(url) == ""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/o/r/actions/runs/1",
            "https://github.com/o/r/actions/runs/1/attempts/2",
            "https://ghe.example:8443/o/r/actions/runs/1/job/3",
        ],
    )
    def test_accepted(self, url):
        """Run, attempt and job URLs, on any https host."""
        assert report.safe_url(url) == url


class TestEvidenceCell:
    """The Evidence column."""

    def test_a_test_with_a_job_link(self):
        """Test, outcome, producer and leg, then the link."""
        cell = report._evidence_cell(status("passed", ("tests/t.py::test_a", "passed"), ci=CI))
        assert cell == rf"test `tests/t.py::test_a` passed in unit 3\.12 ([job]({JOB_URL}))"

    def test_the_run_when_there_is_no_job_and_none_when_unsafe(self):
        """The run link stands in for the job's; an unsafe one is dropped."""
        cell = report._evidence_cell(status("passed", ("t", "passed"), ci={"run_url": RUN_URL}))
        assert cell.endswith(f"([job]({RUN_URL}))")
        assert "[job]" not in report._evidence_cell(status("passed", ("t", "passed"), ci={"job_url": "javascript:x"}))

    def test_a_ci_job_and_no_leg(self):
        """A CI job's result says `job`; no leg, no trailing space."""
        assert (
            report._evidence_cell(status("passed", ("publish", "passed"), kind="ci")) == "job `publish` passed in unit"
        )

    def test_a_backtick_cant_close_the_code_span(self):
        """A backtick in the test name is dropped, and nothing is left in its place."""
        assert report._evidence_cell(status("passed", ("a`b", "passed"))) == "test `ab` passed in unit"

    def test_many_results_are_counted(self, monkeypatch: pytest.MonkeyPatch):
        """After MAX_EVIDENCE results, the rest are a count."""
        monkeypatch.setattr(report, "MAX_EVIDENCE", 2)
        cell = report._evidence_cell(status("passed", *[(f"t{n}", "passed") for n in range(4)]))
        assert cell.count("<br>") == 2 and cell.endswith("<br>and 2 more")

    def test_waiting_and_nothing(self):
        """Without evidence: who it waits on, else a dash."""
        waiting = status("not run")
        waiting.waiting_on = ["unit", "a|b"]
        assert report._evidence_cell(waiting) == r"waiting on unit, a\|b"
        assert report._evidence_cell(status("unclaimed")) == "—"


def test_a_row_stays_four_columns():
    """ID, icon and status, escaped text, evidence."""
    row = report._row(status("failed", ("t|x", "skipped"), text="Pipes | and <b>"))
    assert row == r"| T-REQ-001-01 | ❌ failed | Pipes \| and \<b\> | test `t\|x` skipped in unit |"
    assert row.count(" | ") == 3


def test_order_puts_attention_first():
    """Failed, unclaimed and not run before passed, then retired; ties in spec order."""
    statuses = [
        status("retired", line=1),
        status("passed", line=2),
        status("failed", line=9),
        status("failed", line=3),
        status("not run", line=4),
    ]
    ordered = [(s.status, s.requirement.line) for s in sorted(statuses, key=report._order)]
    assert ordered == [("failed", 3), ("failed", 9), ("not run", 4), ("passed", 2), ("retired", 1)]


class TestInputs:
    """What the report was built from."""

    def test_from_ci_files(self):
        """Commits, run links and producers, each once."""
        files = [source(ci=CI), source(ci=CI), source(ci={"run_url": "javascript:x", "sha": ""})]
        lines = report._inputs(evaluation(files=files, missing=["docker"]))
        assert lines == [
            "- Commit: bbbbbbbbbbbb",
            f"- Runs: [7/attempts/1]({RUN_URL})",
            "- Producers reported: unit",
            "- Producers missing: docker",
        ]

    def test_outside_ci(self):
        """No CI block and nobody reported."""
        assert report._inputs(evaluation(files=[source()], reported=[])) == [
            "- Commit: unknown (not run in CI)",
            "- Runs: none",
            "- Producers reported: none",
        ]


def test_problems_are_a_list_of_code_spans():
    """Literal and without backticks, so a problem reads as written and can't break out of its span."""
    lines = report._problems(evaluation(problems=[Problem("a`b.md", 1, "x*y|z")]))
    assert lines == ["- `ab.md:1: x*y|z`"]


class TestFull:
    """The whole report."""

    def test_the_layout(self):
        """Title, summary, counts, problems, a table per spec with attention first, then the inputs."""
        spec = make_spec(title="The thing")
        passed = evidence.Status(make_requirement(spec, "Passes."), "passed")
        unclaimed = evidence.Status(make_requirement(spec, "Nobody."), "unclaimed")
        other = evidence.Status(make_requirement(make_spec("002", title="Other")), "planned")
        text = report.full("Title*", evaluation(passed, unclaimed, other, problems=[Problem("p", 1, "m")]))
        lines = text.splitlines()
        assert lines[:5] == ["# Title\\*", "", "3 requirements: 1 unclaimed, 1 passed, 1 planned", "", lines[4]]
        assert lines[4] == "❌ unclaimed: 1 · ✅ passed: 1 · 🗓 planned: 1"
        assert "## Problems (1)\n\n- `p:1: m`\n" in text
        heads = [line for line in lines if line.startswith("## ")]
        assert heads == ["## Problems (1)", "## 001 The thing", "## 002 Other", "## Inputs"]
        rows = [line.split(" | ")[0] for line in lines if line.startswith("| T-REQ")]
        assert rows == ["| T-REQ-001-02", "| T-REQ-001-01", "| T-REQ-002-01"]

    def test_no_problems_section_when_clean(self):
        """Only when there are some."""
        assert "## Problems" not in report.full("t", evaluation(status("passed")))


class TestSummary:
    """The short form for a step summary."""

    def test_only_the_rows_that_need_attention(self):
        """Counts, problems, and the failed, unclaimed and not run rows; not passed."""
        statuses = [status("passed"), status("unclaimed"), status("not run"), status("failed")]
        text = report.summary("t", evaluation(*statuses, problems=[Problem("p", 1, "m")]))
        assert text.startswith("### t\n\n4 requirements: 1 failed, 1 unclaimed, 1 not run, 1 passed\n")
        assert "**1 problems**" in text
        assert [line.split(" | ")[1] for line in text.splitlines() if line.startswith("| T-REQ")] == [
            "❌ failed",
            "❌ unclaimed",
            "⏸ not run",
        ]
        assert text.endswith("The full report is in the `speccheck-report` artifact.\n")

    def test_nothing_needs_attention(self):
        """No table and no problems."""
        text = report.summary("t", evaluation(status("passed")))
        assert "| ID |" not in text and "problems" not in text

    def test_it_stays_under_the_limit(self, monkeypatch: pytest.MonkeyPatch):
        """A huge summary is cut at a line, with a note, even inside a multi-byte character."""
        monkeypatch.setattr(report, "SUMMARY_LIMIT", 200)
        statuses = [status("unclaimed", text=f"Unclaimed requirement é number {n}.") for n in range(30)]
        text = report.summary("t", evaluation(*statuses))
        assert len(text.encode()) < 300
        assert text.endswith("\n\n… cut to fit the step summary; see the artifact.\n")


class TestRun:
    """Where the report goes, and the exit code."""

    def ctx(self, tmp_path: Path, **output: bool):
        """A context with one unclaimed requirement, no producers and no inputs."""
        return make_ctx(tmp_path, loaded=make_config(), specs_set=make_specs("It."), **output)

    def test_the_arguments(self):
        """Inputs, scope, `--output` and `--summary`."""
        parser = argparse.ArgumentParser()
        report.add_arguments(parser)
        args = parser.parse_args(["r", "--output", "o.md", "--summary", "s.md"])
        assert (args.inputs, args.output, args.summary, args.complete) == (["r"], "o.md", "s.md", False)

    def test_stdout_by_default_and_exit_0_on_problems(self, tmp_path: Path):
        """The full report on stdout; an unclaimed requirement doesn't fail it."""
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace()) == 0
        assert out(ctx).startswith("# speccheck requirements\n")

    def test_stdout_cant_start_a_log_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """On stdout, which may be a CI log, each line is written out (a code span keeps `##[` and `::`)."""
        monkeypatch.setattr(report, "full", lambda title, evaluation: "- `##[error]x`\n::error::y\n")
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace()) == 0
        assert out(ctx) == "- `##\\x5berror]x`\n\\x3a:error::y\n"
        assert report.run(ctx, namespace(output="r.md")) == 0
        assert (tmp_path / "r.md").read_text() == "- `##[error]x`\n::error::y\n"

    def test_a_lone_surrogate_cant_lose_the_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Text that isn't valid UTF-8 is replaced in the file rather than failing the write."""
        monkeypatch.setattr(report, "full", lambda title, evaluation: "t\ud800\n")
        assert report.run(self.ctx(tmp_path), namespace(output="r.md")) == 0
        assert (tmp_path / "r.md").read_text() == "t?\n"

    def test_output_and_summary(self, tmp_path: Path):
        """`--output` is written (folders made), `--summary` appended, and stdout has the summary line."""
        (tmp_path / "s.md").write_text("earlier step\n")
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace(output="out/r.md", summary=str(tmp_path / "s.md"))) == 0
        assert (tmp_path / "out" / "r.md").read_text().startswith("# speccheck requirements\n")
        assert (tmp_path / "s.md").read_text().startswith("earlier step\n### speccheck requirements\n")
        assert out(ctx) == "speccheck report: 1 requirement: 1 unclaimed\n"

    def test_json(self, tmp_path: Path):
        """`ok` is true even with problems; the title and the statuses."""
        ctx = self.ctx(tmp_path, json_mode=True)
        assert report.run(ctx, namespace()) == 0
        body = json.loads(out(ctx))
        assert (body["command"], body["ok"], body["title"]) == ("report", True, "speccheck requirements")
        assert [r["status"] for r in body["requirements"]] == ["unclaimed"] and len(body["problems"]) == 1
        assert body["producers"] == {"reported": [], "missing": []}
