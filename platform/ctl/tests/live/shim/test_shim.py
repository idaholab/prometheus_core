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

"""Live tests of the shim: the real script, the real Python, no stubs.

Only with `pytest --live`; they never count toward coverage.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.live.helpers import PLATFORM, SHIM, shim

pytestmark = pytest.mark.live


def test_help_from_another_directory(tmp_path):
    """`--help` works when run from a folder that is not the platform's."""
    done = shim("--help", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert "Troubleshoot:" in done.stdout


def test_a_folder_that_shadows_the_standard_library_changes_nothing(tmp_path):
    """Agent folders are full of .py files; a json.py or argparse.py there must not replace the stdlib."""
    (tmp_path / "json.py").write_text("raise SystemExit('shadowed json')\n")
    (tmp_path / "argparse.py").write_text("raise SystemExit('shadowed argparse')\n")
    done = shim("--version", "--json", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["command"] == "version"


def test_the_shim_works_through_a_symlink_and_with_cdpath_set(tmp_path):
    """A symlinked shim finds `ctl/`, and a set CDPATH can't send it elsewhere."""
    link = tmp_path / "pc"
    link.symlink_to(SHIM)
    python_dir = str(Path(sys.executable).parent)
    env = {"PATH": f"{python_dir}:/usr/bin:/bin", "CDPATH": "/tmp:/", "PLATFORMCTL_PYTHON": sys.executable}
    done = subprocess.run(["sh", str(link), "--version"], cwd="/", capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr


def test_make_style_run_from_the_platform_folder():
    """Run from the platform folder itself, the way a Makefile recipe would."""
    done = subprocess.run(["sh", str(SHIM), "--version"], cwd=PLATFORM, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.startswith("platformctl ")
