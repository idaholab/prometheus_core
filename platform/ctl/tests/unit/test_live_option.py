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

"""The `--live` option: live tests are skipped by default and refuse to run with coverage."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CTL = Path(__file__).resolve().parents[2]


def pytest_run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--rootdir", str(CTL), *args],
        cwd=CTL,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_live_tests_are_skipped_without_the_option():
    done = pytest_run("tests/live", "-q", "-rs")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "live test: run with --live" in done.stdout
    assert "passed" not in done.stdout.splitlines()[-1]


def test_live_refuses_to_run_under_coverage():
    done = pytest_run("tests/live", "--live", "--cov=platformctl", "-q")
    assert done.returncode != 0
    assert "--live can't run with coverage" in done.stdout + done.stderr


def test_the_live_marker_is_registered():
    done = pytest_run("--markers")
    assert "live: runs against the real Docker" in done.stdout
