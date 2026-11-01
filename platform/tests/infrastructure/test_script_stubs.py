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

"""The three old scripts are stubs that print a one-line notice and exec the new command.

The hackathon material and `platform/README.md` users still name them until step 3c deletes them.
Each stub is copied next to a fake `platformctl` shim that prints its arguments, so the real tool
(which would create a `.env`) never runs.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

FAKE_SHIM = '#!/bin/sh\nprintf "platformctl:"\nfor a in "$@"; do printf " %s" "$a"; done\nprintf "\\n"\n'
"""A shim that prints the arguments it was given."""


@pytest.fixture
def stub_dir(tmp_path):
    """A platform-shaped folder: `scripts/` with the stubs, and a fake `platformctl` beside it."""
    (tmp_path / "scripts").mkdir()
    for name in ("init_env.py", "check_platform.py", "deeplynx_setup.py"):
        shutil.copy(SCRIPTS / name, tmp_path / "scripts" / name)
    (tmp_path / "platformctl").write_text(FAKE_SHIM)
    return tmp_path


def run_stub(folder, script, *args):
    """Run a stub with the current Python; return its exit code, stdout and stderr."""
    done = subprocess.run(
        [sys.executable, "-I", str(folder / "scripts" / script), *args], capture_output=True, text=True, check=False
    )
    return done.returncode, done.stdout, done.stderr


@pytest.mark.parametrize(
    ("script", "args", "notice", "forwarded"),
    [
        ("init_env.py", [], "moved: run `./platformctl config init`", "config init"),
        ("check_platform.py", [], "moved: run `./platformctl status --wait`", "status --wait"),
        (
            "check_platform.py",
            ["--timeout", "42", "--backend-port", "8600", "agents/client-agent"],
            "moved: run `./platformctl status --wait --timeout 42`",
            "status --wait --timeout 42",
        ),
        (
            "check_platform.py",
            ["--timeout=7", "--backend-port=1"],
            "moved: run `./platformctl status --wait --timeout 7`",
            "status --wait --timeout 7",
        ),
        (
            "deeplynx_setup.py",
            ["--port", "5000"],
            "moved: run `./platformctl deeplynx setup`",
            "deeplynx setup --no-start",
        ),
        (
            "deeplynx_setup.py",
            ["--port", "5000", "--timeout", "9"],
            "moved: run `./platformctl deeplynx setup`",
            "deeplynx setup --no-start --timeout 9",
        ),
    ],
)
def test_each_stub_says_it_moved_and_runs_the_new_command(stub_dir, script, args, notice, forwarded):
    """One line on stderr, then the new command runs with the old `--timeout` carried over."""
    code, out, err = run_stub(stub_dir, script, *args)
    assert code == 0
    assert err.splitlines()[0] == notice
    assert out.strip() == f"platformctl: {forwarded}"


@pytest.mark.parametrize(
    ("script", "args", "ignored"),
    [
        (
            "check_platform.py",
            ["--timeout", "42", "--backend-port", "8600", "agents/client-agent"],
            "--backend-port 8600 agents/client-agent",
        ),
        ("check_platform.py", ["--timeout=7", "--frontend-port=1", "../my-agent"], "--frontend-port=1 ../my-agent"),
        ("deeplynx_setup.py", ["--port", "5000", "--timeout", "9"], "--port 5000"),
    ],
)
def test_a_stub_says_which_old_arguments_it_no_longer_honours(stub_dir, script, args, ignored):
    """A developer who passed a port or their own agent folder is told it is ignored, not left to wonder."""
    _, _, err = run_stub(stub_dir, script, *args)
    assert err.splitlines()[1].startswith(f"ignored: {ignored} (")


@pytest.mark.parametrize(
    ("script", "args"),
    [
        ("check_platform.py", []),
        ("check_platform.py", ["--timeout", "5"]),
        ("deeplynx_setup.py", ["--timeout=9"]),
        ("init_env.py", []),
    ],
)
def test_a_stub_that_ignores_nothing_prints_only_the_moved_line(stub_dir, script, args):
    """`--timeout` is forwarded, so it is not reported as ignored."""
    _, _, err = run_stub(stub_dir, script, *args)
    assert len(err.splitlines()) == 1


def test_the_stubs_are_short():
    """A stub is a forwarder, not a second copy of the logic."""
    for name in ("init_env.py", "check_platform.py", "deeplynx_setup.py"):
        assert len((SCRIPTS / name).read_text().splitlines()) < 60, f"{name} is no longer a stub"
