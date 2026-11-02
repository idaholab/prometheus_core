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

"""What `check`, `verify` and `report` share: their inputs, and the JSON for an evaluation.

Not a command: it has no NAME, so `actions.discover()` skips it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from speccheck import evidence, jsonout, results
from speccheck.context import Context
from speccheck.evidence import Evaluation
from speccheck.specs import Problem


def add_inputs(parser: argparse.ArgumentParser) -> None:
    """The results files or folders to read."""
    parser.add_argument(
        "inputs", nargs="*", metavar="RESULTS", help="Results files, or folders searched for *.jsonl (default: none)"
    )


def add_scope(parser: argparse.ArgumentParser) -> None:
    """`--complete` and `--workflow`."""
    parser.add_argument(
        "--complete",
        action="store_true",
        help="Also fail on a producer that didn't report and on a requirement nothing that reported claims",
    )
    parser.add_argument(
        "--workflow",
        metavar="NAME",
        help="With --complete, expect only the producers that list this workflow (default: every producer)",
    )


def evaluate(ctx: Context, args: argparse.Namespace, *, runtime: bool) -> Evaluation:
    """Read the specs and results files and decide every requirement's status."""
    config = ctx.config()
    specs = ctx.specs()
    paths = [Path(p) if Path(p).is_absolute() else ctx.cwd / p for p in args.inputs]
    files, problems = results.read_all(paths)
    for results_file in files:
        results_file.source = _relative(results_file.source, ctx.cwd)
    problems = [_relocate(p, ctx.cwd) for p in problems]
    evaluation = evidence.evaluate(
        specs,
        config,
        files,
        root=ctx.cwd,
        runtime=runtime,
        complete=getattr(args, "complete", False),
        workflow=getattr(args, "workflow", None),
    )
    evaluation.problems = problems + evaluation.problems
    return evaluation


def _relative(path: str, cwd: Path) -> str:
    """A path relative to where speccheck runs, when it is under it."""
    try:
        return Path(path).resolve().relative_to(cwd.resolve()).as_posix()
    except ValueError:
        return path


def _relocate(problem: Problem, cwd: Path) -> Problem:
    """The problem with its path made relative to where speccheck runs."""
    return Problem(_relative(problem.path, cwd), problem.line, problem.message, problem.code)


def evidence_json(item: evidence.Evidence) -> dict[str, Any]:
    """One claiming result, for `--json` and the report."""
    ci = item.source.ci or {}
    return {
        "test": item.result.test,
        "kind": item.result.kind,
        "file": item.result.file,
        "line": item.result.line,
        "outcome": item.result.outcome,
        "producer": item.source.producer,
        "leg": ci.get("leg") or "",
        "job": ci.get("job") or "",
        "url": ci.get("job_url") or ci.get("run_url") or "",
    }


def statuses_json(evaluation: Evaluation) -> list[dict[str, Any]]:
    """Every requirement's status, for `--json`."""
    return [
        {
            "id": status.requirement.id,
            "spec": status.requirement.spec.number,
            "status": status.status,
            "text": status.requirement.text,
            "evidence": [evidence_json(item) for item in status.evidence],
            "waiting_on": status.waiting_on,
        }
        for status in evaluation.statuses
    ]


def finish(ctx: Context, command: str, evaluation: Evaluation) -> int:
    """Print the problems and the summary (or the JSON object) for `check` or `verify`, and return the exit code."""
    ok = not evaluation.problems
    text = evidence.summary_line(evaluation.counts())
    if evaluation.reported or evaluation.missing:
        text += f"; reported: {', '.join(evaluation.reported) or 'none'}"
        if evaluation.missing:
            text += f"; missing: {', '.join(evaluation.missing)}"
    if ctx.output.json_mode:
        body = jsonout.envelope(
            command,
            ok,
            evaluation.problems,
            counts=evaluation.counts(),
            requirements=statuses_json(evaluation),
            producers={"reported": evaluation.reported, "missing": evaluation.missing},
        )
        jsonout.emit(body, ctx.output.out)
    for status in evaluation.statuses:
        ctx.output.detail(f"{status.requirement.id}  {status.status}")
    ctx.output.problems(evaluation.problems)
    ctx.output.summary(command, text, len(evaluation.problems))
    return jsonout.EXIT_OK if ok else jsonout.EXIT_PROBLEMS
