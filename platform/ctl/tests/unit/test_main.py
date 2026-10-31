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

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from platformctl import __main__ as entry


def test_old_python_gets_a_clear_message(monkeypatch, capsys):
    """Old python gets a clear message."""
    monkeypatch.setattr(entry.sys, "version_info", (3, 9, 6, "final", 0))
    assert entry.main([]) == 1
    err = capsys.readouterr().err
    assert "needs Python 3.10 or newer, but this is Python 3.9" in err
    assert "PLATFORMCTL_PYTHON" in err


def test_sudo_is_refused(monkeypatch, capsys):
    """Running under `sudo` exits 1 and says why."""
    monkeypatch.setenv("SUDO_USER", "someone")
    assert entry.main(["doctor"]) == 1
    assert "don't run it with sudo" in capsys.readouterr().err


def test_refusals_are_one_json_object_with_json(monkeypatch, capsys):
    """With `--json`, the sudo and old-Python refusals print the usual error object on stdout and nothing on stderr."""
    import json

    monkeypatch.setenv("SUDO_USER", "someone")
    assert entry.main(["doctor", "--json"]) == 1
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert captured.err == ""
    assert (body["schema_version"], body["ok"], body["error"]["code"]) == (1, False, "config_invalid")
    assert "sudo" in body["error"]["message"] and body["platform"]["version"] == "unknown"

    monkeypatch.delenv("SUDO_USER")
    monkeypatch.setattr(entry.sys, "version_info", (3, 9, 6, "final", 0))
    assert entry.main(["--json", "doctor"]) == 1
    body = json.loads(capsys.readouterr().out)
    assert "needs Python 3.10 or newer, but this is Python 3.9" in body["error"]["message"]
    assert "PLATFORMCTL_PYTHON" in body["error"]["hint"]


def test_json_after_a_double_dash_belongs_to_the_command_not_the_tool(monkeypatch, capsys):
    """`compose -- --json` passes `--json` on to Compose, so a refusal stays plain text."""
    monkeypatch.setenv("SUDO_USER", "someone")
    assert entry.main(["compose", "--", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "don't run it with sudo" in captured.err


def test_main_hands_over_to_the_cli(monkeypatch):
    """Main hands over to the cli."""
    monkeypatch.delenv("SUDO_USER", raising=False)
    seen = []
    from platformctl import cli

    monkeypatch.setattr(cli, "main", lambda argv: seen.append(list(argv)) or 0)
    assert entry.main(["--version"]) == 0
    monkeypatch.setattr(entry.sys, "argv", ["platformctl", "doctor"])
    assert entry.main() == 0
    assert seen == [["--version"], ["doctor"]]


def test_the_entry_modules_parse_without_3_10_syntax():
    """__main__.py and run.py must parse on 3.9: no match statements, no `X | Y` annotations, no parenthesised with."""
    import ast

    root = Path(entry.__file__).resolve().parents[1]
    for path in (root / "platformctl" / "__main__.py", root / "run.py"):
        ast.parse(path.read_text(), feature_version=(3, 9))


def test_run_py_runs_from_any_directory_without_picking_up_local_modules(tmp_path):
    """Run py runs from any directory without picking up local modules."""
    (tmp_path / "json.py").write_text("raise SystemExit('shadowed!')\n")
    (tmp_path / "argparse.py").write_text("raise SystemExit('shadowed!')\n")
    run_py = Path(entry.__file__).resolve().parents[1] / "run.py"
    done = subprocess.run(
        [sys.executable, "-I", str(run_py), "--version"], cwd=tmp_path, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("platformctl ")
