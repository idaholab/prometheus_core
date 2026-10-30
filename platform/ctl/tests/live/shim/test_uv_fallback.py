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

"""Live test of the shim's last resort: `uv run`, when no Python 3.10+ can be found.

Only with `pytest --live`; it never counts toward coverage. It needs `uv` and nothing else:
the shim gets a `PATH` with only `uv` and the few system tools it calls, so no system Python
exists for it to find.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.live.helpers import SHIM

pytestmark = pytest.mark.live

# The system tools the shim itself runs. Python is deliberately not among them.
SHIM_TOOLS = ("uname", "dirname", "readlink")
# Where a Mac's Homebrew Python lives; the shim tries these paths by name, not through PATH.
HOMEBREW_PYTHONS = ("/opt/homebrew/bin/python3", "/usr/local/bin/python3")


def test_the_shim_falls_back_to_uv_run_when_no_python_is_found(tmp_path):
    """With only `uv` available, the shim runs the real tool through `uv run`, and says which command it ran."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    if sys.platform == "darwin" and any(Path(path).exists() for path in HOMEBREW_PYTHONS):
        pytest.skip("this Mac has a Homebrew Python, which the shim would use before uv")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in SHIM_TOOLS:
        (bin_dir / tool).symlink_to(shutil.which(tool))
    # A recording wrapper around the real uv, so the test can see how the shim called it.
    log = tmp_path / "uv-calls.log"
    wrapper = bin_dir / "uv"
    wrapper.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\nexec "{uv}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    # uv finds or downloads its own Python through HOME and the UV_* settings, not through PATH.
    env = {key: value for key, value in os.environ.items() if key.startswith(("UV_", "XDG_")) or key == "HOME"}
    env["PATH"] = str(bin_dir)
    # Ignore every system Python (uv would otherwise find one by itself, such as a conda or
    # Homebrew install): only a Python that uv manages may run the tool.
    env["UV_PYTHON_PREFERENCE"] = "only-managed"
    # `sh` by absolute path: the bare PATH above can't find it
    done = subprocess.run(
        [shutil.which("sh"), str(SHIM), "--version", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )

    assert done.returncode == 0, done.stderr
    assert '"command": "version"' in done.stdout
    calls = log.read_text().splitlines()
    assert len(calls) == 1
    assert calls[0].startswith("run --no-project --python >=3.10 python -I ")
    assert calls[0].endswith("ctl/run.py --version --json")
