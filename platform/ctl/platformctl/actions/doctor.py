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

"""`doctor`: diagnose common problems. It reports fixes and never applies them."""

from __future__ import annotations

import argparse

from platformctl import jsonout
from platformctl.context import Context
from platformctl.diagnostics import default_registry
from platformctl.diagnostics.base import FAIL, WARN, Outcome, counts, run_checks

NAME = "doctor"
"""The command's name."""
HELP = "Diagnose common problems and say how to fix them"
"""The command's one-line description in `--help`."""
SECTION = "troubleshoot"
"""The `--help` section the command is listed in."""
ORDER = 10
"""Where the command sits within its section; lower is listed first."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add `doctor`'s positional check ids and its options to its parser."""
    parser.add_argument("checks", nargs="*", metavar="check-id", help="Run only these checks")
    parser.add_argument("--tag", choices=["preflight", "diagnose"], help="Only the checks with this tag")
    parser.add_argument("--list", action="store_true", help="List the check ids, their tags and targets")


def _select(registry, ids: list[str], tag: str | None):
    """Choose the checks to run from the ids and tag given, and name the ids that match none."""
    if ids:
        found = [registry.find(i) for i in ids]
        unknown = [i for i, c in zip(ids, found, strict=True) if c is None]
        return [c for c in found if c is not None], unknown
    return [c for c in registry.checks if tag is None or tag in c.tags], []


def _listing(registry) -> list[dict]:
    """Describe every registered check for `--list`."""
    return [{"id": c.id, "area": c.area, "tags": list(c.tags), "targets": list(c.targets)} for c in registry.checks]


def _check_json(outcome: Outcome) -> dict:
    """Describe one check's outcome as the JSON object `doctor --json` prints."""
    check, result = outcome.check, outcome.result
    return {
        "id": check.id,
        "area": check.area,
        "tags": list(check.tags),
        "status": result.status,
        "evidence": result.evidence,
        "fix": result.fix,
        "fix_kind": check.fix_kind,
        "skipped_because": result.skipped_because,
    }


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Run the selected checks, print them as text or JSON, and return the exit code (1 on any FAIL)."""
    registry = default_registry()
    out = ctx.output

    if args.list:
        listing = _listing(registry)
        if ctx.json_mode:
            jsonout.emit(jsonout.result("doctor", ctx.platform_info(), checks=listing), out.out, out.scrubber.scrub)
        else:
            for row in listing:
                out.write(f"{row['id']:<24} {','.join(row['tags']):<20} {','.join(row['targets'])}")
        return jsonout.EXIT_OK

    selected, unknown = _select(registry, args.checks, args.tag)
    if unknown:
        message = "unknown check id: " + ", ".join(unknown)
        hint = "List them with: ./platformctl doctor --list"
        if ctx.json_mode:
            jsonout.emit(
                jsonout.error_object("doctor", ctx.platform_info(), "usage", message, hint), out.out, out.scrubber.scrub
            )
        else:
            out.error(message, hint)
        return jsonout.EXIT_USAGE

    outcomes = run_checks(ctx, registry, selected)
    tally = counts(outcomes)
    problems = tally["fail"] + tally["warn"]

    if ctx.json_mode:
        body = jsonout.result("doctor", ctx.platform_info(), checks=[_check_json(o) for o in outcomes], counts=tally)
        jsonout.emit(body, out.out, out.scrubber.scrub)
    else:
        for outcome in outcomes:
            line = f"{outcome.result.status:<5} {outcome.check.id:<22} {outcome.result.evidence}"
            out.info(line.rstrip())
            if outcome.result.status in (FAIL, WARN) and outcome.result.fix:
                out.info(f"      fix: {outcome.result.fix}")
        if problems:
            noun = "problem" if problems == 1 else "problems"
            out.info(f"\n{problems} {noun}: run the fixes above, then ./platformctl doctor again")
        else:
            out.info("\nNo problems found.")
    # doctor exits 1 on any FAIL, 0 with only WARN.
    return jsonout.EXIT_FAIL if tally["fail"] else jsonout.EXIT_OK
