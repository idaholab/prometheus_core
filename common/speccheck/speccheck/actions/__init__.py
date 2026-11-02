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

"""One module per command, found automatically.

Each exports NAME, HELP, SECTION, ORDER, `add_arguments(parser)` and `run(ctx, args) -> int`.
Adding a command is adding a file here.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

SECTIONS = (
    ("check", "Check specs and evidence"),
    ("ci", "In CI"),
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
