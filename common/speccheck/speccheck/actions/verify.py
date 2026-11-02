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

"""`speccheck verify`: everything `check` checks, and every claimed requirement has a passing result."""

from __future__ import annotations

import argparse

from speccheck.actions import _common
from speccheck.context import Context

NAME = "verify"
"""The command name."""
HELP = "Check that every claimed requirement passed in the given results"
"""The one-line help."""
SECTION = "check"
"""The `--help` section."""
ORDER = 30
"""Its place in the section."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The results files, `--complete` and `--workflow`."""
    _common.add_inputs(parser)
    _common.add_scope(parser)


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Report every requirement that failed, or (with `--complete`) wasn't run."""
    evaluation = _common.evaluate(ctx, args, runtime=True)
    return _common.finish(ctx, NAME, evaluation)
