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

"""Evaluation CLI.

    python -m evals run [run options]          # run the questions, then report
    python -m evals report [evals/report.json] # re-print an existing report

``run`` takes the options documented in ``evals/run.py``; ``python -m evals
run --help`` lists them. ``python -m evals.run`` still works the same way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

USAGE = "usage: python -m evals {run,report} [options]"


def _report(argv: List[str]) -> int:
    from evals import report as render

    path = Path(argv[0] if argv else "evals/report.json")
    if not path.exists():
        print(f"no report at {path}; run `python -m evals run` first", file=sys.stderr)
        return 1
    report = json.loads(path.read_text())
    try:
        from evals.console import make_console, print_summary
    except ImportError:
        # A bare python3 without rich (make osti-eval-report on the host).
        print(render.terminal_summary(report))
        if not report.get("complete", True):
            print("\n(This report is partial: the run did not finish.)")
    else:
        print_summary(make_console(), report)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        print(__doc__)
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command == "run":
        from evals import run

        return run.main(rest)
    if command == "report":
        return _report(rest)
    print(f"unknown command {command!r}\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
