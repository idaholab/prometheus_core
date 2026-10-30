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

"""Helpers shared by the live tests of every component."""

from __future__ import annotations

import subprocess
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[3]
SHIM = PLATFORM / "platformctl"


def shim(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the real shim with `sh` from `cwd` and capture its output."""
    return subprocess.run(["sh", str(SHIM), *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=120)
