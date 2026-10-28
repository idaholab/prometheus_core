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

"""The rich terminal output of the evaluation: summary, result lines, and the
progress bar. Rendered into in-memory consoles; no real terminal needed."""

import asyncio
import io
import logging

from rich.console import Console

from evals import console as rich_out
from evals import scoring
from evals.progress import Progress, ProgressLogHandler

_PASSING = {
    "id": "q-pass", "status": "completed", "status_match": True, "provenance_ok": True,
    "citation_link_rate": 1.0, "source_hit_rate": 1.0, "fact_match": 1.0, "wall_s": 75.0,
    "judge_groundedness": 5, "judge_completeness": 4,
}
_FAILING = {
    **_PASSING, "id": "q-fail", "status_match": False, "judge_reference_agreement": 2,
}


def _console(*, terminal=False, width=200):
    return Console(file=io.StringIO(), width=width, force_terminal=terminal,
                   color_system="truecolor" if terminal else None, highlight=False)


def _report(records, complete=True):
    for record in records:
        record.setdefault("engine", "deepagent")
    return {"questions": len(records), "engines": ["deepagent"], "records": records,
            "aggregate": scoring.aggregate(records), "complete": complete}


def test_summary_shows_header_table_and_failures():
    text = rich_out.plain_summary(_report([dict(_PASSING), dict(_FAILING)]))

    assert "OSTI evaluation  1/2 passed  ·  2 question(s)  ·  engines: deepagent" in text
    assert "Per-engine summary" in text and "ref agree" in text
    assert "Failed (1)" in text and "q-fail" in text
    assert "judge reference agreement 2/5" in text


def test_summary_marks_a_partial_run_and_an_all_pass_run():
    assert "partial run" in rich_out.plain_summary(_report([dict(_PASSING)], complete=False))
    assert "Every question passed." in rich_out.plain_summary(_report([dict(_PASSING)]))


def test_result_line_colors_pass_and_fail():
    console = _console(terminal=True)
    console.print(rich_out.result_line(dict(_PASSING)))
    console.print(rich_out.result_line(dict(_FAILING)))
    out = console.file.getvalue()

    assert " PASS " in out and " FAIL " in out
    assert "\x1b[" in out  # styled on a terminal
    plain = rich_out.result_line(dict(_FAILING)).plain
    assert plain.startswith(" FAIL  q-fail  completed  1m15s  judge ground=5 complete=4 ref=2")


def test_off_a_terminal_the_console_is_wide_and_uncolored():
    console = rich_out.make_console()  # pytest captures stdout: not a terminal

    assert console.is_terminal is False and console.width == 160


def test_progress_off_a_terminal_prints_one_plain_line_per_event():
    console = _console()
    progress = Progress(total=2, console=console, live=False)

    async def go():
        async with progress:
            progress.begin("deepagent", "q-pass", "What?")
            progress.update("Searching OSTI...")  # no line for live status
            progress.finish(dict(_PASSING))

    asyncio.run(go())
    lines = console.file.getvalue().splitlines()

    assert lines[0] == "[deepagent 1/2] q-pass: What?"
    assert lines[1].startswith(" PASS  q-pass")
    assert len(lines) == 2 and "\x1b[" not in console.file.getvalue()


def test_live_progress_shows_question_status_and_count():
    console = _console(terminal=True)
    progress = Progress(total=4, console=console, live=True)

    async def go():
        async with progress:
            progress.begin("deepagent", "q-pass", "What?")
            progress.update("Parsing paper (tables + figures)...")
            progress._bar.refresh()
            progress.finish(dict(_PASSING))
            progress._bar.refresh()

    asyncio.run(go())
    out = console.file.getvalue()

    assert "q-pass" in out and "Parsing paper (tables + figures)..." in out
    assert "1/4" in out and "25%" in out
    assert " PASS " in out


def test_eta_uses_the_average_of_finished_questions(monkeypatch):
    clock = iter([0.0, 0.0, 60.0, 60.0, 90.0])
    monkeypatch.setattr("evals.progress.time.monotonic", lambda: next(clock))
    progress = Progress(total=4, console=_console(), live=False)

    assert progress.eta() is None
    progress.begin("deepagent", "q1", "?")
    progress.finish(dict(_PASSING))  # took 60s
    progress.begin("deepagent", "q2", "?")

    assert progress.eta() == 150  # 3 left x 60s, minus 30s into the current one


def test_warnings_print_through_the_progress_console():
    console = _console()
    progress = Progress(total=1, console=console, live=False)
    logger = logging.getLogger("evals-test")
    logger.addHandler(ProgressLogHandler(progress))
    try:
        logger.warning("OSTI response is not JSON")
    finally:
        logger.handlers.clear()

    assert "WARNING evals-test: OSTI response is not JSON" in console.file.getvalue()
