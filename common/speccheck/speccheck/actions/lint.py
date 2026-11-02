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

"""`speccheck lint`: check that the spec folder follows the format."""

from __future__ import annotations

import argparse

from speccheck import jsonout
from speccheck.context import Context

NAME = "lint"
"""The command name."""
HELP = "Check the spec folder's format"
"""The one-line help."""
SECTION = "check"
"""The `--help` section."""
ORDER = 10
"""Its place in the section."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """lint takes no arguments of its own."""


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Read every spec and report format problems."""
    specs = ctx.specs()
    ok = not specs.problems
    count = len(specs.requirements)
    text = f"{len(specs.specs)} specs, {count} requirement{'' if count == 1 else 's'}"
    if ctx.output.json_mode:
        body = jsonout.envelope(
            NAME,
            ok,
            specs.problems,
            specs=[
                {"number": s.number, "title": s.title, "status": s.status, "requirement_count": len(s.requirements)}
                for s in specs.specs
            ],
            requirement_count=count,
        )
        jsonout.emit(body, ctx.output.out)
    ctx.output.problems(specs.problems)
    ctx.output.summary(NAME, text, len(specs.problems))
    return jsonout.EXIT_OK if ok else jsonout.EXIT_PROBLEMS
