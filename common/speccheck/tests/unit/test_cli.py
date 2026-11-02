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

"""The command line: help, global options, exit codes and errors."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from speccheck import __version__, cli
from tests.conftest import Repo

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
"""common/speccheck."""


def test_help_lists_commands_by_section(repo: Repo):
    """Both sections, every command, and a command's own help."""
    run = repo.run("--help")
    assert run.code == 0
    assert "Check specs and evidence:\n  lint      " in run.out
    assert "In CI:\n  report    " in run.out and "  record    " in run.out
    assert "--complete" in repo.run("verify", "--help").out


class TestGlobalOptions:
    """Before or after the command."""

    def test_config_before_and_after(self, repo: Repo):
        """`--config` works in both places."""
        repo.write("sub/speccheck.toml", 'specs = "../specs"\nid-prefix = "T"\n')
        repo.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: draft\n")
        (repo.root / "speccheck.toml").unlink()
        assert repo.run("--config", "sub/speccheck.toml", "lint").code == 0
        assert repo.run("lint", "--config", "sub/speccheck.toml").code == 0

    def test_json_and_quiet_after_the_command(self, repo: Repo):
        """`lint --json` and `lint --quiet`."""
        repo.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: draft\n")
        assert repo.run("lint", "--json").json()["command"] == "lint"
        assert repo.run("lint", "--quiet").out == ""

    def test_version(self, repo: Repo):
        """Text and JSON."""
        assert repo.run("--version").out == f"speccheck {__version__}\n"
        assert repo.run("--version", "--json").json()["version"] == __version__


class TestExitCodes:
    """2 on a usage or config error."""

    def test_no_command(self, repo: Repo):
        """The help, and 2."""
        run = repo.run()
        assert run.code == 2 and "Check specs and evidence" in run.out

    def test_unknown_command(self, repo: Repo):
        """A usage error on stderr."""
        run = repo.run("nope")
        assert run.code == 2 and "speccheck: error: argument <command>: invalid choice" in run.err

    def test_config_error(self, repo: Repo):
        """No config: 2 and what to pass."""
        (repo.root / "speccheck.toml").unlink()
        run = repo.run("lint")
        assert run.code == 2 and "pass --config PATH" in run.err


def test_errors_are_json_too(repo: Repo):
    """A usage error and a config error, each one object on stdout."""
    body = repo.run("nope", "--json").json()
    assert (body["schema_version"], body["command"], body["ok"], body["problems"]) == (1, "", False, [])
    assert body["error"]["code"] == "usage"
    (repo.root / "speccheck.toml").unlink()
    run = repo.run("verify", "--json")
    assert run.code == 2 and run.json()["command"] == "verify" and "pass --config" in run.json()["error"]["message"]


def test_run_py_works_from_a_checkout(repo: Repo):
    """`python3 -I run.py` needs nothing installed (here: the same interpreter, isolated mode)."""
    if sys.version_info < (3, 11):
        pytest.skip("run.py needs tomllib, Python 3.11 or newer")
    repo.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: draft\n")
    done = subprocess.run(
        [sys.executable, "-I", str(PACKAGE_ROOT / "run.py"), "lint"], cwd=repo.root, capture_output=True, text=True
    )
    assert (done.returncode, done.stdout) == (0, "speccheck lint: 1 specs, 0 requirements\n"), done.stderr


def test_python_m_speccheck(repo: Repo):
    """`python -m speccheck --version`."""
    done = subprocess.run(
        [sys.executable, "-m", "speccheck", "--version"], capture_output=True, text=True, cwd=PACKAGE_ROOT
    )
    assert done.stdout == f"speccheck {__version__}\n"


def test_main_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """With no arguments given, main reads sys.argv, the environment and the real streams."""
    monkeypatch.setattr(sys, "argv", ["speccheck", "--version"])
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert cli.main() == 0 and out.getvalue() == f"speccheck {__version__}\n"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["speccheck", "lint"])
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert cli.main() == 2
