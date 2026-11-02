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

"""specs/005-evidence-and-verify.md: `check` and `verify` on what real runs write."""

from __future__ import annotations

import pytest

from tests.requirements.conftest import CONFIG, Project

CLAIM = 'import pytest\n\n@pytest.mark.covers("T-REQ-001-01")\ndef test_it():\n    {body}\n'
"""A project test that claims T-REQ-001-01 and does `body`."""


def status(run) -> dict[str, str]:
    """ID -> status, from a `--json` run."""
    return {r["id"]: r["status"] for r in run.json()["requirements"]}


@pytest.mark.covers("SPC-REQ-005-01")
def test_one_passing_leg_is_enough(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Skipped on one leg, passed on another: passed, with both results listed."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(body='import os\n    if os.environ.get("SKIP"):\n        pytest.skip("this leg")'))
    project.ini("speccheck_producer = unit\n")
    monkeypatch.setenv("SKIP", "1")
    project.pytest("--speccheck-results=legs/a.jsonl")
    monkeypatch.delenv("SKIP")
    project.pytest("--speccheck-results=legs/b.jsonl")
    run = project.speccheck("verify", "legs", "--json")
    assert run.code == 0 and status(run) == {"T-REQ-001-01": "passed"}
    assert sorted(e["outcome"] for e in run.json()["requirements"][0]["evidence"]) == ["passed", "skipped"]


@pytest.mark.covers("SPC-REQ-005-02")
@pytest.mark.parametrize(
    ("body", "outcome"),
    [
        ("assert False", "failed"),
        ('pytest.skip("no")', "skipped"),
        ('pytest.xfail("known")', "xfailed"),
    ],
)
def test_a_claim_that_didnt_pass_fails_verify(project: Project, body: str, outcome: str):
    """Exit 1, status `failed`, and the problem lists what was seen."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(body=body))
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1
    assert (
        f"specs/001-thing.md:7: T-REQ-001-01 has no passing result: test_project.py::test_it {outcome} in unit"
        in run.err
    )


@pytest.mark.covers("SPC-REQ-005-02")
def test_a_deselected_claim_fails_verify(project: Project):
    """A claim filtered out with -k didn't run, so it proves nothing."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(body="pass") + "\ndef test_other():\n    pass\n")
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl", "-k", "test_other")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1 and "test_project.py::test_it deselected in unit" in run.err


@pytest.mark.covers("SPC-REQ-005-03")
def test_unclaimed_fails_check_and_verify_with_the_fix(project: Project):
    """The message is the marker to paste."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two. ⚠ untested\n- T-REQ-001-03: Three. (planned: step 2)")
    project.tests("def test_nothing():\n    pass\n")
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl")
    expected = 'specs/001-thing.md:7: T-REQ-001-01 is not claimed; add `@pytest.mark.covers("T-REQ-001-01")`'
    for command in ("check", "verify"):
        run = project.speccheck(command, "r.jsonl")
        assert run.code == 1 and run.err.startswith(expected)
        assert "T-REQ-001-02" not in run.err and "T-REQ-001-03" not in run.err


@pytest.mark.covers("SPC-REQ-005-04")
def test_a_producer_that_didnt_report(project: Project):
    """Its requirements are `not run`: fine for a partial verify, a failure for a complete one."""
    project.write("speccheck.toml", CONFIG + '[producers.docker]\nspecs = ["001"]\n')
    project.write(
        "speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["002"]') + '[producers.docker]\nspecs = ["001"]\n'
    )
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [])
    partial = project.speccheck("verify", "unit.jsonl", "--json")
    assert partial.code == 0 and status(partial) == {"T-REQ-001-01": "not run"}
    assert partial.json()["requirements"][0]["waiting_on"] == ["docker"]
    complete = project.speccheck("verify", "--complete", "unit.jsonl")
    assert complete.code == 1
    assert "T-REQ-001-01 was not run: nothing that reported claims it (waiting on: docker)" in complete.err


@pytest.mark.covers("SPC-REQ-005-04")
def test_an_unclaimed_requirement_waits_for_a_test_producer_that_didnt_report(project: Project):
    """Nobody claims it yet, but a test producer that may hasn't reported: `not run`, then `unclaimed` once it has."""
    project.write("speccheck.toml", CONFIG + '[producers.docker]\nspecs = ["001"]\n')
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    partial = project.speccheck("verify", "unit.jsonl", "--json")
    assert partial.code == 0 and status(partial) == {"T-REQ-001-01": "passed", "T-REQ-001-02": "not run"}
    assert partial.json()["requirements"][1]["waiting_on"] == ["docker"]
    complete = project.speccheck("verify", "--complete", "unit.jsonl")
    assert complete.code == 1 and "T-REQ-001-02 was not run" in complete.err and "(waiting on: docker)" in complete.err
    project.results("docker.jsonl", "docker", [])
    reported = project.speccheck("verify", "unit.jsonl", "docker.jsonl", "--json")
    assert reported.code == 1 and status(reported) == {"T-REQ-001-01": "passed", "T-REQ-001-02": "unclaimed"}
    assert project.speccheck("check", "unit.jsonl", "--json").json()["requirements"][1]["status"] == "unclaimed"


@pytest.mark.covers("SPC-REQ-005-05")
def test_complete_needs_every_expected_producer(project: Project):
    """Every producer, or with --workflow only the ones that list it."""
    project.write("speccheck.toml", CONFIG + '[producers.nightly]\nworkflows = ["nightly"]\n')
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "unit.jsonl")
    assert run.code == 1 and "producer `nightly` didn't report" in run.err
    assert run.err.splitlines()[-1].endswith("reported: unit; missing: nightly; 1 problem")
    assert project.speccheck("verify", "--complete", "--workflow", "ci", "unit.jsonl").code == 0


@pytest.mark.covers("SPC-REQ-005-05")
def test_complete_with_a_workflow_nobody_lists_is_an_error(project: Project):
    """A typo or a renamed workflow must not turn the missing-producer check off."""
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "--workflow", "typo", "unit.jsonl")
    assert run.code == 2 and "no producer" in run.err and "typo" in run.err
    assert project.speccheck("verify", "--workflow", "typo", "unit.jsonl").code == 0


@pytest.mark.covers("SPC-REQ-005-06")
def test_an_undeclared_producer_counts_for_nothing(project: Project):
    """A pass from a producer the config doesn't know is a problem, not evidence."""
    project.spec("- T-REQ-001-01: One.")
    project.results("stranger.jsonl", "stranger", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "stranger.jsonl", "--json")
    assert run.code == 1 and status(run) == {"T-REQ-001-01": "not run"}
    assert (
        run.json()["problems"][0]["message"] == "producer `stranger` isn't declared in speccheck.toml (declared: unit)"
    )


@pytest.mark.covers("SPC-REQ-005-07")
def test_a_stale_marker_must_go(project: Project):
    """Claimed and marked untested or planned: remove the marker."""
    project.spec("- T-REQ-001-01: One. ⚠ untested\n- T-REQ-001-02: Two. (planned: step 2)")
    project.tests('import pytest\n\n@pytest.mark.covers("T-REQ-001-01", "T-REQ-001-02")\ndef test_it():\n    pass\n')
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1
    assert "T-REQ-001-01 is claimed, so remove `⚠ untested`" in run.err
    assert "T-REQ-001-02 is claimed, so remove its `(planned: ...)`" in run.err


@pytest.mark.covers("SPC-REQ-005-08")
def test_check_on_a_collect_only_run(project: Project):
    """Outcomes don't matter to check: a failing test's claim counts, an unclaimed requirement doesn't."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.tests(CLAIM.format(body="assert False"))
    project.ini("speccheck_producer = unit\n")
    project.pytest("--collect-only", "-q", "--speccheck-results=.speccheck/collect.jsonl")
    run = project.speccheck("check", ".speccheck/")
    assert run.code == 1
    assert (
        run.err.splitlines()[-1] == "speccheck check: 2 requirements: 1 unclaimed, 1 claimed; reported: unit; 1 problem"
    )


@pytest.mark.covers("SPC-REQ-005-02")
def test_skipped_then_passing(project: Project, monkeypatch: pytest.MonkeyPatch):
    """GIVEN a claiming test WHEN it is skipped THEN verify fails, and WHEN it passes THEN verify passes."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(body='import os\n    if os.environ.get("SKIP"):\n        pytest.skip("on purpose")'))
    project.ini("speccheck_config = speccheck.toml\nspeccheck_producer = unit\n")
    monkeypatch.setenv("SKIP", "1")
    project.pytest("--speccheck-results=skip.jsonl").assert_outcomes(skipped=1)
    skipped = project.speccheck("verify", "--complete", "skip.jsonl", "--json")
    assert skipped.code == 1 and status(skipped) == {"T-REQ-001-01": "failed"}
    monkeypatch.delenv("SKIP")
    project.pytest("--speccheck-results=pass.jsonl").assert_outcomes(passed=1)
    passed = project.speccheck("verify", "--complete", "pass.jsonl", "--json")
    assert passed.code == 0 and status(passed) == {"T-REQ-001-01": "passed"}
