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

"""The shim, run with `sh` against a PATH of stub interpreters (design.md, "CI").

Not part of the coverage-counted unit tests: the shim is shell. Run with
`uv run pytest tests/shim`; pass `--shim-shell dash` (or 'bash --posix', ksh, 'busybox ash')
to try another shell.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SHIM = Path(__file__).resolve().parents[3] / "platformctl"
SYSTEM_PATH = "/usr/bin:/bin"

# The shell that runs the shim; set per session from --shim-shell.
SHELL: list[str] = ["sh"]


@pytest.fixture(autouse=True)
def _use_the_chosen_shell(shim_shell):
    SHELL[:] = shim_shell


def stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def python_stub(directory: Path, name: str, version: tuple[int, int], marker: str | None = None) -> Path:
    """Answers the shim's probe by version, and otherwise reports which stub ran."""
    ok = "0" if version >= (3, 10) else "1"
    return stub(
        directory,
        name,
        f'case "$1" in -c) exit {ok} ;; esac\necho "ran {marker or name}: $*"\n',
    )


def run(tmp_path: Path, path_dirs: list[Path], *args: str, env_extra: dict | None = None, shim: Path = SHIM):
    env = {"PATH": ":".join([*map(str, path_dirs), SYSTEM_PATH]), "HOME": str(tmp_path), **(env_extra or {})}
    return subprocess.run([*SHELL, str(shim), *args], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)


@pytest.fixture
def bin_dir(tmp_path) -> Path:
    path = tmp_path / "bin"
    path.mkdir()
    return path


def test_prefers_the_newest_python_3_1x(tmp_path, bin_dir):
    python_stub(bin_dir, "python3.12", (3, 12))
    python_stub(bin_dir, "python3.14", (3, 14))
    python_stub(bin_dir, "python3", (3, 9))
    done = run(tmp_path, [bin_dir], "up")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("ran python3.14: -I ") and done.stdout.strip().endswith("ctl/run.py up")


def test_a_mac_whose_python3_is_3_9_finds_python3_12(tmp_path, bin_dir):
    python_stub(bin_dir, "python3", (3, 9))
    python_stub(bin_dir, "python3.12", (3, 12))
    assert run(tmp_path, [bin_dir]).stdout.startswith("ran python3.12")


def test_python3_is_used_when_it_is_new_enough(tmp_path, bin_dir):
    python_stub(bin_dir, "python3", (3, 11))
    assert run(tmp_path, [bin_dir]).stdout.startswith("ran python3:")


def test_an_old_python_3_1x_is_skipped(tmp_path, bin_dir):
    python_stub(bin_dir, "python3.10", (3, 9))  # a stub that fails the probe
    python_stub(bin_dir, "python3.11", (3, 11))
    assert run(tmp_path, [bin_dir]).stdout.startswith("ran python3.11")


def test_platformctl_python_wins_when_it_works(tmp_path, bin_dir):
    python_stub(bin_dir, "python3.14", (3, 14))
    mine = python_stub(tmp_path, "mine", (3, 10), marker="mine")
    done = run(tmp_path, [bin_dir], env_extra={"PLATFORMCTL_PYTHON": str(mine)})
    assert done.stdout.startswith("ran mine")


def test_platformctl_python_that_is_too_old_is_an_error_not_a_fallback(tmp_path, bin_dir):
    python_stub(bin_dir, "python3.14", (3, 14))
    old = python_stub(tmp_path, "old", (3, 9))
    done = run(tmp_path, [bin_dir], env_extra={"PLATFORMCTL_PYTHON": str(old)})
    assert done.returncode == 1 and "is not a Python 3.10 or newer" in done.stderr and done.stdout == ""


def test_uv_is_the_fallback(tmp_path, bin_dir):
    stub(bin_dir, "uv", 'echo "uv $*"\n')
    done = run(tmp_path, [bin_dir], "doctor")
    assert done.returncode == 0
    assert done.stdout.startswith("uv run --no-project --python >=3.10 python -I ")
    assert done.stdout.strip().endswith("ctl/run.py doctor")


def test_nothing_found_prints_one_install_command(tmp_path, bin_dir):
    # A PATH with only the system tools the shim needs, and no Python 3.10+ or uv.
    done = run(tmp_path, [bin_dir])
    if done.returncode == 0:  # this machine has a system Python 3.10+ in /usr/bin
        pytest.skip("a Python 3.10+ is in /usr/bin")
    assert done.returncode == 1
    assert "needs Python 3.10 or newer" in done.stderr
    assert done.stderr.count("Install one with:") == 1
    assert ("brew install" in done.stderr) or ("apt install" in done.stderr)


def test_the_arguments_are_passed_through_untouched(tmp_path, bin_dir):
    python_stub(bin_dir, "python3.12", (3, 12))
    done = run(tmp_path, [bin_dir], "logs", "--tail", "5", "a b", "--", "x'y")
    assert done.stdout.strip().endswith("ctl/run.py logs --tail 5 a b -- x'y")


def test_cdpath_and_a_symlinked_shim_do_not_send_it_elsewhere(tmp_path, bin_dir):
    python_stub(bin_dir, "python3.12", (3, 12))
    decoy = tmp_path / "decoy"
    (decoy / "elsewhere").mkdir(parents=True)
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    link = link_dir / "pc"
    link.symlink_to(SHIM)
    relative = link_dir / "rel"
    relative.symlink_to(os.path.relpath(link, link_dir))  # a link to a link, by a relative target
    for shim in (link, relative):
        done = run(tmp_path, [bin_dir], "x", env_extra={"CDPATH": f"{decoy}:/tmp"}, shim=shim)
        assert done.returncode == 0, done.stderr
        assert str(SHIM.parent) in done.stdout


def test_a_crlf_shim_fails_before_python_starts(tmp_path):
    """The `checkout-path` check can't report this (nothing runs), so the Make forwards check for \\r first."""
    crlf = tmp_path / "platformctl"
    crlf.write_bytes(SHIM.read_bytes().replace(b"\n", b"\r\n"))
    done = run(tmp_path, [], shim=crlf)
    assert done.returncode != 0


def test_the_shim_is_posix_sh_and_executable():
    text = SHIM.read_text()
    assert text.startswith("#!/bin/sh\n")
    for bashism in ("[[", "local ", "function ", "<(", "${BASH", "source "):
        assert bashism not in text
    assert SHIM.stat().st_mode & stat.S_IXUSR


def test_the_real_python_runs_the_real_tool(tmp_path):
    env = {"PATH": f"{Path(sys.executable).parent}:{SYSTEM_PATH}", "PLATFORMCTL_PYTHON": sys.executable}
    done = subprocess.run([*SHELL, str(SHIM), "--version"], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert done.returncode == 0 and done.stdout.startswith("platformctl ")
