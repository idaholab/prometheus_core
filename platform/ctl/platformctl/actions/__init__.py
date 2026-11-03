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

"""One module per top-level command, found automatically.

A plain command module exports NAME, HELP, SECTION, ORDER, `add_arguments(parser)` and
`run(ctx, args) -> int`. A group exports NAME, HELP, SECTION, ORDER and SUBCOMMANDS (each
with NAME, HELP, add_arguments, run). Either may export ALIASES: old names that still work
and print a deprecation notice. See plans/platformctl/design.md, "Actions".
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType


@dataclass(frozen=True)
class Subcommand:
    """One subcommand of a group that lives in the group's module, with what a command module exports."""

    NAME: str
    """The subcommand's name."""
    HELP: str
    """Its one-line description in `--help`."""
    add_arguments: Callable[[argparse.ArgumentParser], None]
    """Adds its options to its parser."""
    run: Callable[..., int]
    """Runs it with the context and parsed arguments; returns the exit code."""
    ALIASES: tuple[str, ...] = field(default=())
    """Old names that still work."""


SECTIONS = (
    ("run", "Run the platform"),
    ("setup", "Set up"),
    ("troubleshoot", "Troubleshoot"),
)
"""The `--help` sections as (id, heading), in the order they are listed."""


def discover() -> list[ModuleType]:
    """Every action module, in `--help` order: section, then ORDER, then name."""
    modules = []
    for info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(module, "NAME"):
            modules.append(module)
    order = [section for section, _ in SECTIONS]
    return sorted(modules, key=lambda m: (order.index(m.SECTION), m.ORDER, m.NAME))
