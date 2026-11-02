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

"""`speccheck report`: the markdown report of where each requirement is proven, with links to the jobs.

It fails only on bad usage or a bad config. A bad results file shows up in the report as a problem.
Everything taken from a results file is escaped before it goes into markdown, and capped in length.
The step summary is not this report's: `lint`, `check` and `verify` write it with `--summary`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from speccheck import ci, evidence, jsonout
from speccheck.actions import _common
from speccheck.claims import MAX_HOW
from speccheck.context import Context
from speccheck.evidence import Evaluation, Status
from speccheck.markdown import code, escape, safe_url
from speccheck.specs import plain

NAME = "report"
"""The command name."""
HELP = "Write the full markdown report (--output FILE) or --json"
"""The one-line help."""
SECTION = "ci"
"""The `--help` section."""
ORDER = 10
"""Its place in the section."""

MAX_EVIDENCE = 20
"""The most results listed for one requirement; the rest are counted."""
ICONS = {
    evidence.PASSED: "✅",
    evidence.FAILED: "❌",
    evidence.UNCLAIMED: "❌",
    evidence.NOT_RUN: "⏸",
    evidence.CLAIMED: "☑",
    evidence.PLANNED: "🗓",
    evidence.UNTESTED_STATUS: "⚠",
    evidence.RETIRED: "—",
}
"""One mark per status, beside its name."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The results files, the scope, and where to write."""
    _common.add_inputs(parser)
    _common.add_scope(parser)
    parser.add_argument("--output", metavar="FILE", help="Write the full report here (default: stdout)")


def _evidence_cell(status: Status, base: str) -> str:
    """Every result for one requirement: test, outcome, producer and leg, and a link to the job."""
    items = []
    for item in status.evidence[:MAX_EVIDENCE]:
        data = _common.evidence_json(item)
        label = "job" if data["kind"] == "ci" else "test"
        where = " ".join(part for part in (data["producer"], data["leg"]) if part)
        text = f"{label} {code(data['test'], 150, in_table=True)} {escape(data['outcome'])} in {escape(where)}"
        url = safe_url(data["url"], base)
        items.append(f"{text} ([job]({url}))" if url else text)
    if len(status.evidence) > MAX_EVIDENCE:
        items.append(f"and {len(status.evidence) - MAX_EVIDENCE} more")
    if not items and status.waiting_on:
        items.append("waiting on " + ", ".join(escape(name) for name in status.waiting_on))
    return "<br>".join(items) or "—"


def _row(status: Status, base: str) -> str:
    """One requirement's table row."""
    requirement = status.requirement
    mark = ICONS[status.status]
    return f"| {requirement.id} | {mark} {status.status} | {escape(requirement.text, 120)} | {_evidence_cell(status, base)} |"


TABLE_HEAD = "| ID | Status | Requirement | Evidence |\n|---|---|---|---|"
"""The header of every requirement table."""


def _order(status: Status) -> tuple[int, int]:
    """Sort key: statuses that need attention first, then spec order."""
    return (evidence.STATUSES.index(status.status), status.requirement.line)


def _hows(statuses: list[Status]) -> list[str]:
    """Below a spec's table, each claim with how it proves its requirement, each claimant once per ID."""
    lines: list[str] = []
    for status in statuses:
        seen: set[tuple[str, str]] = set()
        for item in status.evidence:
            key = (item.result.test, item.how)
            if key in seen or not item.how:
                continue
            seen.add(key)
            label = "job" if item.result.kind == "ci" else "test"
            lines.append(
                f"- **{status.requirement.id}**, {label} {code(item.result.test, 150, in_table=False)}: "
                f"{escape(item.how, MAX_HOW)}"
            )
    return ["How each claim proves its requirement:", "", *lines, ""] if lines else []


def _inputs(evaluation: Evaluation, base: str) -> list[str]:
    """The lines saying what the report was built from: commits, runs and producers."""
    commits = sorted({(f.ci or {}).get("sha") or "" for f in evaluation.files} - {""})
    runs = sorted({safe_url((f.ci or {}).get("run_url"), base) for f in evaluation.files} - {""})
    run_links = [f"[{escape(run.rsplit('/runs/', 1)[1])}]({run})" for run in runs]
    lines = [
        f"- Commit: {', '.join(escape(c[:12]) for c in commits) or 'unknown (not run in CI)'}",
        f"- Runs: {', '.join(run_links) or 'none'}",
        f"- Producers reported: {', '.join(escape(p) for p in evaluation.reported) or 'none'}",
    ]
    if evaluation.missing:
        lines.append(f"- Producers missing: {', '.join(escape(p) for p in evaluation.missing)}")
    return lines


def _problems(evaluation: Evaluation) -> list[str]:
    """The problems as a markdown list."""
    return [f"- {code(str(p), 300, in_table=False)}" for p in evaluation.problems]


def full(title: str, evaluation: Evaluation, base: str = "") -> str:
    """The whole report: summary, problems, one table per spec with its claims' explanations, and the inputs."""
    counts = evaluation.counts()
    lines = [f"# {escape(title)}", "", evidence.summary_line(counts), ""]
    lines += [" · ".join(f"{ICONS[s]} {s}: {n}" for s, n in counts.items() if n), ""]
    if evaluation.problems:
        lines += [f"## Problems ({len(evaluation.problems)})", "", *_problems(evaluation), ""]
    by_spec: dict[str, list[Status]] = {}
    titles: dict[str, str] = {}
    for status in evaluation.statuses:
        spec = status.requirement.spec
        by_spec.setdefault(spec.number, []).append(status)
        titles[spec.number] = spec.title
    for number, statuses in by_spec.items():
        ordered = sorted(statuses, key=_order)
        lines += [f"## {number} {escape(titles[number])}", "", TABLE_HEAD]
        lines += [_row(status, base) for status in ordered]
        lines.append("")
        lines += _hows(ordered)
    lines += ["## Inputs", "", *_inputs(evaluation, base), ""]
    return "\n".join(lines)


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Write the report; exit 0 unless the usage or config is bad."""
    evaluation = _common.evaluate(ctx, args, runtime=True)
    title = ctx.config().title
    base = ci.repository_url(ctx.env)
    if args.output:
        _write(ctx, args.output, full(title, evaluation, base))
    if ctx.output.json_mode:
        body = jsonout.envelope(
            NAME,
            True,
            evaluation.problems,
            title=title,
            counts=evaluation.counts(),
            requirements=_common.statuses_json(evaluation),
            producers={"reported": evaluation.reported, "missing": evaluation.missing},
        )
        jsonout.emit(body, ctx.output.out)
    elif not args.output:
        # Unlike the file, stdout may be a CI log, where code spans keep a test name as written
        ctx.output.out.write("".join(plain(line) + "\n" for line in full(title, evaluation, base).splitlines()))
    else:
        ctx.output.summary(NAME, evidence.summary_line(evaluation.counts()), 0)
    return jsonout.EXIT_OK


def _write(ctx: Context, name: str, text: str) -> None:
    """Write a file named on the command line, making its folder."""
    path = Path(name) if Path(name).is_absolute() else ctx.cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # The reader refuses lone surrogates; `replace` keeps any that slip past from losing the report
    with path.open("w", encoding="utf-8", errors="replace") as stream:
        stream.write(text)
