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

"""`speccheck report`: its sections, links and the full report, on evaluations built in memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from speccheck import evidence, results
from speccheck.actions import report
from speccheck.claims import Claim
from speccheck.specs import Problem
from tests.unit.conftest import ROOT, make_config, make_ctx, make_requirement, make_spec, make_specs, namespace, out

JOB_URL = "https://github.com/o/r/actions/runs/7/job/8"
"""A job link."""
RUN_URL = "https://github.com/o/r/actions/runs/7/attempts/1"
"""A run attempt's link."""
CI = {"job": "unit", "job_id": 8, "sha": "b" * 40, "run_url": RUN_URL, "job_url": JOB_URL}
"""A results file's CI block with a job link."""
BASE = "https://github.com/o/r"
"""This run's repository URL, the only one linked."""
FILES = BASE + "/blob/" + "c" * 40
"""Where this run's files are browsed."""
LINKS = report.Links(repository=BASE, files=FILES, root=ROOT)
"""The links a CI run allows, with the specs under ROOT."""
ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_SHA": "c" * 40}
"""The variables `LINKS` comes from."""


def source(producer: str = "unit", ci: dict | None = None, root: str | None = None) -> results.ResultsFile:
    """A results file to hang evidence on."""
    return results.ResultsFile(producer=producer, ci=ci, root=root)


def item(
    test: str = "tests/t.py::test_a",
    outcome: str = "passed",
    *,
    how: str = "it works",
    kind: str = "test",
    file: str = "tests/t.py",
    line: int = 5,
    ci: dict | None = None,
    root: str | None = "sub",
    job_name: str = "",
) -> evidence.Evidence:
    """One piece of evidence."""
    result = results.Result(test, [Claim("T-REQ-001-01", how)], outcome, file=file, line=line, kind=kind)
    return evidence.Evidence(result, source(ci=ci, root=root), how, job_name)


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


def test_heading_counts_and_spec_heading():
    """The pieces a section is named by."""
    assert report._heading(status("passed")) == "T-REQ-001-01 ✅ passed"
    assert report._counts([status("passed"), status("failed"), status("passed")]) == "❌ 1 failed, ✅ 2 passed"
    assert report._spec_heading("001", "Thing") == "001 Thing"
    assert report._spec_heading("001", "") == "001"


def test_the_specs_table():
    """A link to each spec, its number of requirements, its counts worst first."""
    one, two = make_spec(title="Spec *format*"), make_spec("002", title="Other")
    by_spec = {
        "001": [evidence.Status(make_requirement(one), "passed"), evidence.Status(make_requirement(one), "failed")],
        "002": [evidence.Status(make_requirement(two), "untested")],
    }
    assert report._specs_table(by_spec) == [
        "## Specs",
        "",
        "| Spec | Requirements | Status |",
        "|---|--:|---|",
        "| [001 Spec \\*format\\*](#001-spec-format) | 2 | ❌ 1 failed, ✅ 1 passed |",
        "| [002 Other](#002-other) | 1 | ⚠ 1 untested |",
        "",
    ]


class TestResultLine:
    """One result: outcome and job, linked."""

    def test_named_by_job_and_linked(self):
        """The job's display name when known, linked to the job on this run's repository."""
        line = report._result_line(item(ci=CI, job_name="unit [3.12]"), LINKS)
        assert line == f"- ✅ passed in [unit \\[3.12\\]]({JOB_URL})"

    def test_the_producer_without_a_name_and_no_link_outside_ci(self):
        """No job name: the producer; outside CI, or an unsafe URL: no link."""
        assert report._result_line(item(ci=CI), report.Links()) == "- ✅ passed in unit"
        unsafe = report._result_line(item(ci={"job_url": "javascript:x"}), LINKS)
        assert unsafe == "- ✅ passed in unit"

    def test_the_run_when_there_is_no_job(self):
        """The run link stands in for the job's."""
        assert report._result_line(item(ci={"run_url": RUN_URL}), LINKS).endswith(f"]({RUN_URL})")

    def test_marks(self):
        """Passed and collected are fine; anything else is a failure."""
        assert report._result_line(item(outcome="collected"), LINKS).startswith("- ☑ collected in ")
        assert report._result_line(item(outcome="skipped"), LINKS).startswith("- ❌ skipped in ")


class TestClaimantHeading:
    """A claim's heading."""

    def test_a_test_links_its_line_under_root(self):
        """The name after `::` links to its line; the file is shown from the repository's root."""
        heading = report._claimant_heading(item(), LINKS)
        assert heading == f"#### Test [`test_a`]({FILES}/sub/tests/t.py#L5) in `sub/tests/t.py`"

    def test_root_at_the_repository_root(self):
        """`.`: the file is already from the repository's root."""
        assert report._claimant_heading(item(root="."), LINKS) == (
            f"#### Test [`test_a`]({FILES}/tests/t.py#L5) in `tests/t.py`"
        )

    def test_no_root_no_link(self):
        """Without `root` the file's place in the repository isn't known, so it isn't linked."""
        assert report._claimant_heading(item(root=None), LINKS) == "#### Test `test_a` in `tests/t.py`"

    def test_outside_ci_and_unplain_paths_are_not_linked(self):
        """No commit to link to, or a path that isn't plain."""
        assert report._claimant_heading(item(), report.Links()) == "#### Test `test_a` in `sub/tests/t.py`"
        assert "](" not in report._claimant_heading(item(file="../x.py"), LINKS)
        assert "](" not in report._claimant_heading(item(file="a b.py"), LINKS)

    def test_no_file_and_no_node_part(self):
        """A result with no file and a bare test name: the name alone."""
        assert report._claimant_heading(item(test="t", file=""), LINKS) == "#### Test `t`"

    def test_a_ci_job(self):
        """A job has no file: just its name."""
        assert report._claimant_heading(item(test="publish", kind="ci"), LINKS) == "#### Job `publish`"


class TestClaims:
    """A requirement's claims."""

    def test_one_section_per_claimant_with_its_results_worst_first(self):
        """The same test in two jobs is one section; its failing job comes first."""
        passing = item(ci=CI, job_name="b job")
        failing = item(outcome="failed", ci=CI, job_name="a job")
        other = item(test="publish", kind="ci", how="the job [publishes]")
        found = evidence.Status(make_requirement(make_spec()), "passed", [passing, failing, other])
        assert report._claims(found, report.Links()) == [
            "#### Test `test_a` in `sub/tests/t.py`",
            "",
            "**How:** it works",
            "",
            "- ❌ failed in a job",
            "- ✅ passed in b job",
            "",
            "#### Job `publish`",
            "",
            "**How:** the job \\[publishes\\]",
            "",
            "- ✅ passed in unit",
            "",
        ]

    def test_no_explanation_and_many_results(self, monkeypatch: pytest.MonkeyPatch):
        """No How line without an explanation; after MAX_EVIDENCE results, the rest are a count."""
        monkeypatch.setattr(report, "MAX_EVIDENCE", 2)
        found = evidence.Status(make_requirement(make_spec()), "passed", [item(how="") for _ in range(4)])
        lines = report._claims(found, report.Links())
        assert "**How:**" not in "\n".join(lines)
        assert lines[-2:] == ["- and 2 more", ""] and lines.count("- ✅ passed in unit") == 2

    def test_a_long_explanation_is_kept(self):
        """Up to MAX_HOW characters, not a name's 200."""
        found = evidence.Status(make_requirement(make_spec()), "passed", [item(how="x" * 1000)])
        assert report._claims(found, report.Links())[2] == "**How:** " + "x" * 1000


class TestRequirement:
    """A requirement's section."""

    def test_text_and_spec_line_in_ci(self):
        """Heading, quoted text, and a link to its line in its spec, from the repository's root."""
        requirement = make_requirement(make_spec(), "It <b>works</b>.", line=12)
        lines = report._requirement(evidence.Status(requirement, "planned"), LINKS)
        assert lines == [
            "### T-REQ-001-01 🗓 planned",
            "",
            "> It \\<b\\>works\\</b\\>.",
            "",
            f"In [`specs/001-thing.md:12`]({FILES}/specs/001-thing.md#L12)",
            "",
        ]

    def test_no_spec_line_outside_ci_or_outside_the_root(self):
        """No commit, or a spec not under the repository's root: no link."""
        found = evidence.Status(make_requirement(make_spec()), "planned")
        assert not any(line.startswith("In [") for line in report._requirement(found, report.Links()))
        elsewhere = report.Links(repository=BASE, files=FILES, root=Path("/elsewhere"))
        assert not any(line.startswith("In [") for line in report._requirement(found, elsewhere))

    def test_waiting_unclaimed_and_claimed(self):
        """What it waits on, the marker to add, or its claims."""
        waiting = evidence.Status(make_requirement(make_spec()), "not run", waiting_on=["docker", "a*b"])
        assert report._requirement(waiting, report.Links())[-2:] == ["Waiting on: docker, a\\*b", ""]
        unclaimed = evidence.Status(make_requirement(make_spec()), "unclaimed")
        assert report._requirement(unclaimed, report.Links())[-2] == (
            'Not claimed: add `@pytest.mark.covers("T-REQ-001-01", "<how it proves it>")` to a test that '
            "proves it, or mark it `⚠ untested`."
        )
        claimed = evidence.Status(make_requirement(make_spec()), "passed", [item()])
        assert "#### Test `test_a` in `sub/tests/t.py`" in report._requirement(claimed, report.Links())


class TestSpec:
    """A spec's section."""

    def test_purpose_table_then_sections_in_spec_order(self):
        """Title, Purpose, a status table with attention first, then each requirement in spec order."""
        spec = make_spec(title="Thing")
        spec.purpose = "# Why: it matters."
        passed = evidence.Status(make_requirement(spec, "One."), "passed")
        failed = evidence.Status(make_requirement(spec, "Two."), "failed")
        lines = report._spec("001", [passed, failed], report.Links())
        assert lines[:9] == [
            "## 001 Thing",
            "",
            "\\# Why: it matters.",
            "",
            "| Requirement | Status |",
            "|---|---|",
            "| [T-REQ-001-02](#t-req-001-02--failed) | ❌ failed |",
            "| [T-REQ-001-01](#t-req-001-01--passed) | ✅ passed |",
            "",
        ]
        assert [line for line in lines if line.startswith("### ")] == [
            "### T-REQ-001-01 ✅ passed",
            "### T-REQ-001-02 ❌ failed",
        ]

    def test_no_purpose(self):
        """Without one, the table follows the heading."""
        lines = report._spec("001", [evidence.Status(make_requirement(make_spec()), "passed")], report.Links())
        assert lines[:3] == ["## 001 Thing", "", "| Requirement | Status |"]


class TestInputs:
    """What the report was built from."""

    def test_a_job_link_is_not_a_run_link(self):
        """A `run_url` that is really a job's URL is left out of the Runs line, though a job line may link it."""
        lines = report._inputs(evaluation(files=[source(ci={"run_url": JOB_URL, "sha": "b" * 40})]), BASE)
        assert lines[1] == "- Runs: none"
        assert report._result_line(item(ci={"job_url": JOB_URL}), LINKS).endswith(f"]({JOB_URL})")

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


class TestFull:
    """The whole report."""

    def test_the_layout(self):
        """Title, summary, counts, problems, the specs table, a section per spec, then the inputs."""
        spec = make_spec(title="The thing")
        passed = evidence.Status(make_requirement(spec, "Passes."), "passed")
        unclaimed = evidence.Status(make_requirement(spec, "Nobody."), "unclaimed")
        other = evidence.Status(make_requirement(make_spec("002", title="Other")), "planned")
        text = report.full("Title*", evaluation(passed, unclaimed, other, problems=[Problem("p", 1, "m`x")]))
        lines = text.splitlines()
        assert lines[:5] == ["# Title\\*", "", "3 requirements: 1 unclaimed, 1 passed, 1 planned", "", lines[4]]
        assert lines[4] == "❌ unclaimed: 1 · ✅ passed: 1 · 🗓 planned: 1"
        assert "## Problems (1)\n\n- `p:1: mx`\n" in text
        heads = [line for line in lines if line.startswith("## ")]
        assert heads == ["## Problems (1)", "## Specs", "## 001 The thing", "## 002 Other", "## Inputs"]
        sections = [line for line in lines if line.startswith("### ")]
        assert sections == ["### T-REQ-001-01 ✅ passed", "### T-REQ-001-02 ❌ unclaimed", "### T-REQ-002-01 🗓 planned"]

    def test_a_problem_line_is_kept_to_the_limit(self):
        """A line is cut at MAX_PROBLEM with a mark; one that fits is whole. A longest test ID plus its fix fits."""
        fits = Problem("p", 1, "m" * (report.MAX_PROBLEM - len("p:1: ")))
        over = Problem("p", 1, "m" * (report.MAX_PROBLEM - len("p:1: ") + 1))
        lines = report.full("t", evaluation(status("passed"), problems=[fits, over])).splitlines()
        shown = [line.strip("-` ") for line in lines if line.startswith("- `p:1: ")]
        assert [len(s) for s in shown] == [report.MAX_PROBLEM, report.MAX_PROBLEM] and shown[1].endswith("…")
        assert not shown[0].endswith("…")

    def test_the_problem_limit_holds_the_longest_test_id_and_its_fix(self):
        """The reason for the limit: a MAX_TEST-character ID with the longest hint is not cut short."""
        from speccheck.evidence import HINTS
        from speccheck.results import MAX_TEST

        message = (
            f"T-REQ-001-01 has no passing result: {'t' * MAX_TEST} deselected in unit; to fix: {HINTS['deselected']}"
        )
        assert len(f"specs/001-thing.md:7: {message}") <= report.MAX_PROBLEM

    def test_no_problems_section_when_clean(self):
        """Only when there are some."""
        assert "## Problems" not in report.full("t", evaluation(status("passed")))


def test_links_for():
    """In CI, this run's repository, its commit and the repository's root; outside, nothing."""
    ctx = make_ctx(ROOT, env={**ENV, "GITHUB_WORKSPACE": "/repo"})
    assert report.links_for(ctx) == report.Links(repository=BASE, files=FILES, root=Path("/repo").resolve())
    assert report.links_for(make_ctx(Path("/nowhere"))) == report.Links()


class TestRun:
    """Where the report goes, and the exit code."""

    def ctx(self, tmp_path: Path, **output: bool):
        """A context with one unclaimed requirement, no producers and no inputs."""
        return make_ctx(tmp_path, loaded=make_config(), specs_set=make_specs("It."), **output)

    def test_the_arguments(self):
        """Inputs, scope, job names and `--output`; the step summary is not the report's."""
        parser = argparse.ArgumentParser()
        report.add_arguments(parser)
        args = parser.parse_args(["r", "--output", "o.md", "--job-names", "n.json"])
        assert vars(args) == {
            "inputs": ["r"],
            "complete": False,
            "workflow": None,
            "job_names": "n.json",
            "output": "o.md",
        }

    def test_stdout_by_default_and_exit_0_on_problems(self, tmp_path: Path):
        """The full report on stdout; an unclaimed requirement doesn't fail it."""
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace()) == 0
        assert out(ctx).startswith("# speccheck requirements\n")

    def test_stdout_cant_start_a_log_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """On stdout, which may be a CI log, each line is written out (a code span keeps `##[` and `::`)."""
        monkeypatch.setattr(report, "full", lambda title, evaluation, links: "- `##[error]x`\n::error::y\n")
        ctx = self.ctx(tmp_path)
        assert report.run(ctx, namespace()) == 0
        assert out(ctx) == "- `##\\x5berror]x`\n\\x3a:error::y\n"
        assert report.run(ctx, namespace(output="r.md")) == 0
        assert (tmp_path / "r.md").read_text() == "- `##[error]x`\n::error::y\n"

    def test_a_lone_surrogate_cant_lose_the_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Text that isn't valid UTF-8 is replaced in the file rather than failing the write."""
        monkeypatch.setattr(report, "full", lambda title, evaluation, links: "t\ud800\n")
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
