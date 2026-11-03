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

from tests.requirements.conftest import CONFIG, INDEX, Project, spec

CLAIM = 'import pytest\n\n@pytest.mark.covers("T-REQ-001-01", "the inner test")\n{marks}def test_it():\n    {body}\n'
"""A project test that claims T-REQ-001-01, carries `marks` (whole decorator lines), and does `body`."""


def status(run) -> dict[str, str]:
    """ID -> status, from a `--json` run."""
    return {r["id"]: r["status"] for r in run.json()["requirements"]}


@pytest.mark.covers(
    "SPC-REQ-005-01",
    "the same claim skipped in one leg's file and passed in another's makes verify pass, listing both results",
)
def test_one_passing_leg_is_enough(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Skipped on one leg, passed on another: passed, with both results listed."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(
        CLAIM.format(marks="", body='import os\n    if os.environ.get("SKIP"):\n        pytest.skip("this leg")')
    )
    project.ini("speccheck_producer = unit\n")
    monkeypatch.setenv("SKIP", "1")
    project.pytest("--speccheck-results=legs/a.jsonl")
    monkeypatch.delenv("SKIP")
    project.pytest("--speccheck-results=legs/b.jsonl")
    run = project.speccheck("verify", "legs", "--json")
    assert run.code == 0 and status(run) == {"T-REQ-001-01": "passed"}
    assert sorted(e["outcome"] for e in run.json()["requirements"][0]["evidence"]) == ["passed", "skipped"]


@pytest.mark.parametrize(
    ("marks", "body", "outcome"),
    [
        pytest.param(
            "",
            "assert False",
            "failed",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02",
                "an inner claiming test that fails its assert makes verify exit 1, listing it as failed with a hint",
            ),
            id="failed",
        ),
        pytest.param(
            "",
            'pytest.skip("no")',
            "skipped",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02", "an inner claiming test that calls pytest.skip is listed as skipped and fails verify"
            ),
            id="skipped",
        ),
        pytest.param(
            "",
            'pytest.xfail("known")',
            "xfailed",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02", "an inner claiming test that calls pytest.xfail is listed as xfailed and fails verify"
            ),
            id="xfailed",
        ),
        pytest.param(
            "@pytest.mark.xfail(reason='known')\n",
            "pass",
            "xpassed",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02",
                "an inner claiming test marked xfail that passes anyway is listed as xpassed and fails verify",
            ),
            id="xpassed",
        ),
        pytest.param(
            "",
            "raise RuntimeError('boom')",
            "failed",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02",
                "an inner claiming test that raises an exception in its body is listed as failed, not passed",
            ),
            id="raises",
        ),
    ],
)
def test_a_claim_that_didnt_pass_fails_verify(project: Project, marks: str, body: str, outcome: str):
    """Exit 1, status `failed`, and the problem lists what was seen."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(marks=marks, body=body))
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1
    assert (
        f"specs/001-thing.md:7: T-REQ-001-01 has no passing result: test_project.py::test_it {outcome} in unit"
        in run.err
    )
    hint = {
        "failed": "fix the test or the code it checks",
        "skipped": "make the test run here, or claim the requirement from a job where it runs",
        "xfailed": "an expected failure proves nothing; fix it and remove the xfail",
        "xpassed": "an unexpected pass isn't a pass; remove the xfail",
    }[outcome]
    assert f"; to fix: {hint}" in run.err


@pytest.mark.covers(
    "SPC-REQ-005-02",
    "a claiming test left out with -k is listed as deselected with the hint to drop the filter, and verify exits 1",
)
def test_a_deselected_claim_fails_verify(project: Project):
    """A claim filtered out with -k didn't run, so it proves nothing."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(marks="", body="pass") + "\ndef test_other():\n    pass\n")
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl", "-k", "test_other")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1 and "test_project.py::test_it deselected in unit" in run.err
    assert "; to fix: run it: drop the `-k`/`-m` filter or the test's path argument that left it out" in run.err


@pytest.mark.covers(
    "SPC-REQ-005-03",
    "check and verify both fail on an unclaimed requirement with the marker to paste, and skip the untested and planned ones",
)
def test_unclaimed_fails_check_and_verify_with_the_fix(project: Project):
    """The message is the marker to paste."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two. ⚠ untested\n- T-REQ-001-03: Three. (planned: step 2)")
    project.tests("def test_nothing():\n    pass\n")
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl")
    expected = (
        'specs/001-thing.md:7: T-REQ-001-01 is not claimed; add `@pytest.mark.covers("T-REQ-001-01", '
        '"<how it proves it>")`'
    )
    for command in ("check", "verify"):
        run = project.speccheck(command, "r.jsonl")
        assert run.code == 1 and run.err.startswith(expected)
        assert "T-REQ-001-02" not in run.err and "T-REQ-001-03" not in run.err


@pytest.mark.covers(
    "SPC-REQ-005-04",
    "a requirement of spec 001, which producer docker may claim and unit may not, with no claim from anyone, is not run waiting on docker, and fails verify only with --complete",
)
def test_a_producer_that_didnt_report(project: Project):
    """Its requirements are `not run`: fine for a partial verify, a failure for a complete one."""
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


@pytest.mark.covers(
    "SPC-REQ-005-04",
    "an unclaimed requirement is not run while docker hasn't reported, and turns unclaimed once docker's empty file arrives",
)
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


@pytest.mark.covers(
    "SPC-REQ-005-05",
    "--complete fails on producer nightly that didn't report, and --workflow ci leaves it out of the expected producers",
)
def test_complete_needs_every_expected_producer(project: Project):
    """Every producer, or with --workflow only the ones that list it."""
    project.write("speccheck.toml", CONFIG + '[producers.nightly]\nworkflows = ["nightly"]\n')
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "unit.jsonl")
    assert run.code == 1 and "producer `nightly` didn't report" in run.err
    assert run.err.splitlines()[-1].endswith("reported: unit; missing: nightly; 1 problem")
    assert project.speccheck("verify", "--complete", "--workflow", "ci", "unit.jsonl").code == 0


@pytest.mark.covers(
    "SPC-REQ-005-05",
    "--complete --workflow typo exits 2 saying no producer lists that workflow, so a typo can't switch the missing-producer check off",
)
def test_complete_with_a_workflow_nobody_lists_is_an_error(project: Project):
    """A typo or a renamed workflow must not turn the missing-producer check off.

    Without `--complete` the workflow isn't used at all, so the same typo exits 0 (asserted last as a control).
    """
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "--workflow", "typo", "unit.jsonl")
    assert run.code == 2
    assert "--workflow typo: no producer in speccheck.toml lists that workflow (workflows listed: ci)" in run.err
    assert project.speccheck("verify", "--workflow", "typo", "unit.jsonl").code == 0


@pytest.mark.covers(
    "SPC-REQ-005-06",
    "a passing result from producer stranger is a problem naming the declared producers, and the requirement stays not run",
)
def test_an_undeclared_producer_counts_for_nothing(project: Project):
    """A pass from a producer the config doesn't know is a problem, not evidence."""
    project.spec("- T-REQ-001-01: One.")
    project.results("stranger.jsonl", "stranger", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "stranger.jsonl", "--json")
    assert run.code == 1 and status(run) == {"T-REQ-001-01": "not run"}
    assert (
        run.json()["problems"][0]["message"] == "producer `stranger` isn't declared in speccheck.toml (declared: unit)"
    )


@pytest.mark.covers(
    "SPC-REQ-005-07",
    "an inner test claiming an untested and a planned requirement makes verify ask to remove each marker",
)
def test_a_stale_marker_must_go(project: Project):
    """Claimed and marked untested or planned: remove the marker."""
    project.spec("- T-REQ-001-01: One. ⚠ untested\n- T-REQ-001-02: Two. (planned: step 2)")
    project.tests(
        'import pytest\n\n@pytest.mark.covers("T-REQ-001-01", "one")\n@pytest.mark.covers("T-REQ-001-02", "two")\n'
        "def test_it():\n    pass\n"
    )
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1
    assert "T-REQ-001-01 is claimed, so remove `⚠ untested`" in run.err
    assert "T-REQ-001-02 is claimed, so remove its `(planned: ...)`" in run.err


@pytest.mark.covers(
    "SPC-REQ-005-08",
    "check on a collect-only run (outcome collected) of a test whose body would fail counts its claim as claimed, and fails only on the unclaimed requirement",
)
def test_check_on_a_collect_only_run(project: Project):
    """Outcomes don't matter to check: a collected test's claim counts (its body never runs), an unclaimed requirement doesn't."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.tests(CLAIM.format(marks="", body="assert False"))
    project.ini("speccheck_producer = unit\n")
    project.pytest("--collect-only", "-q", "--speccheck-results=.speccheck/collect.jsonl")
    run = project.speccheck("check", ".speccheck/")
    assert run.code == 1
    assert (
        run.err.splitlines()[-1] == "speccheck check: 2 requirements: 1 unclaimed, 1 claimed; reported: unit; 1 problem"
    )


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(
            outcome,
            marks=pytest.mark.covers(
                "SPC-REQ-005-08",
                f"check on a results file that records the claim as {outcome} calls it claimed and fails only on the unclaimed requirement, while verify calls it passed only for a passed outcome",
            ),
        )
        for outcome in ("passed", "failed", "error", "skipped", "xfailed", "xpassed", "deselected", "collected")
    ],
)
def test_check_ignores_the_outcome_of_a_claim(project: Project, outcome: str):
    """Results files written with each outcome: `claimed` for every one, so no outcome is looked at."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("r.jsonl", "unit", [("tests/t.py::test_one", ["T-REQ-001-01"], outcome)])
    run = project.speccheck("check", "r.jsonl", "--json")
    assert status(run) == {"T-REQ-001-01": "claimed", "T-REQ-001-02": "unclaimed"}
    assert [p["code"] for p in run.json()["problems"]] == ["unclaimed"]
    assert run.code == 1
    # The same file under verify is where the outcome counts
    verified = status(project.speccheck("verify", "r.jsonl", "--json"))["T-REQ-001-01"]
    assert (verified == "passed") is (outcome == "passed"), verified


@pytest.mark.covers(
    "SPC-REQ-005-02",
    "the same claiming test fails verify --complete when skipped through an environment variable, and passes once it runs",
)
def test_skipped_then_passing(project: Project, monkeypatch: pytest.MonkeyPatch):
    """GIVEN a claiming test WHEN it is skipped THEN verify fails, and WHEN it passes THEN verify passes."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(
        CLAIM.format(marks="", body='import os\n    if os.environ.get("SKIP"):\n        pytest.skip("on purpose")')
    )
    project.ini("speccheck_config = speccheck.toml\nspeccheck_producer = unit\n")
    monkeypatch.setenv("SKIP", "1")
    project.pytest("--speccheck-results=skip.jsonl").assert_outcomes(skipped=1)
    skipped = project.speccheck("verify", "--complete", "skip.jsonl", "--json")
    assert skipped.code == 1 and status(skipped) == {"T-REQ-001-01": "failed"}
    monkeypatch.delenv("SKIP")
    project.pytest("--speccheck-results=pass.jsonl").assert_outcomes(passed=1)
    passed = project.speccheck("verify", "--complete", "pass.jsonl", "--json")
    assert passed.code == 0 and status(passed) == {"T-REQ-001-01": "passed"}


@pytest.mark.covers(
    "SPC-REQ-005-09",
    "verify on an empty folder, with and without --complete, and with no argument, exits 1 saying nothing is proven",
)
def test_verify_with_no_results_files_fails(project: Project):
    """An empty folder, a folder with no results, and no argument at all: exit 1 and a problem, with or without --complete."""
    project.spec("- T-REQ-001-01: One.")
    project.write("empty/note.txt", "not a results file")
    for argv in (["empty"], ["--complete", "empty"], []):
        run = project.speccheck("verify", *argv, "--json")
        messages = [p["message"] for p in run.json()["problems"]]
        assert run.code == 1 and run.json()["ok"] is False, argv
        assert any("no results files were read" in m and "nothing is proven" in m for m in messages), argv


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "two results files from different producers giving one explanation for two tests make check and verify fail, naming both tests",
)
def test_an_explanation_is_given_once_across_results_files(project: Project):
    """A repeat no single pytest session could see: two producers' tests, in two files."""
    project.write("speccheck.toml", CONFIG + "[producers.docker]\n")
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    header = '{"schema": "speccheck-results/1", "producer": "%s"}\n'
    line = '{"test": "%s", "covers": [{"id": "%s", "how": "%s"}], "outcome": "passed"}\n'
    project.write("u.jsonl", header % "unit" + line % ("tests/a.py::test_a", "T-REQ-001-01", "the file is written"))
    project.write("d.jsonl", header % "docker" + line % ("tests/b.py::test_b", "T-REQ-001-02", "The file is WRITTEN."))
    for command in ("check", "verify"):
        run = project.speccheck(command, "d.jsonl", "u.jsonl", "--json")
        assert run.code == 1
        # Files are read in the order given, so the later one, u.jsonl, holds the repeat
        assert [p["message"] for p in run.json()["problems"] if p["code"] == "how-duplicate"] == [
            "tests/a.py::test_a gives the same explanation for T-REQ-001-01 as tests/b.py::test_b does for "
            "T-REQ-001-02; each claim says how its own test proves its requirement"
        ]


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "one test's claim in three legs' results files and a CI job's result repeating its config entry count as one claim each, so verify passes",
)
def test_the_same_claim_in_several_files_is_not_a_repeat(project: Project):
    """Legs, producers and a job's own result repeat a claim; that is the same claim, not a copy."""
    project.write(
        "speccheck.toml",
        CONFIG + '[producers.docker]\n[ci.publish]\ncovers = { "T-REQ-001-02" = "the job publishes" }\n',
    )
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    for name, producer in (("a.jsonl", "unit"), ("b.jsonl", "unit"), ("c.jsonl", "docker")):
        project.results(name, producer, [("tests/a.py::test_a", ["T-REQ-001-01"], "passed")])
    header = '{"schema": "speccheck-results/1", "producer": "publish"}\n'
    job = '{"test": "publish", "kind": "ci", "covers": [{"id": "T-REQ-001-02", "how": "the job publishes"}], "outcome": "passed"}\n'
    project.write("p.jsonl", header + job)
    run = project.speccheck("verify", "a.jsonl", "b.jsonl", "c.jsonl", "p.jsonl", "--json")
    assert (run.code, run.json()["problems"]) == (0, [])


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "a test whose explanation repeats a CI job's config entry makes check fail, and the problem names the job",
)
def test_a_test_cant_repeat_a_ci_jobs_explanation(project: Project):
    """The config's claims are read first, so the test is the one reported."""
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = { "T-REQ-001-02" = "the image is published" }\n')
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = (
        '{"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "the image is published"}], "outcome": "collected"}\n'
    )
    project.write("u.jsonl", header + line)
    run = project.speccheck("check", "u.jsonl")
    assert run.code == 1
    assert "t gives the same explanation for T-REQ-001-01 as `ci.publish` does for T-REQ-001-02" in run.err


@pytest.mark.covers(
    "SPC-REQ-005-11",
    "a results file claiming malformed, unknown, retired and disallowed IDs gets four claim-invalid problems from check and verify, and none of them counts: every requirement is left with no evidence",
)
def test_a_bad_claimed_id_in_a_results_file_counts_for_nothing(project: Project):
    """Written by `record` or another language, so pytest never checked the IDs."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["001"]'))
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Retired.")
    project.write("specs/002-other.md", spec("- T-REQ-002-01: Other.", number="002", title="Other"))
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    ids = ["T-REQ-1-1", "T-REQ-001-09", "T-REQ-001-02", "T-REQ-002-01"]
    lines = "".join(
        f'{{"test": "t{n}", "covers": [{{"id": "{id_}", "how": "test t{n} proves it"}}], "outcome": "passed"}}\n'
        for n, id_ in enumerate(ids)
    )
    project.write("u.jsonl", header + lines)
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert run.code == 1
        invalid = [p for p in run.json()["problems"] if p["code"] == "claim-invalid"]
        assert len(invalid) == 4, run.json()["problems"]
        assert status(run)["T-REQ-001-01"] == "unclaimed"
        assert [r["id"] for r in run.json()["requirements"] if r["evidence"]] == [], command


@pytest.mark.covers(
    "SPC-REQ-005-11",
    "a passing claim of a retired, unknown, malformed or disallowed ID leaves its real target unclaimed or retired with no evidence, and each problem carries the 003-13 fix",
)
def test_a_refused_claim_has_no_evidence_and_says_how_to_fix_it(project: Project):
    """The claim passed, so any evidence or `passed` status would show the claim counted."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["001"]'))
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: Retired.\n- T-REQ-001-02: Live.")
    project.write("specs/002-other.md", spec("- T-REQ-002-01: Other.", number="002", title="Other"))
    project.results(
        "u.jsonl",
        "unit",
        [
            ("t0", ["T-REQ-1-1"], "passed"),
            ("t1", ["T-REQ-001-09"], "passed"),
            ("t2", ["T-REQ-001-01"], "passed"),
            ("t3", ["T-REQ-002-01"], "passed"),
        ],
    )
    fixes = {
        "T-REQ-1-1": "is not an ID of this folder; IDs read like `T-REQ-",
        "T-REQ-001-09": "isn't in any spec; check the number, or add it to spec 001",
        "T-REQ-001-01": "is retired; claim what replaced it",
        "T-REQ-002-01": "which producer `unit` may not claim; add it to `producers.unit.specs`",
    }
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        by_id = {r["id"]: r for r in run.json()["requirements"]}
        assert by_id["T-REQ-001-01"]["status"] == "retired" and by_id["T-REQ-001-01"]["evidence"] == []
        assert by_id["T-REQ-002-01"]["status"] == "unclaimed" and by_id["T-REQ-002-01"]["evidence"] == []
        assert by_id["T-REQ-001-02"]["status"] == "unclaimed"
        assert set(by_id) == {"T-REQ-001-01", "T-REQ-001-02", "T-REQ-002-01"}
        messages = [p["message"] for p in run.json()["problems"] if p["code"] == "claim-invalid"]
        assert len(messages) == 4, messages
        for id_, fix in fixes.items():
            assert any(id_ in m and fix in m for m in messages), (command, id_, messages)


@pytest.mark.covers(
    "SPC-REQ-005-11",
    "a claim by a producer that may not claim spec 002, the only claim on its requirement and a passing one, leaves that requirement unclaimed",
)
def test_a_disallowed_claim_is_not_the_requirements_proof(project: Project):
    """If the claim counted, the requirement would be `passed`; the only evidence is the refused claim."""
    project.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["001"]'))
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: One.")
    project.write("specs/002-other.md", spec("- T-REQ-002-01: Other.", number="002", title="Other"))
    project.results("u.jsonl", "unit", [("a", ["T-REQ-001-01"], "passed"), ("b", ["T-REQ-002-01"], "passed")])
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert status(run) == {
            "T-REQ-001-01": "claimed" if command == "check" else "passed",
            "T-REQ-002-01": "unclaimed",
        }
        assert run.code == 1


@pytest.mark.covers(
    "SPC-REQ-005-11",
    "a [ci.publish] entry claiming an ID that no spec has gets a config-claim-invalid problem from check and verify",
)
def test_a_ci_job_claiming_an_unknown_id_counts_for_nothing(project: Project):
    """The job's claims are in the config, so they are checked there, whether or not the job reported."""
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = { "T-REQ-001-09" = "the image is published" }\n')
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert run.code == 1
        invalid = [p for p in run.json()["problems"] if p["code"] == "config-claim-invalid"]
        assert len(invalid) == 1 and "T-REQ-001-09" in invalid[0]["message"], run.json()["problems"]


def ci_config(covers: dict[str, str] | None = None, *, docker: bool = True) -> str:
    """The default config, a `docker` test producer, and a CI job `publish` that claims each `{ID: how}` given."""
    entries = "".join(f'"{id_}" = "{how}"\n' for id_, how in (covers or {}).items())
    ci = f"[ci.publish.covers]\n{entries}" if entries else ""
    return CONFIG + ("[producers.docker]\n" if docker else "") + ci


@pytest.mark.covers(
    "SPC-REQ-005-01",
    "a failed result from producer unit and a passed one from producer docker make the requirement passed, with both results as evidence",
)
def test_a_pass_in_another_producer_is_enough(project: Project):
    """Any producer: one's failure doesn't outvote another's pass."""
    project.write("speccheck.toml", ci_config())
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "failed")])
    project.results("d.jsonl", "docker", [("tests/b.py::test_b", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "u.jsonl", "d.jsonl", "--json")
    assert run.code == 0 and status(run) == {"T-REQ-001-01": "passed"}
    evidence = run.json()["requirements"][0]["evidence"]
    assert sorted(e["outcome"] for e in evidence) == ["failed", "passed"]


@pytest.mark.covers(
    "SPC-REQ-005-01",
    "one failed and one passed claiming test in the same producer's single file make the requirement passed",
)
def test_a_pass_beside_a_failure_in_one_file_is_enough(project: Project):
    """Any result: a failing test next to a passing one doesn't fail the requirement."""
    project.spec("- T-REQ-001-01: One.")
    project.results(
        "u.jsonl",
        "unit",
        [("tests/a.py::test_a", ["T-REQ-001-01"], "failed"), ("tests/a.py::test_b", ["T-REQ-001-01"], "passed")],
    )
    run = project.speccheck("verify", "u.jsonl", "--json")
    assert run.code == 0 and status(run) == {"T-REQ-001-01": "passed"}


@pytest.mark.covers(
    "SPC-REQ-005-01",
    "a CI job's passed result beside a failing test makes the requirement passed, as does a passing test beside the job's failed result, while two failures stay failed",
)
def test_a_passing_ci_job_counts_beside_a_failing_test(project: Project):
    """A job's result is a result like a test's, in either direction."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-01": "the job publishes the image"}))
    project.spec("- T-REQ-001-01: One.")
    project.results("fail.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "failed")])
    project.results("ok.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "passed")])
    project.results("job-ok.jsonl", "publish", [("publish", ["T-REQ-001-01"], "passed")], kind="ci")
    project.results("job-fail.jsonl", "publish", [("publish", ["T-REQ-001-01"], "failed")], kind="ci")
    assert status(project.speccheck("verify", "fail.jsonl", "job-ok.jsonl", "--json")) == {"T-REQ-001-01": "passed"}
    assert status(project.speccheck("verify", "ok.jsonl", "job-fail.jsonl", "--json")) == {"T-REQ-001-01": "passed"}
    assert status(project.speccheck("verify", "fail.jsonl", "job-fail.jsonl", "--json")) == {"T-REQ-001-01": "failed"}


@pytest.mark.parametrize(
    ("outcome", "hint"),
    [
        pytest.param(
            "error",
            "fix the setup or teardown that raised",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02",
                "a claiming result recorded as error makes verify exit 1, listing it as error with the setup-or-teardown hint",
            ),
        ),
        pytest.param(
            "collected",
            "the run ended before it ran",
            marks=pytest.mark.covers(
                "SPC-REQ-005-02",
                "a claiming result recorded as collected in a verify run makes it exit 1, listing it as collected with the run-ended hint",
            ),
        ),
    ],
)
def test_error_and_collected_results_fail_verify_with_their_hint(project: Project, outcome: str, hint: str):
    """The results file says the outcome, so it is exactly the one under test."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], outcome)])
    run = project.speccheck("verify", "u.jsonl")
    assert run.code == 1
    assert f"T-REQ-001-01 has no passing result: tests/a.py::test_a {outcome} in unit; to fix: {hint}" in run.err


@pytest.mark.covers(
    "SPC-REQ-005-02",
    "a failed and a skipped result on one requirement are both listed in one problem, with a hint for each outcome",
)
def test_several_failing_results_are_listed_together(project: Project):
    """One problem, both results, both hints."""
    project.spec("- T-REQ-001-01: One.")
    project.results(
        "u.jsonl",
        "unit",
        [("tests/a.py::test_a", ["T-REQ-001-01"], "failed"), ("tests/a.py::test_b", ["T-REQ-001-01"], "skipped")],
    )
    run = project.speccheck("verify", "u.jsonl")
    failing = [line for line in run.err.splitlines() if "has no passing result" in line]
    assert len(failing) == 1
    assert (
        "T-REQ-001-01 has no passing result: tests/a.py::test_a failed in unit; tests/a.py::test_b skipped in unit; "
        "to fix: fix the test or the code it checks; or make the test run here" in failing[0]
    )


@pytest.mark.covers(
    "SPC-REQ-005-02",
    "seven failing results on one requirement list the first five and say '(and 2 more)'",
)
def test_a_long_list_of_failing_results_is_cut(project: Project):
    """The problem stays one readable line: five results, then the count of the rest."""
    project.spec("- T-REQ-001-01: One.")
    tests = [(f"tests/a.py::test_{n}", ["T-REQ-001-01"], "failed") for n in range(7)]
    project.results("u.jsonl", "unit", tests)
    run = project.speccheck("verify", "u.jsonl")
    line = next(line for line in run.err.splitlines() if "has no passing result" in line)
    assert all(f"tests/a.py::test_{n} failed in unit" in line for n in range(5))
    assert "test_5" not in line and "test_6" not in line
    assert "(and 2 more)" in line


@pytest.mark.covers(
    "SPC-REQ-005-02",
    "a CI job's failed result for the only claim on a requirement fails verify, naming the job and its outcome",
)
def test_a_failing_ci_job_fails_verify(project: Project):
    """The job claims it in the config and reports it failed."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-01": "the job publishes the image"}))
    project.spec("- T-REQ-001-01: One.")
    project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01"], "failed")], kind="ci")
    run = project.speccheck("verify", "p.jsonl", "--json")
    assert run.code == 1 and status(run) == {"T-REQ-001-01": "failed"}
    message = run.json()["problems"][0]["message"]
    assert message.startswith("T-REQ-001-01 has no passing result: publish failed in publish")


@pytest.mark.covers(
    "SPC-REQ-005-03",
    "a retired requirement that nothing claims has status retired, and check and verify exit 0",
)
def test_a_retired_requirement_needs_no_claim(project: Project):
    """Retired is exempt, like untested and planned."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Retired. Gone.")
    project.results("u.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "passed")])
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert run.code == 0 and run.json()["problems"] == [], command
        assert status(run)["T-REQ-001-02"] == "retired"


@pytest.mark.covers(
    "SPC-REQ-005-03",
    "an untested and a planned requirement that nothing claims get those statuses, not unclaimed, and check and verify exit 0",
)
def test_untested_and_planned_are_exempt_by_status(project: Project):
    """The statuses themselves, not just the missing message."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two. ⚠ untested\n- T-REQ-001-03: Three. (planned: step 2)")
    project.results("u.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "passed")])
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert run.code == 0, run.err
        assert status(run)["T-REQ-001-02"] == "untested" and status(run)["T-REQ-001-03"] == "planned"


@pytest.mark.covers(
    "SPC-REQ-005-04",
    "a requirement claimed only by CI job publish, whose results file is absent, is not run waiting on publish, fails only with --complete, and is passed once publish reports",
)
def test_a_ci_job_that_didnt_report_leaves_its_claim_not_run(project: Project):
    """The job claims it in the config; no file from the job means we can't say."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-01": "the job publishes the image"}, docker=False))
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [])
    partial = project.speccheck("verify", "u.jsonl", "--json")
    assert partial.code == 0 and status(partial) == {"T-REQ-001-01": "not run"}
    assert partial.json()["requirements"][0]["waiting_on"] == ["publish"]
    complete = project.speccheck("verify", "--complete", "u.jsonl")
    assert complete.code == 1
    assert "T-REQ-001-01 was not run: nothing that reported claims it (waiting on: publish)" in complete.err
    project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01"], "passed")], kind="ci")
    assert status(project.speccheck("verify", "u.jsonl", "p.jsonl", "--json")) == {"T-REQ-001-01": "passed"}


@pytest.mark.covers(
    "SPC-REQ-005-04",
    "with CI job publish and producer docker both unreported, an unclaimed requirement is not run only for docker's sake, and once docker reports it is unclaimed with nothing to wait on",
)
def test_an_unreported_ci_job_doesnt_make_an_unclaimed_requirement_not_run(project: Project):
    """Only a test producer may claim what nobody claims; a CI job claims in the config."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-01": "the job publishes the image"}))
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("u.jsonl", "unit", [])
    waiting = project.speccheck("verify", "u.jsonl", "--json")
    assert status(waiting) == {"T-REQ-001-01": "not run", "T-REQ-001-02": "not run"}
    assert [r["waiting_on"] for r in waiting.json()["requirements"]] == [["publish"], ["docker"]]
    project.results("d.jsonl", "docker", [])
    reported = project.speccheck("verify", "u.jsonl", "d.jsonl", "--json")
    assert status(reported) == {"T-REQ-001-01": "not run", "T-REQ-001-02": "unclaimed"}
    assert reported.json()["requirements"][1]["waiting_on"] == []


@pytest.mark.covers(
    "SPC-REQ-005-04",
    "an unclaimed requirement of spec 001 is unclaimed, not not run, while producer docker, which may only claim spec 002, hasn't reported",
)
def test_a_producer_that_may_not_claim_it_isnt_waited_on(project: Project):
    """`specs` on the producer decides who could have claimed it."""
    project.write("speccheck.toml", CONFIG + '[producers.docker]\nspecs = ["002"]\n')
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: One.")
    project.write("specs/002-other.md", spec("- T-REQ-002-01: Other.", number="002", title="Other"))
    project.results("u.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-002-01"], "passed")])
    run = project.speccheck("verify", "u.jsonl", "--json")
    assert status(run) == {"T-REQ-001-01": "unclaimed", "T-REQ-002-01": "passed"}
    assert run.json()["requirements"][0]["waiting_on"] == []


@pytest.mark.covers(
    "SPC-REQ-005-05",
    "with producers docker and nightly both absent, --complete names both, exits 1, and the summary lists both as missing",
)
def test_complete_names_every_missing_producer(project: Project):
    """Two missing: two problems, both named."""
    project.write("speccheck.toml", CONFIG + "[producers.docker]\n[producers.nightly]\n")
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "unit.jsonl")
    assert run.code == 1
    assert "producer `docker` didn't report" in run.err and "producer `nightly` didn't report" in run.err
    assert run.err.splitlines()[-1].endswith("reported: unit; missing: docker, nightly; 2 problems")


@pytest.mark.covers(
    "SPC-REQ-005-05",
    "--complete --workflow nightly fails when producer nightly, which lists that workflow, didn't report, ignores producer docker, which doesn't, and passes once nightly reports",
)
def test_complete_for_a_workflow_needs_its_producers(project: Project):
    """The named workflow's producers, and only those."""
    project.write(
        "speccheck.toml",
        CONFIG.replace('workflows = ["ci"]', 'workflows = ["ci", "nightly"]')
        + '[producers.nightly]\nworkflows = ["nightly"]\n[producers.docker]\nworkflows = ["ci"]\n',
    )
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "--workflow", "nightly", "unit.jsonl")
    assert run.code == 1
    assert "producer `nightly` didn't report" in run.err and "producer `docker`" not in run.err
    project.results("nightly.jsonl", "nightly", [])
    assert project.speccheck("verify", "--complete", "--workflow", "nightly", "unit.jsonl", "nightly.jsonl").code == 0


@pytest.mark.covers(
    "SPC-REQ-005-05",
    "--complete fails when CI job publish, declared with [ci.publish], has no results file, naming it, and passes once it reports",
)
def test_complete_expects_a_ci_job_to_report(project: Project):
    """A `[ci.<job>]` is an expected producer like any other."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-01": "the job publishes the image"}, docker=False))
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [])
    run = project.speccheck("verify", "--complete", "u.jsonl")
    assert run.code == 1 and "producer `publish` didn't report" in run.err
    project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01"], "passed")], kind="ci")
    assert project.speccheck("verify", "--complete", "u.jsonl", "p.jsonl").code == 0


@pytest.mark.covers(
    "SPC-REQ-005-06",
    "check on a results file from undeclared producer stranger gives a producer-undeclared problem and leaves its claim unclaimed with no evidence",
)
def test_an_undeclared_producer_counts_for_nothing_in_check(project: Project):
    """The same file under `check`: a problem, and the claim is not one."""
    project.spec("- T-REQ-001-01: One.")
    project.results("stranger.jsonl", "stranger", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("check", "stranger.jsonl", "--json")
    assert run.code == 1
    assert {p["code"] for p in run.json()["problems"]} == {"producer-undeclared", "unclaimed"}
    assert status(run) == {"T-REQ-001-01": "unclaimed"}
    assert run.json()["requirements"][0]["evidence"] == []


@pytest.mark.covers(
    "SPC-REQ-005-06",
    "a passing result from undeclared producer stranger beside a failing one from declared unit leaves the requirement failed, with only unit's result as evidence",
)
def test_an_undeclared_pass_doesnt_outvote_a_declared_failure(project: Project):
    """If the stranger's pass counted, the requirement would be `passed`."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "failed")])
    project.results("s.jsonl", "stranger", [("tests/b.py::test_b", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "u.jsonl", "s.jsonl", "--json")
    assert run.code == 1 and status(run) == {"T-REQ-001-01": "failed"}
    assert [e["outcome"] for e in run.json()["requirements"][0]["evidence"]] == ["failed"]
    assert "producer-undeclared" in {p["code"] for p in run.json()["problems"]}


@pytest.mark.covers(
    "SPC-REQ-005-07",
    "check on a collect-only run of a test claiming an untested and a planned requirement asks to remove each marker",
)
def test_a_stale_marker_must_go_in_check(project: Project):
    """`check` reads a collect-only run, which has no outcomes."""
    project.spec("- T-REQ-001-01: One. ⚠ untested\n- T-REQ-001-02: Two. (planned: step 2)")
    project.tests(
        'import pytest\n\n@pytest.mark.covers("T-REQ-001-01", "one")\n@pytest.mark.covers("T-REQ-001-02", "two")\n'
        "def test_it():\n    pass\n"
    )
    project.ini("speccheck_producer = unit\n")
    project.pytest("--collect-only", "-q", "--speccheck-results=.speccheck/collect.jsonl")
    run = project.speccheck("check", ".speccheck/", "--json")
    assert run.code == 1
    assert {p["code"] for p in run.json()["problems"]} == {"untested-marker-stale", "planned-marker-stale"}


@pytest.mark.covers(
    "SPC-REQ-005-07",
    "[ci.publish] entries claiming an untested and a planned requirement make check and verify ask to remove each marker",
)
def test_a_stale_marker_must_go_for_a_ci_job_claim(project: Project):
    """The claimer is a job in the config, so no job result is needed."""
    covers = {"T-REQ-001-01": "the job publishes the image", "T-REQ-001-02": "the job tags the release"}
    project.write("speccheck.toml", ci_config(covers, docker=False))
    project.spec("- T-REQ-001-01: One. ⚠ untested\n- T-REQ-001-02: Two. (planned: step 2)")
    project.results("u.jsonl", "unit", [])
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl")
        assert run.code == 1
        assert "T-REQ-001-01 is claimed, so remove `⚠ untested`" in run.err, command
        assert "T-REQ-001-02 is claimed, so remove its `(planned: ...)`" in run.err, command


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "two [ci.*] jobs giving one explanation for two requirements make check and verify fail with a how-duplicate problem naming both jobs",
)
def test_two_ci_jobs_cant_share_an_explanation(project: Project):
    """Two entries in the config with the same text."""
    project.write(
        "speccheck.toml",
        CONFIG
        + '[ci.a.covers]\n"T-REQ-001-01" = "the image is published"\n'
        + '[ci.b.covers]\n"T-REQ-001-02" = "The image is PUBLISHED."\n',
    )
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("u.jsonl", "unit", [])
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert run.code == 1
        duplicate = [p["message"] for p in run.json()["problems"] if p["code"] == "how-duplicate"]
        assert duplicate == [
            "`ci.b.covers`: `ci.b` gives the same explanation for T-REQ-001-02 as `ci.a` does for T-REQ-001-01; "
            "each claim says how its own test proves its requirement"
        ], command


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "verify, like check, fails on a passing test whose explanation repeats a CI job's config entry, naming the job",
)
def test_a_test_cant_repeat_a_ci_jobs_explanation_in_verify(project: Project):
    """`check` has its own test for this; `verify` runs the same rule on a run that passed."""
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = { "T-REQ-001-02" = "the image is published" }\n')
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = '{"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "the image is published"}], "outcome": "passed"}\n'
    project.write("u.jsonl", header + line)
    run = project.speccheck("verify", "u.jsonl")
    assert run.code == 1
    assert "t gives the same explanation for T-REQ-001-01 as `ci.publish` does for T-REQ-001-02" in run.err


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "a CI job's result giving the same explanation as an earlier test's makes verify fail with a how-duplicate problem naming the job and the test",
)
def test_a_ci_jobs_result_cant_repeat_a_tests_explanation(project: Project):
    """The job's result is read after the test's, so it is the one reported."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-02": "the job tags the release"}, docker=False))
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    header = '{"schema": "speccheck-results/1", "producer": "%s"}\n'
    test = '{"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "the image is published"}], "outcome": "passed"}\n'
    job = '{"test": "publish", "kind": "ci", "covers": [{"id": "T-REQ-001-02", "how": "the image is published"}], "outcome": "passed"}\n'
    project.write("u.jsonl", header % "unit" + test)
    project.write("p.jsonl", header % "publish" + job)
    run = project.speccheck("verify", "u.jsonl", "p.jsonl", "--json")
    assert run.code == 1
    assert [p["message"] for p in run.json()["problems"] if p["code"] == "how-duplicate"] == [
        "`ci.publish` gives the same explanation for T-REQ-001-02 as t does for T-REQ-001-01; "
        "each claim says how its own test proves its requirement"
    ]


@pytest.mark.covers(
    "SPC-REQ-005-10",
    "one test's claim in two files of one producer from different run attempts counts as one claim, so verify passes",
)
def test_the_same_claim_in_another_attempt_is_not_a_repeat(project: Project):
    """A re-run writes the test's claim again; that is the same claim."""
    project.spec("- T-REQ-001-01: One.")
    for name, attempt in (("a1.jsonl", 1), ("a2.jsonl", 2)):
        project.results(
            name, "unit", [("tests/a.py::test_a", ["T-REQ-001-01"], "passed")], ci={"run_id": 7, "run_attempt": attempt}
        )
    run = project.speccheck("verify", "a1.jsonl", "a2.jsonl", "--json")
    assert (run.code, run.json()["problems"]) == (0, [])


@pytest.mark.covers(
    "SPC-REQ-005-11",
    "[ci.publish] entries for a malformed ID and a retired ID each get a config-claim-invalid problem with the 003-13 fix, in check and verify, and neither counts",
)
def test_ci_entries_with_a_malformed_or_retired_id_count_for_nothing(project: Project):
    """The config's claims are checked in the config, so they can be wrong without any job running."""
    covers = {"T-REQ-1-1": "the job builds the image", "T-REQ-001-02": "the job pushes the image"}
    project.write("speccheck.toml", ci_config(covers, docker=False))
    project.spec("- T-REQ-001-01: Live.\n- T-REQ-001-02: Retired. Gone.")
    project.results("u.jsonl", "unit", [])
    fixes = {
        "T-REQ-1-1": "is not an ID of this folder; IDs read like `T-REQ-",
        "T-REQ-001-02": "is retired; claim what replaced it",
    }
    for command in ("check", "verify"):
        run = project.speccheck(command, "u.jsonl", "--json")
        assert run.code == 1
        invalid = [p["message"] for p in run.json()["problems"] if p["code"] == "config-claim-invalid"]
        assert len(invalid) == 2, invalid
        for id_, fix in fixes.items():
            assert any(id_ in m and fix in m and "`ci.publish.covers`" in m for m in invalid), (command, id_, invalid)
        by_id = {r["id"]: r for r in run.json()["requirements"]}
        assert by_id["T-REQ-001-02"]["status"] == "retired" and by_id["T-REQ-001-02"]["evidence"] == []
        assert by_id["T-REQ-001-01"]["status"] == "unclaimed"


@pytest.mark.covers(
    "SPC-REQ-005-11",
    "a [ci.publish] entry on an ID that no spec has, the only entry, leaves the real requirement unclaimed instead of not run waiting on publish",
)
def test_a_refused_ci_entry_is_not_a_claim(project: Project):
    """If the refused entry counted, the real requirement would be `not run`, waiting on `publish`."""
    project.write("speccheck.toml", ci_config({"T-REQ-001-09": "the job builds the image"}, docker=False))
    project.spec("- T-REQ-001-01: Live.")
    project.results("u.jsonl", "unit", [])
    run = project.speccheck("verify", "u.jsonl", "--json")
    assert status(run) == {"T-REQ-001-01": "unclaimed"}
    assert run.json()["requirements"][0]["waiting_on"] == []
    fix = [p["message"] for p in run.json()["problems"] if p["code"] == "config-claim-invalid"][0]
    assert "T-REQ-001-09 isn't in any spec; check the number, or add it to spec 001" in fix
