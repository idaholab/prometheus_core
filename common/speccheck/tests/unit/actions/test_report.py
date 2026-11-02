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

"""`speccheck report`: rows, explanations and the full report, on evaluations built in memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from speccheck import evidence, results
from speccheck.actions import report
from speccheck.claims import Claim
from speccheck.specs import Problem
from tests.unit.conftest import make_config, make_ctx, make_requirement, make_spec, make_specs, namespace, out

JOB_URL = "https://github.com/o/r/actions/runs/7/job/8"
"""A job link."""
RUN_URL = "https://github.com/o/r/actions/runs/7/attempts/1"
"""A run attempt's link."""
CI = {"leg": "3.12", "job": "unit", "sha": "b" * 40, "run_url": RUN_URL, "job_url": JOB_URL}
"""A results file's CI block with a job link."""
BASE = "https://github.com/o/r"
"""This run's repository URL, the only one linked."""
ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""The variables `BASE` comes from."""


def source(producer: str = "unit", ci: dict | None = None) -> results.ResultsFile:
    """A results file to hang evidence on."""
    return results.ResultsFile(producer=producer, ci=ci)


def status(
    name: str, *found: tuple[str, str], text: str = "It.", line: int = 0, ci: dict | None = None, kind: str = "test"
) -> evidence.Status:
    """A status of a fresh requirement, with `(test, outcome)` evidence from `unit`."""
    requirement = make_requirement(make_spec(), text, line=line)
    from_file = source(ci=ci)
    items = [
        evidence.Evidence(
            results.Result(t, [Claim(requirement.id, f"{t} proves it")], o, kind=kind), from_file, f"{t} proves it"
        )
        for t, o in found
    ]
    return evidence.Status(requirement, name, items)


def evaluation(
    *statuses: evidence.Status, problems=(), files=(), reported=("unit",), missing=()
) -> evidence.Evaluation:
    """An evaluation of the given statuses."""
    return evidence.Evaluation(list(statuses), list(problems), list(reported), list(missing), list(files))


class TestEvidenceCell:
    """The Evidence column."""

    def test_a_test_with_a_job_link(self):
        """Test, outcome, producer and leg, then the link."""
        cell = report._evidence_cell(status("passed", ("tests/t.py::test_a", "passed"), ci=CI), BASE)
        assert cell == rf"test `tests/t.py::test_a` passed in unit 3\.12 ([job]({JOB_URL}))"

    def test_the_run_when_there_is_no_job_and_none_when_unsafe(self):
        """The run link stands in for the job's; an unsafe one is dropped."""
        cell = report._evidence_cell(status("passed", ("t", "passed"), ci={"run_url": RUN_URL}), BASE)
        assert cell.endswith(f"([job]({RUN_URL}))")
        assert "[job]" not in report._evidence_cell(
            status("passed", ("t", "passed"), ci={"job_url": "javascript:x"}), BASE
        )

    def test_a_ci_job_and_no_leg(self):
        """A CI job's result says `job`; no leg, no trailing space."""
        assert (
            report._evidence_cell(status("passed", ("publish", "passed"), kind="ci"), BASE)
            == "job `publish` passed in unit"
        )

    def test_a_backtick_cant_close_the_code_span(self):
        """A backtick in the test name is dropped, and nothing is left in its place."""
        assert report._evidence_cell(status("passed", ("a`b", "passed")), BASE) == "test `ab` passed in unit"

    def test_many_results_are_counted(self, monkeypatch: pytest.MonkeyPatch):
        """After MAX_EVIDENCE results, the rest are a count."""
        monkeypatch.setattr(report, "MAX_EVIDENCE", 2)
        cell = report._evidence_cell(status("passed", *[(f"t{n}", "passed") for n in range(4)]), BASE)
        assert cell.count("<br>") == 2 and cell.endswith("<br>and 2 more")

    def test_waiting_and_nothing(self):
        """Without evidence: who it waits on, else a dash."""
        waiting = status("not run")
        waiting.waiting_on = ["unit", "a|b"]
        assert report._evidence_cell(waiting, BASE) == r"waiting on unit, a\|b"
        assert report._evidence_cell(status("unclaimed"), BASE) == "—"


def test_a_row_stays_four_columns():
    """ID, icon and status, escaped text, evidence."""
    row = report._row(status("failed", ("t|x", "skipped"), text="Pipes | and <b>"), BASE)
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
        lines = report._inputs(evaluation(files=files, missing=["docker"]), BASE)
        assert lines == [
            "- Commit: bbbbbbbbbbbb",
            f"- Runs: [7/attempts/1]({RUN_URL})",
            "- Producers reported: unit",
            "- Producers missing: docker",
        ]

    def test_outside_ci(self):
        """No CI block and nobody reported."""
        assert report._inputs(evaluation(files=[source()], reported=[]), "") == [
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


class TestHows:
    """Below a spec's table, how each claim proves its requirement."""

    def test_each_claim_once_with_its_explanation(self):
        """A test, a CI job, and the same test in a second leg listed once; text is escaped, a test name is code."""
        failed = status("failed", ("t[x]", "failed"), ("t[x]", "failed"))
        passed = status("passed", ("publish", "passed"), kind="ci")
        assert report._hows([failed, passed]) == [
            "How each claim proves its requirement:",
            "",
            "- **T-REQ-001-01**, test `t[x]`: t\\[x\\] proves it",
            "- **T-REQ-001-01**, job `publish`: publish proves it",
            "",
        ]

    def test_nothing_without_explanations(self):
        """No evidence, or evidence with no explanation: no section."""
        assert report._hows([status("unclaimed")]) == []
        bare = status("passed")
        bare.evidence = [evidence.Evidence(results.Result("t", [], "passed"), source())]
        assert report._hows([bare]) == []

    def test_a_long_explanation_is_kept(self):
        """Up to MAX_HOW characters, not the cell's 200."""
        long = status("passed")
        long.evidence = [evidence.Evidence(results.Result("t", [], "passed"), source(), "x" * 1000)]
        assert report._hows([long])[2].endswith(": " + "x" * 1000)

    def test_the_full_report_puts_them_under_the_table(self):
        """After the table's blank line, before the next heading."""
        text = report.full("t", evaluation(status("passed", ("t", "passed"))))
        assert (
            "|\n\nHow each claim proves its requirement:\n\n- **T-REQ-001-01**, test `t`: t proves it\n\n## Inputs"
            in text
        )


class TestRun:
    """Where the report goes, and the exit code."""

    def ctx(self, tmp_path: Path, **output: bool):
        """A context with one unclaimed requirement, no producers and no inputs."""
        return make_ctx(tmp_path, loaded=make_config(), specs_set=make_specs("It."), **output)

    def test_the_arguments(self):
        """Inputs, scope and `--output`; the step summary is not the report's."""
        parser = argparse.ArgumentParser()
        report.add_arguments(parser)
        args = parser.parse_args(["r", "--output", "o.md"])
        assert vars(args) == {"inputs": ["r"], "complete": False, "workflow": None, "output": "o.md"}

    def test_stdout_by_default_and_exit_0_on_problems(self, tmp_path: Path):
        """The full report on stdout; an unclaimed requirement doesn't fail it."""
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace()) == 0
        assert out(ctx).startswith("# speccheck requirements\n")

    def test_stdout_cant_start_a_log_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """On stdout, which may be a CI log, each line is written out (a code span keeps `##[` and `::`)."""
        monkeypatch.setattr(report, "full", lambda title, evaluation, base: "- `##[error]x`\n::error::y\n")
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace()) == 0
        assert out(ctx) == "- `##\\x5berror]x`\n\\x3a:error::y\n"
        assert report.run(ctx, namespace(output="r.md")) == 0
        assert (tmp_path / "r.md").read_text() == "- `##[error]x`\n::error::y\n"

    def test_a_lone_surrogate_cant_lose_the_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Text that isn't valid UTF-8 is replaced in the file rather than failing the write."""
        monkeypatch.setattr(report, "full", lambda title, evaluation, base: "t\ud800\n")
        assert report.run(self.ctx(tmp_path), namespace(output="r.md")) == 0
        assert (tmp_path / "r.md").read_text() == "t?\n"

    def test_output(self, tmp_path: Path):
        """`--output` is written over what was there (folders made), and stdout has the summary line."""
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "r.md").write_text("an old report\n")
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace(output="out/r.md")) == 0
        assert (tmp_path / "out" / "r.md").read_text().startswith("# speccheck requirements\n")
        assert out(ctx) == "speccheck report: 1 requirement: 1 unclaimed\n"
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace(output=str(tmp_path / "new" / "r.md"))) == 0
        assert (tmp_path / "new" / "r.md").is_file()

    def test_json(self, tmp_path: Path):
        """`ok` is true even with problems; the title and the statuses."""
        ctx = self.ctx(tmp_path, json_mode=True)
        assert report.run(ctx, namespace()) == 0
        body = json.loads(out(ctx))
        assert (body["command"], body["ok"], body["title"]) == ("report", True, "speccheck requirements")
        assert [r["status"] for r in body["requirements"]] == ["unclaimed"] and len(body["problems"]) == 1
        assert body["producers"] == {"reported": [], "missing": []}
