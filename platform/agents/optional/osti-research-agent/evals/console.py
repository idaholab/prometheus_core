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

"""Rich terminal rendering for the evaluation: the summary table, the failure
list, and one styled line per finished question.

Built on the same numbers as ``report.py`` (``failures``, the summary rows),
which stays standard-library only for the plain-text and Markdown output.
``rich`` handles terminals itself: off a terminal (CI, ``| tee``) it drops the
colors and keeps the table readable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from evals import report as render

_JUDGE_LABELS = (
    ("judge_groundedness", "ground"),
    ("judge_completeness", "complete"),
    ("judge_reference_agreement", "ref"),
)


# Off a terminal rich assumes 80 columns, which wraps the summary table; logs
# and files have no width limit, so give them room.
_PIPE_WIDTH = 160


def make_console(stderr: bool = False) -> Console:
    console = Console(stderr=stderr, highlight=False, soft_wrap=False)
    if not console.is_terminal:
        console.width = _PIPE_WIDTH
    return console


def _score_style(value: Optional[int]) -> str:
    if not isinstance(value, int):
        return "dim"
    return "green" if value >= render.JUDGE_PASS_SCORE else "red"


def _fraction_style(cell: str) -> str:
    """Green when every question passed (n/n), yellow for some, red for none."""
    try:
        done, total = (int(x) for x in cell.split("/"))
    except ValueError:
        return ""
    if total and done == total:
        return "green"
    return "red" if done == 0 else "yellow"


def _rate_style(cell: str) -> str:
    try:
        value = float(cell)
    except ValueError:
        return "dim"
    if value >= 1.0:
        return "green"
    return "yellow" if value >= 0.5 else "red"


def _judge_style(cell: str) -> str:
    try:
        value = float(cell)
    except ValueError:
        return "dim"
    return "green" if value >= render.JUDGE_PASS_SCORE else "red"


# Column name -> how to color its cells.
_COLUMN_STYLES = {
    "passed": _fraction_style,
    "status": _fraction_style,
    "sources": _fraction_style,
    "cite links": _rate_style,
    "source hit": _rate_style,
    "fact match": _rate_style,
    "ground": _judge_style,
    "complete": _judge_style,
    "ref agree": _judge_style,
}


def summary_table(report: Dict[str, Any]) -> Table:
    table = Table(
        title="Per-engine summary",
        title_style="bold",
        header_style="bold cyan",
        show_lines=False,
    )
    for name in render._SUMMARY_HEADER:
        justify = "left" if name == "engine" else "right"
        table.add_column(name, justify=justify, no_wrap=True)
    for row in render._summary_rows(report):
        cells = []
        for name, cell in zip(render._SUMMARY_HEADER, row):
            style = _COLUMN_STYLES.get(name, lambda _c: "")(str(cell))
            cells.append(Text(str(cell), style="bold" if name == "engine" else style))
        table.add_row(*cells)
    return table


def failures_table(report: Dict[str, Any], *, max_failures: int = 20) -> Optional[Table]:
    failed = render._failed_records(report)
    if not failed:
        return None
    table = Table(
        title=f"Failed ({len(failed)})",
        title_style="bold red",
        header_style="bold",
        expand=True,
    )
    table.add_column("engine", no_wrap=True)
    table.add_column("question", style="bold", no_wrap=True)
    table.add_column("why", ratio=1)
    for record in failed[:max_failures]:
        table.add_row(
            str(record.get("engine")),
            str(record.get("id")),
            _why(record),
        )
    if len(failed) > max_failures:
        table.caption = f"... and {len(failed) - max_failures} more in report.md"
    return table


def _why(record: Dict[str, Any]) -> Text:
    """Each failure reason in red, with its explanation after it in the
    default color, one reason per line."""
    text, judge_shown = Text(), False
    for index, (reason, detail) in enumerate(render.explained_failures(record)):
        if index:
            text.append("\n")
        text.append(reason, style="red")
        if reason.startswith("judge "):
            if judge_shown:
                continue
            judge_shown = True
        if detail:
            text.append(f": {detail}")
    return text


def print_summary(console: Console, report: Dict[str, Any]) -> None:
    """The end-of-run report: header panel, summary table, failures, caveats."""
    total = len(report.get("records", []))
    passed = total - len(render._failed_records(report))
    complete = report.get("complete", True)
    style = "green" if total and passed == total else ("yellow" if passed else "red")
    header = Text.assemble(
        ("OSTI evaluation  ", "bold"),
        (f"{passed}/{total} passed", f"bold {style}"),
        f"  ·  {report.get('questions', 0)} question(s)  ·  engines: "
        f"{', '.join(report.get('engines', []))}",
    )
    if not complete:
        header.append("  ·  partial run", style="bold yellow")
    console.print(Panel(header, expand=False, border_style=style))
    console.print(summary_table(report))

    failed = failures_table(report)
    if failed is not None:
        console.print(failed)
    else:
        console.print(Text("Every question passed.", style="bold green"))

    judge_errors = [r for r in report.get("records", []) if r.get("judge_error")]
    if judge_errors:
        console.print(
            Text(
                f"Judge errors ({len(judge_errors)}): those questions are unjudged "
                "and count as failed.",
                style="yellow",
            )
        )
    console.print(Text(render._CAVEAT, style="dim"))


def result_line(record: Dict[str, Any]) -> Text:
    """One styled line for a finished question."""
    reasons = render.failures(record)
    line = Text()
    line.append(" PASS " if not reasons else " FAIL ", style="bold white on green"
                if not reasons else "bold white on red")
    line.append(f" {record.get('id')}", style="bold")
    line.append(f"  {record.get('status')}", style="dim")
    wall_s = record.get("wall_s")
    if isinstance(wall_s, (int, float)):
        line.append(f"  {render._duration(wall_s)}", style="dim")
    scores = [(label, record.get(key)) for key, label in _JUDGE_LABELS
              if isinstance(record.get(key), int)]
    if scores:
        line.append("  judge")
        for label, value in scores:
            line.append(f" {label}=")
            line.append(str(value), style=_score_style(value))
    elif record.get("judge_error"):
        line.append("  judge error", style="yellow")
    if reasons:
        line.append("  " + "; ".join(reasons), style="red")
    return line


def plain_summary(report: Dict[str, Any]) -> str:
    """Render ``print_summary`` to plain text (tests, logs)."""
    console = Console(width=160, color_system=None, highlight=False, record=True,
                      file=_NullFile())
    print_summary(console, report)
    return console.export_text()


class _NullFile:
    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        pass
