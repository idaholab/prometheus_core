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

"""specs/008-command-line.md: the installed `speccheck` command, as a separate process."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import speccheck
from tests.requirements.conftest import Project


def command(project: Project, *argv: str) -> subprocess.CompletedProcess:
    """Run the installed `speccheck` console script in the project."""
    script = shutil.which("speccheck", path=str(Path(sys.executable).parent))
    assert script, "the speccheck console script is installed with the package"
    return subprocess.run([script, *argv], cwd=project.root, capture_output=True, text=True)


@pytest.mark.covers("SPC-REQ-008-01")
def test_help_lists_every_command_by_section(project: Project):
    """Every command is in `--help`, under its section, with a one-line description."""
    done = command(project, "--help")
    assert done.returncode == 0
    assert "Check specs and evidence:" in done.stdout and "In CI:" in done.stdout
    listed = {
        line.split()[0]: line.split(None, 1)[1:]
        for line in done.stdout.splitlines()
        if line.startswith("  ") and not line.startswith("   ") and not line.lstrip().startswith("-")
    }
    assert {"lint", "check", "verify", "report", "record"} <= set(listed)
    assert all(listed[name] for name in ("lint", "check", "verify", "report", "record"))


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


@pytest.mark.covers("SPC-REQ-008-04")
def test_an_unwritable_output_is_still_one_json_object(project: Project):
    """A file in the way of the output folder is a usage error (2) as an object, not a traceback."""
    project.spec("- T-REQ-001-01: One.")
    project.write("blocker", "a file, not a folder")
    done = command(project, "report", "--json", "--output", "blocker/report.md")
    body = json.loads(done.stdout)
    assert done.returncode == 2 and body["ok"] is False and body["error"]["code"] == "usage"
    assert "blocker" in body["error"]["message"] and "Traceback" not in done.stderr


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
def test_problems_are_path_line_message_and_cant_start_a_log_command(project: Project):
    """Every problem line is `path:line: message` or `path: message`, and nothing printed can begin `::`.

    Control characters are written out whether they come from a file name or from a results file.
    """
    project.spec("- T-REQ-1-1: Bad.")
    project.write("specs/x\n::error::evil.md", "")
    done = command(project, "lint")
    assert done.stderr.splitlines()[:-1] and all(not line.startswith("::") for line in done.stderr.splitlines())
    assert "specs/001-thing.md:7: a bullet must read" in done.stderr
    assert "specs/x\\n::error::evil.md: a spec file must be named" in done.stderr
    (project.root / "specs" / "x\n::error::evil.md").unlink()
    project.spec("- T-REQ-001-01: One.")
    project.results("r.jsonl", "unit", [("t\n::error::evil", ["T-REQ-001-01"], "failed")])
    done = command(project, "verify", "r.jsonl")
    assert done.returncode == 1 and all(not line.startswith("::") for line in done.stderr.splitlines())
    assert "t\\n::error::evil failed in unit" in done.stderr
    project.results("r.jsonl", "unit", [("::error title=x::FORGED", ["T-REQ-001-01"], "failed")])
    done = command(project, "verify", "r.jsonl")
    assert done.returncode == 1 and all(not line.lstrip().startswith("::") for line in done.stderr.splitlines())
    assert "\\x3a:error title=x::FORGED" not in done.stderr  # mid-line, so left as written
    for forged, written in [("::error::x", "\\x3a:error::x"), ("##[error]x", "##\\x5berror]x")]:
        path = project.results("r.jsonl", "unit", [("t", ["T-REQ-009-09"], "passed")])
        path.write_text(path.read_text().replace('"file": "tests/test_x.py"', f'"file": "{forged}"'))
        done = command(project, "verify", "r.jsonl")
        assert done.stderr.startswith(f"{written}:3: T-REQ-009-09 isn't in any spec") and "##[" not in done.stderr
        assert all(not line.lstrip().startswith("::") for line in done.stderr.splitlines())
