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

"""The step summary: one line of counts, a link to the report, then what failed, and nothing else.

See plan/design.md, "Step summary". `lint`, `check` and `verify` write it with `--summary FILE`;
the full report is the artifact's job.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from speccheck import ci
from speccheck.context import Context
from speccheck.markdown import code, escape, safe_artifact_url
from speccheck.specs import Problem

LIMIT = 900 * 1024
"""The most bytes written: GitHub's step summary limit is 1 MiB, and other steps may append too."""
CUT = "- … cut to fit the step summary; the full report has every problem"
"""The last entry when the problems don't all fit."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`--summary FILE` and `--report-url URL`."""
    parser.add_argument("--summary", metavar="FILE", help="Append the failures here, such as $GITHUB_STEP_SUMMARY")
    parser.add_argument(
        "--report-url",
        metavar="URL",
        help="With --summary, link the full report: an artifact URL of this run's repository",
    )


def _size(text: str) -> int:
    """`text`'s size as `write` writes it: a lone surrogate, as from a file name, becomes one `?`."""
    return len(text.encode("utf-8", "replace"))


def text(counts: str, problems: list[Problem], report_url: str = "") -> str:
    """The summary: the line, then one entry per problem, cut after a whole entry to stay under LIMIT."""
    head = f"{len(problems)} problem{'' if len(problems) == 1 else 's'}. " if problems else ""
    line = f"**speccheck:** {head}{escape(counts, 500)}"
    if report_url:
        line += f". Full report: [speccheck-report]({report_url})"
    lines = [line, ""]
    used = _size("\n".join(lines)) + _size(CUT) + 2
    for problem in problems:
        entry = f"- {code(str(problem), 500, in_table=False)}"
        size = _size(entry) + 1
        if used + size > LIMIT:
            lines.append(CUT)
            break
        lines.append(entry)
        used += size
    # A blank line after, so a later step's summary starts its own block
    return "\n".join(lines).rstrip("\n") + "\n\n"


def write(ctx: Context, args: argparse.Namespace, counts: str, problems: list[Problem]) -> None:
    """Append the summary to `--summary`, when given; link `--report-url` only when it is safe to."""
    name = getattr(args, "summary", None)
    if not name:
        return
    url = safe_artifact_url(getattr(args, "report_url", None), ci.repository_url(ctx.env))
    path = Path(name) if Path(name).is_absolute() else ctx.cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # The reader refuses lone surrogates; `replace` keeps any that slip past from losing the summary
    with path.open("a", encoding="utf-8", errors="replace") as stream:
        stream.write(text(counts, problems, url))
