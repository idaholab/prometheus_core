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

"""Progress display for an evaluation run, on stderr, using ``rich``.

On a terminal: a live bar redrawn every second, so the clock keeps moving
through long parses -

    ⠋ deepagent uq-fp-... ━━━━╺━━━ 3/10 30% 0:12:04 ETA 0:28:10 q 0:01:30 Parsing paper...

with each finished question and any warning printed above it. Off a terminal
(CI, a log file) it prints one plain line per question start and finish
instead, so logs stay readable.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress as RichProgress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

from evals.console import make_console, result_line

REFRESH_PER_SECOND = 1


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


class _EtaColumn(ProgressColumn):
    """ETA from the average time of the questions finished so far."""

    def __init__(self, progress: "Progress"):
        super().__init__()
        self._progress = progress

    def render(self, task: Task) -> Text:
        eta = self._progress.eta()
        return Text("ETA " + (_clock(eta) if eta is not None else "--"), style="cyan")


class _QuestionClockColumn(ProgressColumn):
    def __init__(self, progress: "Progress"):
        super().__init__()
        self._progress = progress

    def render(self, task: Task) -> Text:
        if not self._progress.qid:
            return Text("")
        return Text("q " + _clock(time.monotonic() - self._progress.question_started),
                    style="dim")


class Progress:
    def __init__(
        self,
        total: int,
        console: Optional[Console] = None,
        live: Optional[bool] = None,
    ):
        self.total = max(total, 0)
        self.console = console or make_console(stderr=True)
        self.live = self.console.is_terminal if live is None else live
        self.done = 0
        self.engine = ""
        self.qid = ""
        self.status = ""
        self.question_started = time.monotonic()
        self._finished_times: List[float] = []
        self._bar: Optional[RichProgress] = None
        self._task = None

    # --- lifecycle --------------------------------------------------------

    async def __aenter__(self) -> "Progress":
        if self.live:
            self._bar = RichProgress(
                SpinnerColumn(),
                TextColumn("[bold]{task.fields[engine]}"),
                TextColumn("[bold cyan]{task.fields[qid]}"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                _EtaColumn(self),
                _QuestionClockColumn(self),
                TextColumn("[dim]{task.fields[status]}"),
                console=self.console,
                refresh_per_second=REFRESH_PER_SECOND,
                transient=True,
            )
            self._task = self._bar.add_task("eval", total=self.total, engine="",
                                            qid="", status="")
            self._bar.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._bar is not None:
            self._bar.stop()
            self._bar = None

    # --- events -----------------------------------------------------------

    def begin(self, engine: str, qid: str, question: str) -> None:
        self.engine, self.qid, self.status = engine, qid, "starting"
        self.question_started = time.monotonic()
        if self._bar is not None:
            self._bar.update(self._task, engine=engine, qid=qid, status=self.status)
        elif not self.live:
            self.console.print(
                f"[{engine} {self.done + 1}/{self.total}] {qid}: {question}",
                markup=False,
            )

    def update(self, message: str) -> None:
        self.status = " ".join(str(message).split())
        if self._bar is not None:
            self._bar.update(self._task, status=self.status)

    def finish(self, record: Dict[str, Any]) -> None:
        self._finished_times.append(time.monotonic() - self.question_started)
        self.done += 1
        self.status = ""
        self.console.print(result_line(record))
        if self._bar is not None:
            self._bar.update(self._task, completed=self.done, status="")

    def write(self, text: str) -> None:
        """Print a line above the bar (rich keeps the bar at the bottom)."""
        self.console.print(text, markup=False, highlight=False)

    def eta(self) -> Optional[float]:
        if not self._finished_times:
            return None
        remaining = self.total - self.done
        average = sum(self._finished_times) / len(self._finished_times)
        current = time.monotonic() - self.question_started
        return max(average * remaining - (current if remaining else 0), 0)


class ProgressLogHandler(logging.Handler):
    """Route log records through the progress console so they don't break the bar."""

    def __init__(self, progress: Progress, level: int = logging.WARNING):
        super().__init__(level)
        self.progress = progress
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = Text(self.format(record),
                        style="yellow" if record.levelno < logging.ERROR else "red")
            self.progress.console.print(text)
        except Exception:  # logging must never raise
            self.handleError(record)
