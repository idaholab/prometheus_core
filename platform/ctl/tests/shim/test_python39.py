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

"""The tool and the shim on a real Python 3.9, the interpreter of a stock Mac.

Not stubs: these tests run the real entry point and the real shim with a real 3.9. Locally
they skip when no 3.9 can be found; CI installs one with uv and sets PLATFORMCTL_REQUIRE_PY39=1,
which turns that skip into a failure so the check can't silently go missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shim.test_shim import SHIM

CTL = SHIM.parent / "ctl"
"""The `ctl/` folder next to the shim."""
RUN_PY = CTL / "run.py"
"""The entry point the shim runs."""
REQUIRE = os.environ.get("PLATFORMCTL_REQUIRE_PY39") == "1"
"""Whether a missing Python 3.9 fails the tests instead of skipping them (CI sets this)."""
SHIM_TOOLS = ("uname", "dirname", "readlink")
"""The system tools the shim itself runs; Python is deliberately not among them."""
HOMEBREW_PYTHONS = ("/opt/homebrew/bin/python3", "/usr/local/bin/python3")
"""Where a Mac's Homebrew Python lives; the shim tries these paths by name, not through PATH."""


def minor_version(python: str) -> str | None:
    """The `major.minor` of an interpreter, or None when it can't run."""
    try:
        done = subprocess.run(
            [python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def find_python39() -> str | None:
    """A real Python 3.9: `python3.9`, uv's, or the stock `/usr/bin/python3` of a Mac."""
    candidates = [shutil.which("python3.9")]
    uv = shutil.which("uv")
    if uv:
        found = subprocess.run(
            [uv, "python", "find", "3.9", "--no-python-downloads"], capture_output=True, text=True, timeout=60
        )
        candidates.append(found.stdout.strip() if found.returncode == 0 else None)
    candidates.append("/usr/bin/python3")
    return next((c for c in candidates if c and minor_version(c) == "3.9"), None)


@pytest.fixture(scope="module")
def python39() -> str:
    """The path of a real Python 3.9, or a skip (a failure in CI)."""
    found = find_python39()
    if found is None:
        message = "no Python 3.9 found (CI installs one with `uv python install 3.9`)"
        if REQUIRE:
            pytest.fail(message)
        pytest.skip(message)
    return found


@pytest.fixture
def tool_dir(tmp_path: Path) -> Path:
    """A PATH directory holding only the system tools the shim calls."""
    path = tmp_path / "bin"
    path.mkdir()
    for tool in SHIM_TOOLS:
        (path / tool).symlink_to(shutil.which(tool))
    return path


def run_shim(shim_shell: list[str], path: Path, cwd: Path, *args: str, env_extra: dict | None = None):
    """Run the real shim with `path` as the whole PATH, so only what is in it can be found."""
    env = {"PATH": str(path), "HOME": str(cwd), **(env_extra or {})}
    shell = [shutil.which(shim_shell[0]), *shim_shell[1:]]  # absolute: the bare PATH can't find `sh`
    return subprocess.run([*shell, str(SHIM), *args], capture_output=True, text=True, env=env, cwd=cwd, timeout=120)


def test_the_entry_point_explains_itself_instead_of_crashing(python39, tmp_path):
    """On 3.9, `run.py` parses and says what to do, with no SyntaxError or traceback.

    Covers REQ-001-04.
    """
    done = subprocess.run(
        [python39, "-I", str(RUN_PY), "--version"], capture_output=True, text=True, cwd=tmp_path, timeout=60
    )
    assert done.returncode == 1
    assert "needs Python 3.10 or newer, but this is Python 3.9" in done.stderr
    assert "PLATFORMCTL_PYTHON" in done.stderr
    assert "SyntaxError" not in done.stderr and "Traceback" not in done.stderr
    assert done.stdout == ""


def test_a_python3_that_is_3_9_is_skipped_for_a_newer_python(python39, shim_shell, tool_dir, tmp_path):
    """The Mac case: `python3` is 3.9 and a 3.12 is installed, so the shim runs the tool with the 3.12.

    Covers REQ-001-01, BEH-001-01.
    """
    (tool_dir / "python3").symlink_to(python39)
    (tool_dir / "python3.12").symlink_to(sys.executable)  # any 3.10+; the shim only looks at the name
    done = run_shim(shim_shell, tool_dir, tmp_path, "--version")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("platformctl ")


def test_a_lone_python_3_9_gets_the_install_message(python39, shim_shell, tool_dir, tmp_path):
    """With only a 3.9 (and no uv), the shim suggests installing uv, not a traceback.

    Covers REQ-001-03.
    """
    if sys.platform == "darwin" and any(Path(p).exists() for p in HOMEBREW_PYTHONS):
        pytest.skip("this Mac has a Homebrew Python, which the shim would use")
    (tool_dir / "python3").symlink_to(python39)
    done = run_shim(shim_shell, tool_dir, tmp_path, "--version")
    assert done.returncode == 1
    assert "needs Python 3.10 or newer, and none was found" in done.stderr
    assert done.stderr.count("curl -LsSf https://astral.sh/uv/install.sh | sh") == 1
    assert "brew" not in done.stderr and "apt" not in done.stderr
    assert "Traceback" not in done.stderr and done.stdout == ""


def test_platformctl_python_set_to_a_3_9_is_refused(python39, shim_shell, tool_dir, tmp_path):
    """A `PLATFORMCTL_PYTHON` that is 3.9 is an error naming the variable, not a silent fallback.

    Covers REQ-001-02.
    """
    (tool_dir / "python3.12").symlink_to(sys.executable)
    done = run_shim(shim_shell, tool_dir, tmp_path, "--version", env_extra={"PLATFORMCTL_PYTHON": python39})
    assert done.returncode == 1
    assert "PLATFORMCTL_PYTHON" in done.stderr and "is not a Python 3.10 or newer" in done.stderr
