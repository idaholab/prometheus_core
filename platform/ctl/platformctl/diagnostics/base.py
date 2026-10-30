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

"""The doctor framework: checks, results, dependencies and the runner of them all.

A check has an id (matching the hackathon `checks.md` where one exists), tags, the
targets it applies to, the checks it depends on, and `run(ctx) -> Result`. A failed
dependency skips the checks that depend on it. Checks report whether a value is set,
never the value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platformctl.context import Context

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"

# How a fix may be applied: `safe` (an assistant may run it), `yes` (after asking), `you` (the user does it).
FIX_SAFE, FIX_YES, FIX_YOU = "safe", "yes", "you"

TAG_PREFLIGHT, TAG_DIAGNOSE = "preflight", "diagnose"


@dataclass
class Result:
    status: str
    evidence: str = ""
    fix: str = ""
    skipped_because: str = ""


@dataclass
class Check:
    id: str
    area: str
    tags: tuple[str, ...]
    run: Callable[[Context], Result]
    depends_on: tuple[str, ...] = ()
    targets: tuple[str, ...] = ("compose",)
    fix_kind: str = FIX_YOU
    # Conflicts with the hackathon checks.md ids are renamed with an alias, never silently.
    aliases: tuple[str, ...] = ()


@dataclass
class Outcome:
    check: Check
    result: Result


@dataclass
class Registry:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        if any(c.id == check.id for c in self.checks):
            raise ValueError(f"duplicate check id {check.id!r}")
        self.checks.append(check)
        return check

    def find(self, ident: str) -> Check | None:
        for check in self.checks:
            if ident == check.id or ident in check.aliases:
                return check
        return None

    def validate(self) -> None:
        """Every dependency exists and comes earlier (so order is a valid run order)."""
        seen: set[str] = set()
        for check in self.checks:
            for dep in check.depends_on:
                if dep not in seen:
                    raise ValueError(f"check {check.id!r} depends on {dep!r}, which is missing or later")
            seen.add(check.id)


def run_checks(ctx: Context, registry: Registry, selected: list[Check]) -> list[Outcome]:
    """Run `selected` in registry order; skip a check whose dependency didn't pass or warn."""
    wanted = {c.id for c in selected}
    status: dict[str, str] = {}
    outcomes: list[Outcome] = []
    for check in registry.checks:
        if check.id not in wanted:
            continue
        blocked = next((d for d in check.depends_on if status.get(d) in (FAIL, SKIP)), None)
        if ctx.config.get("PLATFORM_TARGET") not in check.targets:
            result = Result(SKIP, "does not apply to this target", skipped_because="target")
        elif blocked:
            result = Result(SKIP, f"needs {blocked}", skipped_because=blocked)
        else:
            result = check.run(ctx)
        status[check.id] = result.status
        outcomes.append(Outcome(check, result))
    return outcomes


def counts(outcomes: list[Outcome]) -> dict[str, int]:
    tally = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for outcome in outcomes:
        tally[outcome.result.status] += 1
    return {k.lower(): v for k, v in tally.items()}
