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

"""Turn specs, the config and results files into one status per requirement, and the problems.

See plan/design.md, "How a requirement's status is decided". `check` and `verify` both call
`evaluate`. `check` is the static layer: it asks whether every requirement is claimed. `verify`
also asks whether a claim passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from speccheck.config import Config, ConfigError, Producer
from speccheck.results import Result, ResultsFile
from speccheck.specs import UNTESTED, Problem, Requirement, SpecSet, rel

PASSED, FAILED, NOT_RUN, UNCLAIMED, CLAIMED = "passed", "failed", "not run", "unclaimed", "claimed"
"""The statuses evidence decides. `claimed` is only for `check`, which sees claims but not outcomes."""
PLANNED, UNTESTED_STATUS, RETIRED = "planned", "untested", "retired"
"""The statuses the spec decides, when nothing claims the requirement."""
STATUSES = (FAILED, UNCLAIMED, NOT_RUN, CLAIMED, PASSED, PLANNED, UNTESTED_STATUS, RETIRED)
"""Every status, worst first: the order of the report and of the summary counts."""


@dataclass(frozen=True)
class Evidence:
    """One result that claims a requirement, with the file it came from."""

    result: Result
    """The claiming test or CI job and its outcome."""
    source: ResultsFile
    """The results file: producer, leg and links."""


@dataclass
class Status:
    """One requirement's status and what decided it."""

    requirement: Requirement
    """The requirement."""
    status: str
    """One of STATUSES."""
    evidence: list[Evidence] = field(default_factory=list)
    """Every result that claims it, passing or not."""
    waiting_on: list[str] = field(default_factory=list)
    """For `not run`: the producers that could have claimed it and didn't report."""
    claimed: bool = False
    """Whether anything claims it: a result, or a CI job in the config."""


@dataclass
class Evaluation:
    """Everything `check`, `verify` and `report` need."""

    statuses: list[Status]
    """One per requirement, in spec order."""
    problems: list[Problem]
    """Spec format problems, claim problems and failing requirements, in that order."""
    reported: list[str]
    """The producers that wrote at least one results file, sorted."""
    missing: list[str]
    """With `complete`, the expected producers that didn't report, sorted."""
    files: list[ResultsFile] = field(default_factory=list)
    """The results files read."""

    def counts(self) -> dict[str, int]:
        """How many requirements have each status, every status listed."""
        counts = dict.fromkeys(STATUSES, 0)
        for status in self.statuses:
            counts[status.status] += 1
        return counts


def summary_line(counts: dict[str, int]) -> str:
    """ "12 requirements: 10 passed, 1 planned, 1 untested", leaving out statuses with none."""
    total = sum(counts.values())
    parts = [f"{count} {status}" for status, count in counts.items() if count]
    noun = "requirement" if total == 1 else "requirements"
    return f"{total} {noun}" + (f": {', '.join(parts)}" if parts else "")


def claim_problem(claimed: str, producer: Producer | None, specs: SpecSet) -> str:
    """Why `producer` may not claim the ID `claimed`, or "" when it may. The message says what to do."""
    match = specs.syntax.id.fullmatch(claimed)
    if match is None:
        return f"`{claimed}` is not an ID of this folder; IDs read like `{specs.syntax.example()}`"
    requirement = specs.requirements.get(claimed)
    if requirement is None:
        return f"{claimed} isn't in any spec; check the number, or add it to spec {match.group('number')}"
    if requirement.retired:
        return f"{claimed} is retired; claim what replaced it"
    if producer is not None and not producer.may_claim(requirement.spec.number):
        return (
            f"{claimed} is in spec {requirement.spec.number}, which producer `{producer.name}` may not claim; "
            f"add it to `producers.{producer.name}.specs` or claim it from another producer"
        )
    return ""


def _where(result: Result) -> tuple[str, int]:
    """Where a claim is, for a problem: its file and line, or its test name when there is no file."""
    return (result.file or result.test), result.line


HINTS = {
    "failed": "fix the test or the code it checks",
    "error": "fix the setup or teardown that raised",
    "skipped": "make the test run here, or claim the requirement from a leg where it runs",
    "xfailed": "an expected failure proves nothing; fix it and remove the xfail",
    "xpassed": "an unexpected pass isn't a pass; remove the xfail",
    "deselected": "run it: drop the `-k`/`-m` filter or the test's path argument that left it out",
    "collected": "the run ended before it ran; look for an earlier crash or `-x`",
}
"""What to do about each outcome that isn't a pass."""


def _hint(found: list[Evidence]) -> str:
    """One hint per distinct outcome among `found`, in the order seen."""
    outcomes = dict.fromkeys(e.result.outcome for e in found)
    hints = [HINTS[o] for o in outcomes if o in HINTS]
    return f"; to fix: {'; or '.join(hints)}" if hints else ""


def _describe(evidence: Evidence) -> str:
    """ "tests/test_x.py::test_y skipped in speccheck-requirements 3.12"."""
    leg = (evidence.source.ci or {}).get("leg") or ""
    where = f"{evidence.source.producer} {leg}".strip()
    return f"{evidence.result.test} {evidence.result.outcome} in {where}"


def evaluate(
    specs: SpecSet,
    config: Config,
    files: list[ResultsFile],
    *,
    root,
    runtime: bool,
    complete: bool = False,
    workflow: str | None = None,
) -> Evaluation:
    """Decide every requirement's status. `runtime` is `verify` (outcomes count); otherwise `check`.

    With `complete`, every producer expected in `workflow` (every producer, without one) must have
    reported, and a requirement nobody among them claims fails.
    """
    problems = list(specs.problems)
    config_name = rel(config.path, root)

    # Claims from results files, kept only when the producer is declared and may claim the ID.
    claims: dict[str, list[Evidence]] = {id_: [] for id_ in specs.requirements}
    reported = sorted({f.producer for f in files})
    for results_file in files:
        producer = config.producers.get(results_file.producer)
        if producer is None:
            known = ", ".join(sorted(config.producers)) or "none"
            message = f"producer `{results_file.producer}` isn't declared in {config_name} (declared: {known})"
            problems.append(Problem(results_file.source, 1, message, "producer-undeclared"))
            continue
        for result in results_file.results:
            for claimed in result.covers:
                why = claim_problem(claimed, producer, specs)
                if not why and producer.ci_job and claimed not in producer.covers:
                    why = f"{claimed} isn't in `ci.{producer.name}.covers`, so job `{producer.name}` may not record it"
                if why:
                    path, line = _where(result)
                    problems.append(Problem(path, line, why, "claim-invalid"))
                else:
                    claims[claimed].append(Evidence(result, results_file))

    # CI jobs claim in the config itself, so their claims are known even when they didn't report.
    config_claims: dict[str, list[str]] = {id_: [] for id_ in specs.requirements}
    for producer in config.producers.values():
        for claimed in producer.covers:
            why = claim_problem(claimed, None, specs)
            if why:
                problems.append(Problem(config_name, 0, f"`ci.{producer.name}.covers`: {why}", "config-claim-invalid"))
            else:
                config_claims[claimed].append(producer.name)

    expected = [p.name for p in (config.producers_in(workflow) if workflow else config.producers.values())]
    if complete and not expected:
        # An empty expectation would pass the missing-producer check for nothing, so a typo or a renamed
        # workflow would turn the check off without a sound.
        if workflow:
            known = ", ".join(sorted({w for p in config.producers.values() for w in p.workflows})) or "none"
            raise ConfigError(
                f"--workflow {workflow}: no producer in {config_name} lists that workflow (workflows listed: {known})"
            )
        raise ConfigError(f"--complete: {config_name} declares no producers, so there is nothing to expect")
    missing = sorted(set(expected) - set(reported)) if complete else []
    for name in missing:
        message = (
            f"producer `{name}` didn't report; its job failed before uploading, was skipped, or was renamed "
            f"(see `{name}` in {config_name})"
        )
        problems.append(Problem(config_name, 0, message, "producer-missing"))

    statuses = []
    status_problems: list[Problem] = []
    for requirement in specs.requirements.values():
        status = _decide(requirement, claims[requirement.id], config_claims[requirement.id], config, reported, runtime)
        statuses.append(status)
        status_problems += _problems_of(status, root, complete)
    problems += status_problems
    return Evaluation(statuses=statuses, problems=problems, reported=reported, missing=missing, files=files)


def _decide(
    requirement: Requirement,
    evidence: list[Evidence],
    config_claims: list[str],
    config: Config,
    reported: list[str],
    runtime: bool,
) -> Status:
    """One requirement's status, from its claims and its markers."""
    claimed = bool(evidence or config_claims)
    if requirement.retired:
        return Status(requirement, RETIRED, evidence)
    if not claimed:
        if requirement.planned:
            return Status(requirement, PLANNED)
        if requirement.untested:
            return Status(requirement, UNTESTED_STATUS)
        # In verify, a test run that didn't report could still claim it, so say so instead of calling it
        # unclaimed. check reads a collect-only run, which sees every claim: there, unclaimed is unclaimed.
        waiting = (
            []
            if not runtime
            else sorted(
                p.name
                for p in config.producers.values()
                if not p.ci_job and p.name not in reported and p.may_claim(requirement.spec.number)
            )
        )
        return Status(requirement, NOT_RUN if waiting else UNCLAIMED, waiting_on=waiting)
    if not runtime:
        return Status(requirement, CLAIMED, evidence, claimed=True)
    if any(e.result.outcome == "passed" for e in evidence):
        return Status(requirement, PASSED, evidence, claimed=True)
    if evidence:
        return Status(requirement, FAILED, evidence, claimed=True)
    waiting = sorted(name for name in config_claims if name not in reported)
    return Status(requirement, NOT_RUN, evidence, waiting_on=waiting, claimed=True)


def _problems_of(status: Status, root, complete: bool) -> list[Problem]:
    """The problems a status is in this check, each saying what to do about it."""
    requirement = status.requirement
    name = rel(requirement.spec.path, root)
    line = requirement.line
    problems = []
    if status.claimed and requirement.untested:
        problems.append(
            Problem(name, line, f"{requirement.id} is claimed, so remove `{UNTESTED}`", "untested-marker-stale")
        )
    if status.claimed and requirement.planned:
        problems.append(
            Problem(name, line, f"{requirement.id} is claimed, so remove its `(planned: ...)`", "planned-marker-stale")
        )
    if status.status == UNCLAIMED:
        message = (
            f'{requirement.id} is not claimed; add `@pytest.mark.covers("{requirement.id}")` to a test that '
            f"proves it, or mark it `{UNTESTED}` in the spec"
        )
        problems.append(Problem(name, line, message, UNCLAIMED))
    elif status.status == FAILED:
        seen = "; ".join(_describe(e) for e in status.evidence[:5])
        more = f" (and {len(status.evidence) - 5} more)" if len(status.evidence) > 5 else ""
        problems.append(
            Problem(name, line, f"{requirement.id} has no passing result: {seen}{more}{_hint(status.evidence)}", FAILED)
        )
    elif status.status == NOT_RUN and complete:
        waiting = ", ".join(status.waiting_on) or "none"
        message = f"{requirement.id} was not run: nothing that reported claims it (waiting on: {waiting})"
        problems.append(Problem(name, line, message, "not-run"))
    return problems
