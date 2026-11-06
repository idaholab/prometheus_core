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

"""`speccheck check`: every requirement is claimed, and every claim is allowed. Outcomes are not looked at.

Run it locally on a collect-only run:

    pytest --collect-only -q --speccheck-results=.speccheck/collect.jsonl
    speccheck check .speccheck/
"""

from __future__ import annotations

import argparse

from speccheck import summary
from speccheck.actions import _common
from speccheck.context import Context

NAME = "check"
"""The command name."""
HELP = "Check that every requirement is claimed (from a collect-only run)"
"""The one-line help."""
SECTION = "check"
"""The `--help` section."""
ORDER = 20
"""Its place in the section."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The results files to read, and `--summary`."""
    _common.add_inputs(parser)
    summary.add_arguments(parser)


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Report claim problems and unclaimed requirements."""
    evaluation = _common.evaluate(ctx, args, runtime=False)
    return _common.finish(ctx, args, NAME, evaluation)
