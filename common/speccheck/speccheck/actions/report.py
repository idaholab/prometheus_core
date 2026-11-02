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
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from speccheck import ci, evidence, jsonout
from speccheck.actions import _common
from speccheck.context import Context
from speccheck.evidence import Evaluation, Status
from speccheck.specs import plain

NAME = "report"
"""The command name."""
HELP = "Write the markdown report (--output FILE, --summary FILE) or --json"
"""The one-line help."""
SECTION = "ci"
"""The `--help` section."""
ORDER = 10
"""Its place in the section."""

MAX_CELL = 200
"""The longest text kept in one table cell, after which it is cut with `…`."""
MAX_EVIDENCE = 20
"""The most results listed for one requirement; the rest are counted."""
SUMMARY_LIMIT = 900 * 1024
"""The most bytes `--summary` writes: GitHub's step summary limit is 1 MiB."""
MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~&])")
"""Characters that mean something in markdown or HTML, escaped with a backslash."""
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
    parser.add_argument("--summary", metavar="FILE", help="Append the short form here, such as $GITHUB_STEP_SUMMARY")


def escape(text: str, limit: int = MAX_CELL) -> str:
    """Text safe in a markdown table cell: one line, special characters escaped, at most `limit` characters."""
    text = " ".join(str(text).split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return MARKDOWN_SPECIAL.sub(r"\\\1", text)


def code(text: str, limit: int = MAX_CELL, *, in_table: bool) -> str:
    """Text as an inline code span: one line, capped, with no backtick to close the span early.

    Markdown takes everything in a code span literally, so backslash escapes would show. The one
    exception is a table cell, where GFM splits on `|` before it reads the span, so a `|` there is
    written `\\|` (which GFM turns back into `|`).
    """
    text = " ".join(str(text).replace("`", "").split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"`{text.replace('|', chr(92) + '|') if in_table else text}`"


def safe_url(url: Any) -> str:
    """The URL when it is one this tool would have built (https, our run's form), else ""."""
    if not isinstance(url, str):
        return ""
    match = re.match(
        r"^(https://[A-Za-z0-9.-]+(?::\d+)?)/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/actions/runs/\d+(?:/(?:attempts|job)/\d+)?$",
        url,
    )
    if match is None or not ci.SERVER.match(match.group(1)):
        return ""
    return url


def _evidence_cell(status: Status) -> str:
    """Every result for one requirement: test, outcome, producer and leg, and a link to the job."""
    items = []
    for item in status.evidence[:MAX_EVIDENCE]:
        data = _common.evidence_json(item)
        label = "job" if data["kind"] == "ci" else "test"
        where = " ".join(part for part in (data["producer"], data["leg"]) if part)
        text = f"{label} {code(data['test'], 150, in_table=True)} {escape(data['outcome'])} in {escape(where)}"
        url = safe_url(data["url"])
        items.append(f"{text} ([job]({url}))" if url else text)
    if len(status.evidence) > MAX_EVIDENCE:
        items.append(f"and {len(status.evidence) - MAX_EVIDENCE} more")
    if not items and status.waiting_on:
        items.append("waiting on " + ", ".join(escape(name) for name in status.waiting_on))
    return "<br>".join(items) or "—"


def _row(status: Status) -> str:
    """One requirement's table row."""
    requirement = status.requirement
    mark = ICONS[status.status]
    return f"| {requirement.id} | {mark} {status.status} | {escape(requirement.text, 120)} | {_evidence_cell(status)} |"


TABLE_HEAD = "| ID | Status | Requirement | Evidence |\n|---|---|---|---|"
"""The header of every requirement table."""


def _order(status: Status) -> tuple[int, int]:
    """Sort key: statuses that need attention first, then spec order."""
    return (evidence.STATUSES.index(status.status), status.requirement.line)


def _inputs(evaluation: Evaluation) -> list[str]:
    """The lines saying what the report was built from: commits, runs and producers."""
    commits = sorted({(f.ci or {}).get("sha") or "" for f in evaluation.files} - {""})
    runs = sorted({safe_url((f.ci or {}).get("run_url")) for f in evaluation.files} - {""})
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


def full(title: str, evaluation: Evaluation) -> str:
    """The whole report: summary, problems, one table per spec, and the inputs."""
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
        lines += [f"## {number} {escape(titles[number])}", "", TABLE_HEAD]
        lines += [_row(status) for status in sorted(statuses, key=_order)]
        lines.append("")
    lines += ["## Inputs", "", *_inputs(evaluation), ""]
    return "\n".join(lines)


def summary(title: str, evaluation: Evaluation) -> str:
    """The short form for a step summary: counts, problems, and the rows that aren't fine, within the size limit."""
    counts = evaluation.counts()
    lines = [f"### {escape(title)}", "", evidence.summary_line(counts), ""]
    if evaluation.problems:
        lines += [f"**{len(evaluation.problems)} problems**", "", *_problems(evaluation), ""]
    attention = [s for s in evaluation.statuses if s.status in (evidence.FAILED, evidence.UNCLAIMED, evidence.NOT_RUN)]
    if attention:
        lines += [TABLE_HEAD, *(_row(s) for s in sorted(attention, key=_order)), ""]
    lines += ["The full report is in the `speccheck-report` artifact.", ""]
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > SUMMARY_LIMIT:
        cut = text.encode("utf-8")[:SUMMARY_LIMIT].decode("utf-8", "ignore")
        text = cut.rsplit("\n", 1)[0] + "\n\n… cut to fit the step summary; see the artifact.\n"
    return text


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Write the report; exit 0 unless the usage or config is bad."""
    evaluation = _common.evaluate(ctx, args, runtime=True)
    title = ctx.config().title
    if args.output:
        _write(ctx, args.output, full(title, evaluation), append=False)
    if args.summary:
        _write(ctx, args.summary, summary(title, evaluation), append=True)
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
    elif not args.output and not args.summary:
        # Unlike the files, stdout may be a CI log, where code spans keep a test name as written
        ctx.output.out.write("".join(plain(line) + "\n" for line in full(title, evaluation).splitlines()))
    else:
        ctx.output.summary(NAME, evidence.summary_line(evaluation.counts()), 0)
    return jsonout.EXIT_OK


def _write(ctx: Context, name: str, text: str, *, append: bool) -> None:
    """Write (or append) a file named on the command line."""
    path = Path(name) if Path(name).is_absolute() else ctx.cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as stream:
        stream.write(text)
