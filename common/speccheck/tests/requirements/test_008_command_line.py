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

"""specs/008-command-line.md: the installed `speccheck` command and `run.py`, as separate processes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import speccheck
from tests.requirements.conftest import Project

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
"""common/speccheck."""


def command(project: Project, *argv: str) -> subprocess.CompletedProcess:
    """Run the installed `speccheck` console script in the project."""
    script = shutil.which("speccheck", path=str(Path(sys.executable).parent))
    assert script, "the speccheck console script is installed with the package"
    return subprocess.run([script, *argv], cwd=project.root, capture_output=True, text=True)


@pytest.mark.covers("SPC-REQ-008-01")
def test_help_lists_every_command_by_section(project: Project):
    """Each actions/ module is a command in `--help`, under its section."""
    done = command(project, "--help")
    actions = Path(speccheck.__file__).parent / "actions"
    names = sorted(p.stem for p in actions.glob("*.py") if not p.stem.startswith("_"))
    assert done.returncode == 0
    assert "Check specs and evidence:" in done.stdout and "In CI:" in done.stdout
    listed = sorted(
        line.split()[0] for line in done.stdout.splitlines() if line.startswith("  ") and not line.startswith("   ")
    )
    assert [n for n in names if n in listed] == names


@pytest.mark.covers("SPC-REQ-008-02")
def test_global_options_before_or_after_and_version(project: Project):
    """`--config` and `--json` work either side of the command; `--version` prints the version."""
    project.write("sub/c.toml", 'specs = "../specs"\nid-prefix = "T"\n')
    for argv in (["--config", "sub/c.toml", "--json", "lint"], ["lint", "--config", "sub/c.toml", "--json"]):
        done = command(project, *argv)
        assert done.returncode == 0 and json.loads(done.stdout)["command"] == "lint"
    assert command(project, "lint", "--quiet").stdout == ""
    assert command(project, "--version").stdout == f"speccheck {speccheck.__version__}\n"


@pytest.mark.covers("SPC-REQ-008-03")
def test_exit_codes(project: Project):
    """0 clean, 1 problems, 2 usage or config error."""
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    assert command(project, "lint").returncode == 0
    project.spec("- T-REQ-1-1: Bad.")
    assert command(project, "lint").returncode == 1
    assert command(project, "nope").returncode == 2
    assert command(project, "lint", "--config", "missing.toml").returncode == 2


@pytest.mark.covers("SPC-REQ-008-04")
def test_one_json_object_on_every_exit_path(project: Project):
    """Clean, with problems, and on a usage error: stdout is one object with the fixed fields."""
    project.spec("- T-REQ-001-01: One.")
    for argv, code in (
        (["lint", "--json"], 0),
        (["check", "--json"], 1),
        (["verify", "--json"], 0),
        (["report", "--json"], 0),
        (["nope", "--json"], 2),
    ):
        done = command(project, *argv)
        body = json.loads(done.stdout)
        assert done.returncode == code, argv
        assert {"schema_version", "command", "ok", "problems"} <= set(body), argv
    check = json.loads(command(project, "check", "--json").stdout)
    assert check["requirements"] == [
        {"id": "T-REQ-001-01", "spec": "001", "status": "unclaimed", "text": "One.", "evidence": [], "waiting_on": []}
    ]


@pytest.mark.covers("SPC-REQ-008-05")
def test_problems_on_stderr_and_a_summary_last(project: Project):
    """stdout stays clean on failure; the last line counts statuses and names the producers."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    done = command(project, "verify", "unit.jsonl")
    assert done.returncode == 1 and done.stdout == ""
    assert done.stderr.splitlines()[0].startswith("specs/001-thing.md:8: T-REQ-001-02 is not claimed")
    assert done.stderr.splitlines()[-1] == (
        "speccheck verify: 2 requirements: 1 unclaimed, 1 passed; reported: unit; 1 problem"
    )


@pytest.mark.covers("SPC-REQ-008-06")
def test_run_py_from_a_checkout(project: Project):
    """`python3 -I run.py` with nothing installed: only the standard library on the path."""
    if sys.version_info < (3, 11):
        pytest.skip("run.py needs tomllib (3.11 or newer); the 3.11 to 3.14 legs prove this")
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    done = subprocess.run(
        [sys.executable, "-I", "-S", str(PACKAGE_ROOT / "run.py"), "lint"],
        cwd=project.root,
        capture_output=True,
        text=True,
    )
    assert (done.returncode, done.stdout) == (0, "speccheck lint: 1 specs, 1 requirement\n"), done.stderr
