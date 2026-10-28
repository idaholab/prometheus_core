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

"""Coverage for the progress display's plain write and its never-raising log handler."""

import io
import logging

from rich.console import Console

from evals.progress import Progress, ProgressLogHandler


def _console():
    return Console(file=io.StringIO(), width=200, force_terminal=False,
                   color_system=None, highlight=False)


def test_write_prints_text_verbatim_without_markup():
    console = _console()
    progress = Progress(total=1, console=console, live=False)

    progress.write("[bold]not markup[/] 42")

    assert console.file.getvalue() == "[bold]not markup[/] 42\n"


def test_a_failing_console_does_not_make_logging_raise():
    class _Broken:
        def print(self, *args, **kwargs):
            raise OSError("terminal gone")

    progress = Progress(total=1, console=_console(), live=False)
    progress.console = _Broken()
    handler = ProgressLogHandler(progress)
    handled = []
    handler.handleError = handled.append
    record = logging.LogRecord("osti", logging.ERROR, __file__, 1, "boom", None, None)

    handler.emit(record)

    assert handled == [record]
