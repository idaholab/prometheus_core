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

"""Rules about the code base itself."""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "platformctl"


def test_no_pragma_no_cover_anywhere():
    """The only allowed exclusion is `if __name__ == "__main__":` (in pyproject's coverage config)."""
    offenders = [
        f"{path.relative_to(PACKAGE)}:{number}"
        for path in PACKAGE.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "pragma: no cover" in line or "pragma:no cover" in line
    ]
    assert offenders == []


def test_only_the_runner_starts_subprocesses():
    """Design: only system/runner.py starts subprocesses."""
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path.name != "runner.py" and ("import subprocess" in path.read_text() or "os.system" in path.read_text())
    ]
    assert offenders == []


def test_the_standard_library_is_the_only_runtime_dependency():
    # No tomllib: it needs Python 3.11 and the tests run on 3.10.
    text = (PACKAGE.parent / "pyproject.toml").read_text()
    assert "\ndependencies = []\n" in text
