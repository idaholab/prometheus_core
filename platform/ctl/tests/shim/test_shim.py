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
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SHIM = Path(__file__).resolve().parents[3] / "platformctl"
"""The real `platformctl` shim."""
SYSTEM_PATH = "/usr/bin:/bin"
"""The system directories, for the one test that runs the real Python."""
TOOLS = ("uname", "dirname", "readlink")
"""The system tools the shim itself runs. Python is deliberately not among them."""
HOMEBREW_PYTHONS = ("/opt/homebrew/bin/python3", "/usr/local/bin/python3")
"""Where a Mac's Homebrew Python lives; the shim tries these paths by name, not through PATH."""

SHELL: list[str] = ["sh"]
"""The shell that runs the shim; set per session from `--shim-shell`."""


@pytest.fixture(autouse=True)
def _use_the_chosen_shell(shim_shell):
    """Run every test in this module with the shell chosen by `--shim-shell`."""
    SHELL[:] = shim_shell


def stub(directory: Path, name: str, body: str) -> Path:
    """Write an executable shell script called `name` into `directory`."""
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


def tool_dir(tmp_path: Path) -> Path:
    """A directory holding only the system tools the shim runs, so no system Python can be found."""
    path = tmp_path / "tools"
    if not path.exists():
        path.mkdir()
        for tool in TOOLS:
            (path / tool).symlink_to(shutil.which(tool))
    return path


def skip_if_homebrew_python():
    """Skip on a Mac with a Homebrew Python: the shim tries those paths before `python3` and uv."""
    if sys.platform == "darwin" and any(Path(path).exists() for path in HOMEBREW_PYTHONS):
        pytest.skip("this Mac has a Homebrew Python, which the shim would use")


def run(tmp_path: Path, path_dirs: list[Path], *args: str, env_extra: dict | None = None, shim: Path = SHIM):
    """Run the shim with a PATH of `path_dirs` plus the few system tools it needs, and no system Python."""
    env = {
        "PATH": ":".join([*map(str, path_dirs), str(tool_dir(tmp_path))]),
        "HOME": str(tmp_path),
        **(env_extra or {}),
    }
    shell = [shutil.which(SHELL[0]), *SHELL[1:]]  # absolute: the child's PATH has no shells
    return subprocess.run([*shell, str(shim), *args], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)


@pytest.fixture
def bin_dir(tmp_path) -> Path:
    """An empty directory to hold stub interpreters."""
    path = tmp_path / "bin"
    path.mkdir()
    return path


def test_prefers_the_newest_python_3_1x(tmp_path, bin_dir):
    """Prefers the newest python 3 1x."""
    python_stub(bin_dir, "python3.12", (3, 12))
    python_stub(bin_dir, "python3.14", (3, 14))
    python_stub(bin_dir, "python3", (3, 9))
    done = run(tmp_path, [bin_dir], "up")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("ran python3.14: -I ") and done.stdout.strip().endswith("ctl/run.py up")


def test_a_mac_whose_python3_is_3_9_finds_python3_12(tmp_path, bin_dir):
    """A mac whose python3 is 3 9 finds python3 12."""
    python_stub(bin_dir, "python3", (3, 9))
    python_stub(bin_dir, "python3.12", (3, 12))
    assert run(tmp_path, [bin_dir]).stdout.startswith("ran python3.12")


def test_python3_is_used_when_it_is_new_enough(tmp_path, bin_dir):
    """Python3 is used when it is new enough."""
    skip_if_homebrew_python()
    python_stub(bin_dir, "python3", (3, 11))
    assert run(tmp_path, [bin_dir]).stdout.startswith("ran python3:")


def test_an_old_python_3_1x_is_skipped(tmp_path, bin_dir):
    """An old python 3 1x is skipped."""
    python_stub(bin_dir, "python3.10", (3, 9))  # a stub that fails the probe
    python_stub(bin_dir, "python3.11", (3, 11))
    assert run(tmp_path, [bin_dir]).stdout.startswith("ran python3.11")


def test_platformctl_python_wins_when_it_works(tmp_path, bin_dir):
    """Platformctl python wins when it works."""
    python_stub(bin_dir, "python3.14", (3, 14))
    mine = python_stub(tmp_path, "mine", (3, 10), marker="mine")
    done = run(tmp_path, [bin_dir], env_extra={"PLATFORMCTL_PYTHON": str(mine)})
    assert done.stdout.startswith("ran mine")


def test_platformctl_python_that_is_too_old_is_an_error_not_a_fallback(tmp_path, bin_dir):
    """Platformctl python that is too old is an error not a fallback."""
    python_stub(bin_dir, "python3.14", (3, 14))
    old = python_stub(tmp_path, "old", (3, 9))
    done = run(tmp_path, [bin_dir], env_extra={"PLATFORMCTL_PYTHON": str(old)})
    assert done.returncode == 1 and "is not a Python 3.10 or newer" in done.stderr and done.stdout == ""


def test_uv_is_the_fallback(tmp_path, bin_dir):
    """With no Python 3.10+, the shim runs the tool through `uv run --no-project --python >=3.10`."""
    skip_if_homebrew_python()
    stub(bin_dir, "uv", 'echo "uv $*"\n')
    done = run(tmp_path, [bin_dir], "doctor")
    assert done.returncode == 0
    assert done.stdout.startswith("uv run --no-project --python >=3.10 python -I ")
    assert done.stdout.strip().endswith("ctl/run.py doctor")


def test_nothing_found_prints_one_install_command(tmp_path, bin_dir):
    """With no Python 3.10+ and no uv, the shim's only suggestion is to install uv, with one command."""
    skip_if_homebrew_python()
    done = run(tmp_path, [bin_dir])
    assert done.returncode == 1
    assert "needs Python 3.10 or newer" in done.stderr
    assert done.stderr.count("curl -LsSf https://astral.sh/uv/install.sh | sh") == 1
    assert "brew" not in done.stderr and "apt" not in done.stderr


def test_the_arguments_are_passed_through_untouched(tmp_path, bin_dir):
    """The arguments are passed through untouched."""
    python_stub(bin_dir, "python3.12", (3, 12))
    done = run(tmp_path, [bin_dir], "logs", "--tail", "5", "a b", "--", "x'y")
    assert done.stdout.strip().endswith("ctl/run.py logs --tail 5 a b -- x'y")


def test_cdpath_and_a_symlinked_shim_do_not_send_it_elsewhere(tmp_path, bin_dir):
    """Cdpath and a symlinked shim do not send it elsewhere."""
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
    """The shim is posix sh and executable."""
    text = SHIM.read_text()
    assert text.startswith("#!/bin/sh\n")
    for bashism in ("[[", "local ", "function ", "<(", "${BASH", "source "):
        assert bashism not in text
    assert SHIM.stat().st_mode & stat.S_IXUSR


def test_the_real_python_runs_the_real_tool(tmp_path):
    """The real python runs the real tool."""
    env = {"PATH": f"{Path(sys.executable).parent}:{SYSTEM_PATH}", "PLATFORMCTL_PYTHON": sys.executable}
    done = subprocess.run([*SHELL, str(SHIM), "--version"], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert done.returncode == 0 and done.stdout.startswith("platformctl ")
