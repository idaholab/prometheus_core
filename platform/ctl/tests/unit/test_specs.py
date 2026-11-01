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

"""The build and run specs (build/specs) and every citation of them follow common/speccheck's rules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
"""The repository root, which the specs' `tests:` paths are relative to."""

CHECKER = REPO / "common" / "speccheck" / "speccheck.py"
"""The shared spec checker, run by path so it adds no dependency."""


def test_specs_and_citations_are_consistent():
    """Each requirement is cited by a test, `⚠ untested` or planned; each citation names a real ID."""
    done = subprocess.run(
        [sys.executable, "-I", str(CHECKER), "--specs", "build/specs"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
