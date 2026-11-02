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

"""How each requirement's status is decided, and which statuses are problems."""

from __future__ import annotations

import pytest

from speccheck import config, evidence, results, specs
from tests.conftest import CONFIG, Repo


def evaluate(repo: Repo, files: list[results.ResultsFile], *, runtime: bool = True, **kwargs) -> evidence.Evaluation:
    """Evaluate the repo's specs against some results files."""
    loaded = config.load(repo.root / "speccheck.toml")
    spec_set = specs.load(loaded.specs_dir, repo.root, loaded.prefix, loaded.require_index)
    return evidence.evaluate(spec_set, loaded, files, root=repo.root, runtime=runtime, **kwargs)


def run_of(producer: str, *claims: tuple[str, str], leg: str = "") -> results.ResultsFile:
    """A results file of `(id, outcome)` claims, one test each."""
    return results.ResultsFile(
        producer=producer,
        ci={"leg": leg} if leg else None,
        source=f"{producer}.jsonl",
        results=[
            results.Result(test=f"tests/test_x.py::test_{n}", covers=[id_], outcome=o, file="tests/test_x.py", line=n)
            for n, (id_, o) in enumerate(claims, 1)
        ],
    )


def statuses(evaluation: evidence.Evaluation) -> dict[str, str]:
    """ID -> status."""
    return {s.requirement.id: s.status for s in evaluation.statuses}


def messages(evaluation: evidence.Evaluation) -> list[str]:
    """Every problem as a string."""
    return [str(p) for p in evaluation.problems]


@pytest.mark.covers("SPC-REQ-005-01")
class TestPassed:
    """One passing result is enough."""

    def test_one_pass_among_failures(self, repo: Repo):
        """A pass in one leg outweighs a skip in another."""
        repo.spec("- T-REQ-001-01: It.")
        files = [
            run_of("unit", ("T-REQ-001-01", "skipped"), leg="3.10"),
            run_of("unit", ("T-REQ-001-01", "passed"), leg="3.14"),
        ]
        evaluation = evaluate(repo, files)
        assert statuses(evaluation) == {"T-REQ-001-01": "passed"} and evaluation.problems == []
        assert len(evaluation.statuses[0].evidence) == 2

    def test_counts_and_summary_line(self, repo: Repo):
        """Every status is counted; the summary line leaves out the empty ones."""
        repo.spec("- T-REQ-001-01: It.\n- T-REQ-001-02: Later. (planned: step 2)")
        evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", "passed"))])
        assert evaluation.counts()["passed"] == 1 and evaluation.counts()["failed"] == 0
        assert evidence.summary_line(evaluation.counts()) == "2 requirements: 1 passed, 1 planned"
        assert evidence.summary_line({"passed": 1}) == "1 requirement: 1 passed"
        assert evidence.summary_line({}) == "0 requirements"


@pytest.mark.covers("SPC-REQ-005-02")
@pytest.mark.parametrize("outcome", ["failed", "error", "skipped", "xfailed", "xpassed", "deselected", "collected"])
def test_anything_but_passed_fails(repo: Repo, outcome: str):
    """Only `passed` is evidence, and the problem lists what was seen."""
    repo.spec("- T-REQ-001-01: It.")
    evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", outcome), leg="3.12")])
    assert statuses(evaluation) == {"T-REQ-001-01": "failed"}
    assert messages(evaluation) == [
        f"specs/001-thing.md:7: T-REQ-001-01 has no passing result: tests/test_x.py::test_1 {outcome} in unit 3.12"
    ]


@pytest.mark.covers("SPC-REQ-005-02")
def test_a_long_list_of_failures_is_cut(repo: Repo):
    """At most five results are listed in the message."""
    repo.spec("- T-REQ-001-01: It.")
    evaluation = evaluate(repo, [run_of("unit", *[("T-REQ-001-01", "skipped")] * 7)])
    assert messages(evaluation)[0].endswith("(and 2 more)")


@pytest.mark.covers("SPC-REQ-005-03")
class TestUnclaimed:
    """Nothing claims it."""

    def test_unclaimed_fails_check_and_verify(self, repo: Repo):
        """The message shows the marker to add."""
        repo.spec("- T-REQ-001-01: It.")
        for runtime in (False, True):
            evaluation = evaluate(repo, [run_of("unit")], runtime=runtime)
            assert statuses(evaluation) == {"T-REQ-001-01": "unclaimed"}
            assert '@pytest.mark.covers("T-REQ-001-01")' in messages(evaluation)[0]

    def test_markers_and_retirement_excuse_it(self, repo: Repo):
        """Planned, untested and retired requirements need no claim."""
        repo.spec("- T-REQ-001-01: A. ⚠ untested\n- T-REQ-001-02: B. (planned: step 2)\n- T-REQ-001-03: Retired. Gone.")
        evaluation = evaluate(repo, [run_of("unit")])
        assert list(statuses(evaluation).values()) == ["untested", "planned", "retired"]
        assert evaluation.problems == []


@pytest.mark.covers("SPC-REQ-005-04")
class TestNotRun:
    """Claimed only by producers that didn't report."""

    def test_a_producer_that_didnt_report(self, repo: Repo):
        """Without results from `unit`, its requirements wait on it, and fail only a complete check."""
        repo.spec("- T-REQ-001-01: It.")
        evaluation = evaluate(repo, [])
        assert statuses(evaluation) == {"T-REQ-001-01": "not run"}
        assert evaluation.statuses[0].waiting_on == ["unit"]
        assert evaluation.problems == []
        complete = evaluate(repo, [], complete=True)
        assert any("T-REQ-001-01 was not run" in m for m in messages(complete))

    def test_a_ci_job_that_didnt_record(self, repo: Repo):
        """A CI job's claim is in the config, so its requirement waits on that job by name."""
        repo.write("speccheck.toml", CONFIG + '\n[ci.publish]\ncovers = ["T-REQ-001-01"]\n')
        repo.spec("- T-REQ-001-01: It.")
        evaluation = evaluate(repo, [run_of("unit")])
        assert statuses(evaluation) == {"T-REQ-001-01": "not run"}
        assert evaluation.statuses[0].waiting_on == ["publish"]


@pytest.mark.covers("SPC-REQ-005-05")
class TestComplete:
    """`--complete` and `--workflow`."""

    def test_missing_producers(self, repo: Repo):
        """Every expected producer must report."""
        repo.write("speccheck.toml", CONFIG + '\n[producers.docker]\nworkflows = ["other"]\n')
        repo.spec("- T-REQ-001-01: It.")
        evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", "passed"))], complete=True)
        assert evaluation.missing == ["docker"]
        assert any("producer `docker` didn't report" in m for m in messages(evaluation))

    def test_workflow_limits_what_is_expected(self, repo: Repo):
        """With `--workflow ci`, a producer of another workflow isn't expected."""
        repo.write("speccheck.toml", CONFIG + '\n[producers.docker]\nworkflows = ["other"]\n')
        repo.spec("- T-REQ-001-01: It.")
        evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", "passed"))], complete=True, workflow="ci")
        assert evaluation.missing == [] and evaluation.problems == []
        assert evaluation.reported == ["unit"]


@pytest.mark.covers("SPC-REQ-005-06")
def test_an_undeclared_producer_doesnt_count(repo: Repo):
    """Its results are a problem, and its passes are not evidence."""
    repo.spec("- T-REQ-001-01: It.")
    evaluation = evaluate(repo, [run_of("stranger", ("T-REQ-001-01", "passed")), run_of("unit")])
    assert statuses(evaluation) == {"T-REQ-001-01": "unclaimed"}
    assert "stranger.jsonl:1: producer `stranger` isn't declared in speccheck.toml (declared: unit)" in messages(
        evaluation
    )


@pytest.mark.covers("SPC-REQ-005-07")
def test_a_marker_on_a_claimed_requirement_must_go(repo: Repo):
    """Once claimed, the marker is stale, in check and in verify."""
    repo.spec("- T-REQ-001-01: A. ⚠ untested\n- T-REQ-001-02: B. (planned: step 2)")
    files = [run_of("unit", ("T-REQ-001-01", "passed"), ("T-REQ-001-02", "collected"))]
    for runtime in (False, True):
        found = messages(evaluate(repo, files, runtime=runtime))
        assert any("T-REQ-001-01 is claimed, so remove `⚠ untested`" in m for m in found)
        assert any("T-REQ-001-02 is claimed, so remove its `(planned: ...)`" in m for m in found)


@pytest.mark.covers("SPC-REQ-005-08")
class TestCheck:
    """The static check, on a collect-only run."""

    def test_collected_is_enough_for_check(self, repo: Repo):
        """`check` looks at claims, not outcomes."""
        repo.spec("- T-REQ-001-01: It.")
        evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", "collected"))], runtime=False)
        assert statuses(evaluation) == {"T-REQ-001-01": "claimed"} and evaluation.problems == []

    @pytest.mark.parametrize(
        ("claimed", "message"),
        [
            ("REQ-001-01", "`REQ-001-01` is not an ID of this folder; IDs read like `T-REQ-001-01`"),
            ("T-REQ-001-09", "T-REQ-001-09 isn't in any spec; check the number, or add it to spec 001"),
            ("T-REQ-001-02", "T-REQ-001-02 is retired; claim what replaced it"),
        ],
    )
    def test_bad_claims(self, repo: Repo, claimed: str, message: str):
        """Malformed, unknown and retired IDs, at the test's file and line."""
        repo.spec("- T-REQ-001-01: It. ⚠ untested\n- T-REQ-001-02: Retired. Gone.")
        evaluation = evaluate(repo, [run_of("unit", (claimed, "collected"))], runtime=False)
        assert messages(evaluation) == [f"tests/test_x.py:1: {message}"]

    def test_a_producer_limited_to_other_specs(self, repo: Repo):
        """A claim outside the producer's `specs` says how to allow it."""
        repo.write("speccheck.toml", CONFIG.replace('specs = "all"', 'specs = ["002"]'))
        repo.spec("- T-REQ-001-01: It. ⚠ untested")
        evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", "collected"))], runtime=False)
        assert "which producer `unit` may not claim; add it to `producers.unit.specs`" in messages(evaluation)[0]


@pytest.mark.covers("SPC-REQ-007-02")
class TestCiJobClaims:
    """A CI job may record only what its config entry lists."""

    def test_a_ci_job_counts_for_its_own_ids(self, repo: Repo):
        """Its recorded result passes the requirement."""
        repo.write("speccheck.toml", CONFIG + '\n[ci.publish]\ncovers = ["T-REQ-001-01"]\n')
        repo.spec("- T-REQ-001-01: It.\n- T-REQ-001-02: Other. ⚠ untested")
        job = run_of("publish", ("T-REQ-001-01", "passed"), ("T-REQ-001-02", "passed"))
        evaluation = evaluate(repo, [job, run_of("unit")])
        assert statuses(evaluation)["T-REQ-001-01"] == "passed"
        assert any("T-REQ-001-02 isn't in `ci.publish.covers`" in m for m in messages(evaluation))

    def test_a_bad_id_in_the_config(self, repo: Repo):
        """A typo in `covers` is a problem at the config."""
        repo.write("speccheck.toml", CONFIG + '\n[ci.publish]\ncovers = ["T-REQ-001-09"]\n')
        repo.spec("- T-REQ-001-01: It. ⚠ untested")
        found = messages(evaluate(repo, [run_of("unit")]))
        assert found == [
            "speccheck.toml: `ci.publish.covers`: T-REQ-001-09 isn't in any spec; check the number, or add it to spec 001"
        ]

    def test_a_result_without_a_file(self, repo: Repo):
        """A CI job's bad claim is reported at the job's name."""
        repo.write("speccheck.toml", CONFIG + '\n[ci.publish]\ncovers = ["T-REQ-001-01"]\n')
        repo.spec("- T-REQ-001-01: It.")
        job = results.ResultsFile(
            producer="publish",
            source="p.jsonl",
            results=[results.Result("publish", ["T-REQ-001-09"], "passed", kind="ci")],
        )
        assert any(m.startswith("publish: T-REQ-001-09") for m in messages(evaluate(repo, [job, run_of("unit")])))
