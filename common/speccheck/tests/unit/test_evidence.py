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

from pathlib import Path

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


@pytest.mark.parametrize("outcome", ["failed", "error", "skipped", "xfailed", "xpassed", "deselected", "collected"])
def test_anything_but_passed_fails(repo: Repo, outcome: str):
    """Only `passed` is evidence, and the problem lists what was seen."""
    repo.spec("- T-REQ-001-01: It.")
    evaluation = evaluate(repo, [run_of("unit", ("T-REQ-001-01", outcome), leg="3.12")])
    assert statuses(evaluation) == {"T-REQ-001-01": "failed"}
    assert messages(evaluation) == [
        f"specs/001-thing.md:7: T-REQ-001-01 has no passing result: tests/test_x.py::test_1 {outcome} in unit 3.12"
    ]


def test_a_long_list_of_failures_is_cut(repo: Repo):
    """At most five results are listed in the message."""
    repo.spec("- T-REQ-001-01: It.")
    evaluation = evaluate(repo, [run_of("unit", *[("T-REQ-001-01", "skipped")] * 7)])
    assert messages(evaluation)[0].endswith("(and 2 more)")


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


def test_an_undeclared_producer_doesnt_count(repo: Repo):
    """Its results are a problem, and its passes are not evidence."""
    repo.spec("- T-REQ-001-01: It.")
    evaluation = evaluate(repo, [run_of("stranger", ("T-REQ-001-01", "passed")), run_of("unit")])
    assert statuses(evaluation) == {"T-REQ-001-01": "unclaimed"}
    assert "stranger.jsonl:1: producer `stranger` isn't declared in speccheck.toml (declared: unit)" in messages(
        evaluation
    )


def test_a_marker_on_a_claimed_requirement_must_go(repo: Repo):
    """Once claimed, the marker is stale, in check and in verify."""
    repo.spec("- T-REQ-001-01: A. ⚠ untested\n- T-REQ-001-02: B. (planned: step 2)")
    files = [run_of("unit", ("T-REQ-001-01", "passed"), ("T-REQ-001-02", "collected"))]
    for runtime in (False, True):
        found = messages(evaluate(repo, files, runtime=runtime))
        assert any("T-REQ-001-01 is claimed, so remove `⚠ untested`" in m for m in found)
        assert any("T-REQ-001-02 is claimed, so remove its `(planned: ...)`" in m for m in found)


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


def requirement(text: str = "It.", status: str = "draft", number: str = "001") -> specs.Requirement:
    """A requirement in a spec of the given status, without a spec folder on disk."""
    spec = specs.Spec(path=Path(f"specs/{number}-x.md"), number=number, status=status)
    return specs.Requirement(id=f"T-REQ-{number}-01", spec=spec, line=7, text=text)


def producer_config(*producers: config.Producer) -> config.Config:
    """A config holding only the given producers."""
    return config.Config(path=Path("speccheck.toml"), specs_dir=Path("specs"), producers={p.name: p for p in producers})


UNIT = config.Producer(name="unit", specs=None, workflows=())
"""A test producer that may claim every spec."""
OTHER_SPECS = config.Producer(name="other", specs=("002",), workflows=())
"""A test producer that may claim only spec 002."""
JOB = config.Producer(name="job", specs=None, workflows=(), covers=("T-REQ-001-01",), ci_job=True)
"""A CI job."""


def evidence_of(*outcomes: str) -> list[evidence.Evidence]:
    """One result per outcome, from producer `unit`."""
    source = results.ResultsFile(producer="unit")
    return [
        evidence.Evidence(results.Result(test=f"t{n}", covers=["T-REQ-001-01"], outcome=o), source)
        for n, o in enumerate(outcomes)
    ]


@pytest.mark.parametrize(
    ("text", "status", "found", "config_claims", "reported", "runtime", "expected", "waiting"),
    [
        # what the spec says, when nothing claims it
        ("Retired. Gone.", "draft", [], [], [], True, "retired", []),
        ("It.", "retired", ["passed"], [], ["unit"], True, "retired", []),
        ("It. (planned: 2)", "draft", [], [], [], True, "planned", []),
        ("It. ⚠ untested", "draft", [], [], [], True, "untested", []),
        # nothing claims it: unclaimed, unless a test producer that may claim it didn't report (verify only)
        ("It.", "draft", [], [], ["unit"], True, "unclaimed", []),
        ("It.", "draft", [], [], [], True, "not run", ["unit"]),
        ("It.", "draft", [], [], [], False, "unclaimed", []),
        # claimed: check sees the claim only; verify needs a pass
        ("It.", "draft", ["failed"], [], ["unit"], False, "claimed", []),
        ("It.", "draft", ["skipped", "passed"], [], ["unit"], True, "passed", []),
        ("It.", "draft", ["skipped", "xpassed"], [], ["unit"], True, "failed", []),
        # claimed only by a CI job in the config, which didn't report
        ("It.", "draft", [], ["job"], ["unit"], True, "not run", ["job"]),
        ("It.", "draft", [], ["job"], ["unit", "job"], True, "not run", []),
    ],
)
def test_decide(text, status, found, config_claims, reported, runtime, expected, waiting):
    """Every row of the status table in design.md, for one requirement."""
    decided = evidence._decide(
        requirement(text, status),
        evidence_of(*found),
        config_claims,
        producer_config(UNIT, OTHER_SPECS, JOB),
        reported,
        runtime,
    )
    assert (decided.status, decided.waiting_on) == (expected, waiting)
    assert decided.claimed == (expected in ("claimed", "passed", "failed") or bool(config_claims))


def test_decide_ignores_producers_that_may_not_claim_the_spec():
    """A producer limited to spec 002 that didn't report isn't waited on for spec 001."""
    decided = evidence._decide(requirement(), [], [], producer_config(OTHER_SPECS), [], True)
    assert (decided.status, decided.waiting_on) == ("unclaimed", [])


@pytest.mark.parametrize(
    ("status", "complete", "expected"),
    [
        ("passed", True, []),
        ("planned", True, []),
        ("claimed", True, []),
        ("unclaimed", False, ["T-REQ-001-01 is not claimed"]),
        ("failed", False, ["T-REQ-001-01 has no passing result"]),
        ("not run", False, []),
        ("not run", True, ["T-REQ-001-01 was not run"]),
    ],
)
def test_problems_of(status, complete, expected, tmp_path: Path):
    """Which statuses are problems, with and without --complete."""
    decided = evidence.Status(requirement(), status, evidence_of("failed") if status == "failed" else [])
    found = [p.message for p in evidence._problems_of(decided, tmp_path, complete)]
    assert len(found) == len(expected)
    assert [m[: len(e)] for m, e in zip(found, expected, strict=True)] == expected
