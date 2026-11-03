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
    assert "; to fix: " in run.err


@pytest.mark.covers("SPC-REQ-005-02", "a claiming test left out with -k is listed as deselected and verify exits 1")
def test_a_deselected_claim_fails_verify(project: Project):
    """A claim filtered out with -k didn't run, so it proves nothing."""
    project.spec("- T-REQ-001-01: One.")
    project.tests(CLAIM.format(marks="", body="pass") + "\ndef test_other():\n    pass\n")
    project.ini("speccheck_producer = unit\n")
    project.pytest("--speccheck-results=r.jsonl", "-k", "test_other")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1 and "test_project.py::test_it deselected in unit" in run.err


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
    "a requirement only producer docker may claim is not run, waiting on docker, and fails verify only with --complete",
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
    "--complete --workflow typo exits 2 because no producer lists that workflow, while --workflow alone is ignored",
)
def test_complete_with_a_workflow_nobody_lists_is_an_error(project: Project):
    """A typo or a renamed workflow must not turn the missing-producer check off."""
    project.spec("- T-REQ-001-01: One.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = project.speccheck("verify", "--complete", "--workflow", "typo", "unit.jsonl")
    assert run.code == 2 and "no producer" in run.err and "typo" in run.err
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
    "check on a collect-only run of a failing claim counts it as claimed, and fails only on the unclaimed requirement",
)
def test_check_on_a_collect_only_run(project: Project):
    """Outcomes don't matter to check: a failing test's claim counts, an unclaimed requirement doesn't."""
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
                f"check on a results file that records the claim as {outcome} calls it claimed and fails only on the unclaimed requirement, while verify does not call it claimed",
            ),
        )
        for outcome in ("failed", "error", "skipped", "xfailed", "xpassed", "deselected", "collected")
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
    assert status(project.speccheck("verify", "r.jsonl", "--json"))["T-REQ-001-01"] != "claimed"


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
    "a results file claiming malformed, unknown, retired and disallowed IDs gets four claim-invalid problems from check and verify, and none of them counts",
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
