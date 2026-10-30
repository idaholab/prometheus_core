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

"""Where the platform runs. Only `compose` is supported for now."""

from __future__ import annotations

from platformctl.targets.base import UnsupportedError

SUPPORTED = ("compose",)
"""The targets that work today."""


def check_name(name: str) -> str:
    """Validate a `--target` / PLATFORM_TARGET value."""
    if name == "k3d":
        raise UnsupportedError("target `k3d` is not supported yet")
    if name not in SUPPORTED:
        raise UnsupportedError(f"unknown target `{name}` (choose compose)")
    return name
