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

"""How each requirement's status is decided, and which statuses are problems, on specs and a config built in memory."""

from __future__ import annotations

import pytest

from speccheck import config, evidence, results, specs
from speccheck.claims import Claim
from speccheck.config import ConfigError
from tests.unit.conftest import (
    ROOT,
    ci_job,
    make_config,
    make_requirement,
    make_spec,
    make_specs,
    producer,
    results_file,
    spec_set,
)

UNIT = producer("unit")
"""A test producer that may claim every spec."""
OTHER_SPECS = producer("other", may_claim=("002",))
"""A test producer that may claim only spec 002."""
JOB = ci_job("job", "T-REQ-001-01")
"""A CI job claiming T-REQ-001-01."""


def evidence_of(*outcomes: str, job_name: str = "") -> list[evidence.Evidence]:
    """One result per outcome, from producer `unit`, in the job named `job_name` when given."""
    source = results.ResultsFile(producer="unit")
    return [
        evidence.Evidence(
            results.Result(test=f"t{n}", covers=[Claim("T-REQ-001-01", f"t{n} proves it")], outcome=o),
            source,
            f"t{n} proves it",
            job_name,
        )
        for n, o in enumerate(outcomes)
    ]


def statuses(evaluation: evidence.Evaluation) -> dict[str, str]:
    """ID -> status."""
    return {s.requirement.id: s.status for s in evaluation.statuses}


def messages(evaluation: evidence.Evaluation) -> list[str]:
    """Every problem as a string."""
    return [str(p) for p in evaluation.problems]


class TestCounts:
    """The counts and the summary line."""

    def test_counts_list_every_status(self):
        """Every status is a key, worst first, even with none."""
        spec = make_spec()
        status = evidence.Status(make_requirement(spec), evidence.PASSED)
        counts = evidence.Evaluation([status], [], [], []).counts()
        assert list(counts) == list(evidence.STATUSES)
        assert counts["passed"] == 1 and sum(counts.values()) == 1

    @pytest.mark.parametrize(
        ("counts", "line"),
        [
            ({}, "0 requirements"),
            ({"passed": 1}, "1 requirement: 1 passed"),
            ({"failed": 0, "passed": 1, "unimplemented": 1}, "2 requirements: 1 passed, 1 unimplemented"),
        ],
    )
    def test_summary_line(self, counts, line):
        """Empty statuses are left out; the noun agrees with the total."""
        assert evidence.summary_line(counts) == line


class TestClaimProblem:
    """Why a producer may not claim an ID."""

    SPECS = make_specs("It.")
    """T-REQ-001-01."""

    @pytest.mark.parametrize(
        ("claimed", "who", "message"),
        [
            ("T-REQ-001-01", UNIT, ""),
            ("T-REQ-001-01", None, ""),
            ("REQ-001-01", UNIT, "`REQ-001-01` is not an ID of this folder; IDs read like `T-REQ-001-01`"),
            ("T-REQ-001-01x", UNIT, "is not an ID of this folder"),
            ("T-REQ-001-09", UNIT, "T-REQ-001-09 isn't in any spec; check the number, or add it to spec 001"),
            (
                "T-REQ-002-09",
                UNIT,
                "T-REQ-002-09 isn't in any spec, and there is no spec 002; check the number, or write spec 002",
            ),
            (
                "T-REQ-001-01",
                OTHER_SPECS,
                "T-REQ-001-01 is in spec 001, which producer `other` may not claim; "
                "add it to `producers.other.specs` or claim it from another producer",
            ),
        ],
    )
    def test_claim_problem(self, claimed, who, message):
        """Malformed, unknown and not allowed, each with what to do; "" when fine."""
        found = evidence.claim_problem(claimed, who, self.SPECS)
        assert message in found and bool(found) == bool(message)


def test_where_and_describe():
    """A claim is located by its file, or its test name without one; described by job name, else producer."""
    assert evidence._where(results.Result("t", ["X"], "passed", file="f.py", line=3)) == ("f.py", 3)
    assert evidence._where(results.Result("publish", ["X"], "passed", kind="ci")) == ("publish", 0)
    assert evidence._describe(evidence_of("skipped", job_name="unit (3.12)")[0]) == "t0 skipped in unit (3.12)"
    assert evidence._describe(evidence_of("failed")[0]) == "t0 failed in unit"


@pytest.mark.parametrize(
    ("text", "status", "found", "config_claims", "reported", "runtime", "expected", "waiting"),
    [
        # what the spec says, when nothing claims it
        ("It. (unimplemented: step 2)", "draft", [], [], [], True, "unimplemented", []),
        ("It. (unimplemented: step 2)", "draft", [], [], [], False, "unimplemented", []),
        # nothing claims it: unclaimed, unless a test producer that may claim it didn't report (verify only)
        ("It.", "draft", [], [], ["unit"], True, "unclaimed", []),
        ("It.", "draft", [], [], [], True, "not run", ["unit"]),
        ("It.", "draft", [], [], [], False, "unclaimed", []),
        # claimed: check sees the claim only; verify needs a pass
        ("It.", "draft", ["failed"], [], ["unit"], False, "claimed", []),
        ("It.", "draft", ["skipped", "passed"], [], ["unit"], True, "passed", []),
        ("It.", "draft", ["skipped", "xpassed"], [], ["unit"], True, "failed", []),
        # a marker doesn't excuse a claimed requirement: it is decided by its evidence
        ("It. (unimplemented: step 2)", "draft", ["passed"], [], ["unit"], True, "passed", []),
        ("It. (unimplemented: step 2)", "draft", ["collected"], [], ["unit"], False, "claimed", []),
        # claimed only by a CI job in the config, which didn't report
        ("It.", "draft", [], ["job"], ["unit"], True, "not run", ["job"]),
        ("It.", "draft", [], ["job"], ["unit", "job"], True, "not run", []),
        # an unimplemented requirement is never not run, even claimed by a job that didn't report
        ("It. (unimplemented: step 2)", "draft", [], ["job"], ["unit"], True, "unimplemented", []),
    ],
)
def test_decide(text, status, found, config_claims, reported, runtime, expected, waiting):
    """Every row of the status table in design.md, for one requirement."""
    requirement = make_requirement(make_spec(status=status), text)
    decided = evidence._decide(
        requirement, evidence_of(*found), config_claims, make_config(UNIT, OTHER_SPECS, JOB), reported, runtime
    )
    assert (decided.status, decided.waiting_on) == (expected, waiting)
    assert decided.claimed == (expected in ("claimed", "passed", "failed") or bool(config_claims))


@pytest.mark.parametrize("outcome", [o for o in results.OUTCOMES if o != "passed"])
def test_anything_but_passed_is_failed(outcome: str):
    """Only `passed` is evidence."""
    requirement = make_requirement(make_spec())
    decided = evidence._decide(requirement, evidence_of(outcome), [], make_config(UNIT), ["unit"], True)
    assert decided.status == "failed"


def test_decide_ignores_producers_that_may_not_claim_the_spec():
    """A producer limited to spec 002 that didn't report isn't waited on for spec 001."""
    decided = evidence._decide(make_requirement(make_spec()), [], [], make_config(OTHER_SPECS), [], True)
    assert (decided.status, decided.waiting_on) == ("unclaimed", [])


@pytest.mark.parametrize(
    ("status", "complete", "expected"),
    [
        ("passed", True, []),
        ("unimplemented", True, []),
        ("claimed", True, []),
        (
            "unclaimed",
            False,
            ['T-REQ-001-01 is not claimed; add `@pytest.mark.covers("T-REQ-001-01", "<how it proves it>")`'],
        ),
        (
            "failed",
            False,
            [
                "T-REQ-001-01 has no passing result: t0 failed in unit (3.12); to fix: fix the test or the code it checks"
            ],
        ),
        ("not run", False, []),
        ("not run", True, ["T-REQ-001-01 was not run: nothing that reported claims it (waiting on: unit)"]),
    ],
)
def test_problems_of(status, complete, expected):
    """Which statuses are problems, with and without --complete, at the spec's path and the bullet's line."""
    requirement = make_requirement(make_spec())
    found = evidence_of("failed", job_name="unit (3.12)") if status == "failed" else []
    decided = evidence.Status(requirement, status, found, waiting_on=["unit"] if status == "not run" else [])
    problems = evidence._problems_of(decided, ROOT, complete)
    assert [p.message[: len(e)] for p, e in zip(problems, expected, strict=True)] == expected
    assert all((p.path, p.line) == ("specs/001-thing.md", 7) for p in problems)


def test_not_run_with_nobody_to_wait_on():
    """A CI job's requirement whose job reported nothing for it says `none`."""
    decided = evidence.Status(make_requirement(make_spec()), "not run")
    assert evidence._problems_of(decided, ROOT, True)[0].message.endswith("(waiting on: none)")


def test_a_long_list_of_failures_is_cut():
    """At most five results are listed in the message."""
    decided = evidence.Status(make_requirement(make_spec()), "failed", evidence_of(*["skipped"] * 7))
    message = evidence._problems_of(decided, ROOT, False)[0].message
    assert message.count("skipped in unit") == 5 and "(and 2 more); to fix: " in message


def test_the_hint_names_each_outcome_once():
    """Mixed outcomes get one hint each, in the order seen; an outcome with no hint adds none."""
    decided = evidence.Status(make_requirement(make_spec()), "failed", evidence_of("skipped", "failed", "skipped"))
    message = evidence._problems_of(decided, ROOT, False)[0].message
    assert message.endswith(f"; to fix: {evidence.HINTS['skipped']}; or {evidence.HINTS['failed']}")
    assert evidence._hint([]) == ""


@pytest.mark.parametrize("status", ["passed", "failed", "claimed", "not run"])
def test_a_suffix_on_a_claimed_requirement_must_go(status):
    """Once claimed, the suffix is stale, whatever the status."""
    requirement = make_requirement(make_spec(), "It. (unimplemented: step 2)")
    decided = evidence.Status(requirement, status, claimed=True)
    found = evidence._problems_of(decided, ROOT, False)
    assert [(p.code, p.message) for p in found if p.code == "unimplemented-stale"] == [
        ("unimplemented-stale", "T-REQ-001-01 is claimed, so remove its `(unimplemented: ...)` suffix")
    ]


def test_an_unclaimed_requirement_says_how_to_mark_it_unimplemented():
    """The message names both fixes."""
    decided = evidence.Status(make_requirement(make_spec()), "unclaimed")
    assert evidence._problems_of(decided, ROOT, False)[0].message.endswith(
        "or end it with `(unimplemented: <reason>)` in the spec if a plan delivers it later"
    )


def evaluate(spec_text: tuple[str, ...], files, *producers, runtime=True, **kwargs) -> evidence.Evaluation:
    """`evidence.evaluate` on one spec of the given requirements and a config of `producers` (default: UNIT)."""
    return evidence.evaluate(
        make_specs(*spec_text), make_config(*(producers or (UNIT,))), files, root=ROOT, runtime=runtime, **kwargs
    )


class TestEvaluate:
    """What `evaluate` adds to `_decide`: which claims count, CI jobs, --complete, and the problem order."""

    def test_claims_are_gathered_across_files(self):
        """A pass in one job outweighs a skip in another; both are the requirement's evidence, named by job."""
        files = [
            results_file("unit", ("T-REQ-001-01", "skipped"), ci={"job_id": 10}),
            results_file("unit", ("T-REQ-001-01", "passed"), ci={"job_id": 14}),
        ]
        evaluation = evaluate(("It.",), files, job_names={"10": "unit 3.10"})
        assert statuses(evaluation) == {"T-REQ-001-01": "passed"} and evaluation.problems == []
        found = evaluation.statuses[0].evidence
        assert [(e.result.outcome, e.job_name, e.where) for e in found] == [
            ("skipped", "unit 3.10", "unit 3.10"),
            ("passed", "", "unit"),
        ]
        assert (evaluation.reported, evaluation.missing, evaluation.files) == (["unit"], [], files)

    def test_an_undeclared_producer_doesnt_count(self):
        """Its results are a problem at the file, and its passes are not evidence."""
        files = [results_file("stranger", ("T-REQ-001-01", "passed")), results_file("unit")]
        evaluation = evaluate(("It.",), files)
        assert statuses(evaluation) == {"T-REQ-001-01": "unclaimed"}
        assert messages(evaluation)[0] == (
            "stranger.jsonl:1: producer `stranger` isn't declared in speccheck.toml (declared: unit)"
        )
        assert evaluate(("It.",), [files[0]], producer("x")).problems[0].message.endswith("(declared: x)")

    def test_no_producers_declared(self):
        """The message says none are."""
        empty = evidence.evaluate(make_specs("It."), make_config(), [results_file("x")], root=ROOT, runtime=True)
        assert "(declared: none)" in messages(empty)[0]

    def test_a_bad_claim_is_a_problem_and_not_evidence(self):
        """At the test's file and line, and the requirement stays unclaimed."""
        evaluation = evaluate(("It.",), [results_file("unit", ("T-REQ-001-09", "passed"))], runtime=False)
        assert statuses(evaluation) == {"T-REQ-001-01": "unclaimed"}
        assert messages(evaluation)[0].startswith("tests/test_x.py:1: T-REQ-001-09 isn't in any spec")

    def test_a_ci_job_counts_only_for_its_own_ids(self):
        """A recorded result for an ID outside `covers` is a problem at the job's name."""
        job = ci_job("publish", "T-REQ-001-01")
        files = [results_file("publish", ("T-REQ-001-01", "passed"), ("T-REQ-001-02", "passed"), kind="ci")]
        evaluation = evaluate(("It.", "Other. (unimplemented: later)"), files, UNIT, job)
        assert statuses(evaluation) == {"T-REQ-001-01": "passed", "T-REQ-001-02": "unimplemented"}
        assert messages(evaluation) == [
            "publish: T-REQ-001-02 isn't in `ci.publish.covers`, so job `publish` may not record it"
        ]

    def test_a_ci_job_that_didnt_record(self):
        """Its claim is in the config, so its requirement waits on it by name, and is claimed."""
        evaluation = evaluate(("It.",), [results_file("unit")], UNIT, ci_job("publish", "T-REQ-001-01"))
        status = evaluation.statuses[0]
        assert (status.status, status.waiting_on, status.claimed) == ("not run", ["publish"], True)

    def test_a_bad_id_in_a_ci_jobs_covers(self):
        """A typo in `covers` is a problem at the config, and claims nothing."""
        evaluation = evaluate(
            ("It. (unimplemented: later)",), [results_file("unit")], UNIT, ci_job("publish", "T-REQ-001-09")
        )
        assert messages(evaluation) == [
            "speccheck.toml: `ci.publish.covers`: T-REQ-001-09 isn't in any spec; check the number, or add it to spec 001"
        ]

    def test_evidence_carries_the_explanation(self):
        """Each piece of evidence keeps how its result says it proves the requirement."""
        evaluation = evaluate(("It.",), [results_file("unit", ("T-REQ-001-01", "passed"))])
        assert [e.how for e in evaluation.statuses[0].evidence] == ["tests/test_x.py::test_1 proves T-REQ-001-01"]

    def test_an_explanation_copying_a_requirement_is_a_problem(self):
        """In a results file, at the test, and in a CI job's config entry; neither claims."""
        unit = results.ResultsFile(
            producer="unit",
            source="unit.jsonl",
            results=[results.Result("t", [Claim("T-REQ-001-01", "it.")], "passed", file="t.py", line=4)],
        )
        job = config_producer("publish", Claim("T-REQ-001-02", "Other"))
        evaluation = evaluate(("It.", "Other."), [unit], UNIT, job)
        assert statuses(evaluation) == {"T-REQ-001-01": "unclaimed", "T-REQ-001-02": "unclaimed"}
        assert messages(evaluation)[:2] == [
            "speccheck.toml: `ci.publish.covers`: the explanation for T-REQ-001-02 is the text of T-REQ-001-02; "
            "describe how the test proves T-REQ-001-02",
            "t.py:4: the explanation for T-REQ-001-01 is the text of T-REQ-001-01; describe how the test proves T-REQ-001-01",
        ]

    def test_a_repeated_explanation_is_a_problem_but_still_evidence(self):
        """Across files, and between a test and a CI job's entry; the second owner is the one reported."""
        same = "the file is written"
        one = results.ResultsFile(
            producer="unit", results=[results.Result("a", [Claim("T-REQ-001-01", same)], "passed", file="a.py", line=1)]
        )
        two = results.ResultsFile(
            producer="unit",
            results=[results.Result("b", [Claim("T-REQ-001-02", same.upper())], "passed", file="b.py", line=2)],
        )
        evaluation = evaluate(
            ("It.", "Other.", "Third."),
            [one, two],
            UNIT,
            config_producer("publish", Claim("T-REQ-001-03", "the file is written.")),
        )
        assert statuses(evaluation) == {"T-REQ-001-01": "passed", "T-REQ-001-02": "passed", "T-REQ-001-03": "not run"}
        assert [(p.path, p.code) for p in evaluation.problems] == [("a.py", "how-duplicate"), ("b.py", "how-duplicate")]
        assert messages(evaluation)[0] == (
            "a.py:1: a gives the same explanation for T-REQ-001-01 as `ci.publish` does for T-REQ-001-03; "
            "each claim says how its own test proves its requirement"
        )

    def test_two_ci_jobs_with_one_explanation(self):
        """The second job's entry is a problem at the config, and still claims."""
        one = config_producer("publish", Claim("T-REQ-001-01", "same"))
        two = config_producer("deploy", Claim("T-REQ-001-02", "same"))
        evaluation = evaluate(("It.", "Other."), [results_file("unit")], UNIT, one, two)
        assert [(p.message.split(";")[0], p.code) for p in evaluation.problems] == [
            (
                "`ci.deploy.covers`: `ci.deploy` gives the same explanation for T-REQ-001-02 as `ci.publish` does for T-REQ-001-01",
                "how-duplicate",
            )
        ]
        assert evaluation.statuses[1].waiting_on == ["deploy"]

    def test_the_same_claim_in_several_files_is_one_claim(self):
        """One test in two legs, and a CI job's own result repeating its config entry."""
        legs = [results_file("unit", ("T-REQ-001-01", "passed")), results_file("unit", ("T-REQ-001-01", "passed"))]
        job = ci_job("publish", "T-REQ-001-02")
        recorded = results_file("publish", ("T-REQ-001-02", "passed"), kind="ci")
        evaluation = evaluate(("It.", "Other."), [*legs, recorded], UNIT, job)
        assert evaluation.problems == []

    def test_complete_names_the_missing_producers(self):
        """Every expected producer must report; one that didn't is a problem at the config."""
        docker = producer("docker", workflows=("other",))
        files = [results_file("unit", ("T-REQ-001-01", "passed"))]
        evaluation = evaluate(("It.",), files, UNIT, docker, complete=True)
        assert evaluation.missing == ["docker"]
        assert messages(evaluation) == [
            "speccheck.toml: producer `docker` didn't report; its job failed before uploading, was skipped, "
            "or was renamed (see `docker` in speccheck.toml)"
        ]
        assert evaluate(("It.",), files, UNIT, docker).missing == []

    def test_workflow_limits_what_is_expected(self):
        """With a workflow, a producer of another workflow isn't expected."""
        docker = producer("docker", workflows=("other",))
        files = [results_file("unit", ("T-REQ-001-01", "passed"))]
        evaluation = evaluate(("It.",), files, UNIT, docker, complete=True, workflow="ci")
        assert (evaluation.missing, evaluation.problems, evaluation.reported) == ([], [], ["unit"])

    def test_complete_with_nothing_to_expect_is_an_error(self):
        """A workflow no producer lists, or no producers at all, can't pass the missing-producer check."""
        docker = producer("docker", workflows=("other",))
        files = [results_file("unit", ("T-REQ-001-01", "passed"))]
        with pytest.raises(ConfigError, match="--workflow typo: no producer .* lists that workflow .*: ci, other"):
            evaluate(("It.",), files, UNIT, docker, complete=True, workflow="typo")
        with pytest.raises(ConfigError, match="declares no producers"):
            evidence.evaluate(make_specs("It."), make_config(), files, root=ROOT, runtime=True, complete=True)
        # Without --complete nothing is expected, so nothing is wrong
        assert evaluate(("It.",), files, UNIT, docker, workflow="typo").missing == []

    def test_problems_come_in_order(self):
        """Spec problems, then claim problems, then missing producers, then statuses."""
        spec = make_spec()
        make_requirement(spec, "It.")
        spec_problem = specs.Problem("specs/001-thing.md", 1, "spec")
        evaluation = evidence.evaluate(
            spec_set(spec, problems=[spec_problem]),
            make_config(UNIT, producer("docker")),
            [results_file("unit", ("T-REQ-001-09", "passed"))],
            root=ROOT,
            runtime=True,
            complete=True,
        )
        found = messages(evaluation)
        assert found[0] == "specs/001-thing.md:1: spec"
        assert "T-REQ-001-09 isn't in any spec" in found[1]
        assert "producer `docker` didn't report" in found[2]
        assert "T-REQ-001-01 was not run" in found[3] and "(waiting on: docker)" in found[3]
        assert len(found) == 4


def config_producer(name: str, *claims: Claim) -> config.Producer:
    """A CI job with exactly the given claims and explanations."""
    return config.Producer(name=name, specs=None, workflows=("ci",), claims=claims, ci_job=True)


def test_job_name():
    """By the results file's `ci.job_id`, as a string key; "" without an ID or a name for it."""
    names = {"7": "build"}
    assert evidence.job_name(results.ResultsFile(producer="u", ci={"job_id": 7}), names) == "build"
    assert evidence.job_name(results.ResultsFile(producer="u", ci={"job_id": 8}), names) == ""
    assert evidence.job_name(results.ResultsFile(producer="u", ci={}), names) == ""
    assert evidence.job_name(results.ResultsFile(producer="u"), names) == ""
