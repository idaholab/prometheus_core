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

"""Live tests: run against the real shim and the real Docker. Only with `pytest --live`, never counted.

cd platform/ctl && uv run pytest tests/live --live
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

PLATFORM = Path(__file__).resolve().parents[3]
SHIM = PLATFORM / "platformctl"


def shim(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(SHIM), *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=120)


def test_help_from_another_directory(tmp_path):
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
    link = tmp_path / "pc"
    link.symlink_to(SHIM)
    python_dir = str(Path(sys.executable).parent)
    env = {"PATH": f"{python_dir}:/usr/bin:/bin", "CDPATH": "/tmp:/", "PLATFORMCTL_PYTHON": sys.executable}
    done = subprocess.run(["sh", str(link), "--version"], cwd="/", capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr


def test_make_style_run_from_the_platform_folder(tmp_path):
    done = subprocess.run(["sh", str(SHIM), "--version"], cwd=PLATFORM, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.startswith("platformctl ")


@pytest.mark.skipif(shutil.which("docker") is None, reason="no docker")
def test_doctor_against_the_real_daemon(tmp_path):
    done = shim("doctor", "--json", "--tag", "preflight", cwd=tmp_path)
    assert done.returncode in (0, 1), done.stderr
    body = json.loads(done.stdout)
    by_id = {c["id"]: c for c in body["checks"]}
    assert body["ok"] is True
    assert by_id["docker"]["status"] in ("PASS", "FAIL")
    if by_id["docker"]["status"] == "PASS":
        assert "Compose" in by_id["docker"]["evidence"]
    assert done.returncode == (1 if body["counts"]["fail"] else 0)


@pytest.mark.skipif(shutil.which("docker") is None, reason="no docker")
def test_doctor_never_prints_the_secrets_of_a_real_looking_env(tmp_path):
    secret = "fake-canary-fake-canary"
    platform = tmp_path / "platform"
    shutil.copytree(
        PLATFORM / "ctl", platform / "ctl", ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache")
    )
    shutil.copy(SHIM, platform / "platformctl")
    (platform / ".env").write_text(f"LLM_API_KEY={secret}\nAGENT_SECRET={secret}x\n")
    (platform / ".env").chmod(0o600)
    done = subprocess.run(
        ["sh", str(platform / "platformctl"), "--verbose", "doctor", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert secret not in done.stdout + done.stderr
    assert json.loads(done.stdout)["ok"] is True
