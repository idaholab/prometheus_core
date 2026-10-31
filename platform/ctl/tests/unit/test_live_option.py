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
"""The `platform/ctl` folder."""


def pytest_run(*args: str) -> subprocess.CompletedProcess:
    """Run pytest in a subprocess, from `platform/ctl`."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--rootdir", str(CTL), *args],
        cwd=CTL,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_live_tests_are_skipped_without_the_option():
    """Live tests are skipped without the option."""
    done = pytest_run("tests/live", "-q", "-rs")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "live test: run with --live" in done.stdout
    assert "passed" not in done.stdout.splitlines()[-1]


def test_live_refuses_to_run_under_coverage():
    """Live refuses to run under coverage."""
    done = pytest_run("tests/live", "--live", "--cov=platformctl", "-q")
    assert done.returncode != 0
    assert "--live can't run with coverage" in done.stdout + done.stderr


def test_live_without_a_path_collects_the_live_tests_not_the_unit_tests():
    """`testpaths` lists only `tests/unit`; `--live` alone must still reach `tests/live`."""
    done = pytest_run("--live", "--collect-only", "-q")
    assert done.returncode == 0, done.stdout + done.stderr
    collected = [line for line in done.stdout.splitlines() if "::" in line]
    assert collected and all(line.startswith("tests/live/") for line in collected)


def test_live_that_finds_no_live_test_fails_instead_of_passing_empty():
    """`--live tests/unit/test_cli.py` runs nothing live: that is an error, not a green run."""
    done = pytest_run("--live", "tests/unit/test_cli.py", "-q")
    assert done.returncode != 0
    assert "--live found no live tests to run" in done.stdout + done.stderr


def test_live_with_a_named_folder_runs_that_folder_only():
    """An explicit path is respected, even when an option's value (`--rootdir`) also contains a slash."""
    done = pytest_run("--live", "tests/live/shim", "--collect-only", "-q")
    collected = [line for line in done.stdout.splitlines() if "::" in line]
    assert collected and all(line.startswith("tests/live/shim/") for line in collected)


def test_the_live_marker_is_registered():
    """The live marker is registered."""
    done = pytest_run("--markers")
    assert "live: runs against the real Docker" in done.stdout
