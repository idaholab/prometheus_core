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

"""Live tests of `doctor` against the real Docker daemon.

Only with `pytest --live`; they never count toward coverage.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.live.helpers import PLATFORM, SHIM, shim

pytestmark = [pytest.mark.live, pytest.mark.skipif(shutil.which("docker") is None, reason="no docker")]


def test_doctor_against_the_real_daemon(tmp_path):
    """`doctor --json` reports the real daemon, and its exit code follows the failed count."""
    done = shim("doctor", "--json", "--tag", "preflight", cwd=tmp_path)
    assert done.returncode in (0, 1), done.stderr
    body = json.loads(done.stdout)
    by_id = {c["id"]: c for c in body["checks"]}
    assert body["ok"] is True
    assert by_id["docker"]["status"] in ("PASS", "FAIL")
    if by_id["docker"]["status"] == "PASS":
        assert "Compose" in by_id["docker"]["evidence"]
    assert done.returncode == (1 if body["counts"]["fail"] else 0)


def test_doctor_never_prints_the_secrets_of_a_real_looking_env(tmp_path):
    """A `.env` full of secrets never reaches `doctor --verbose --json` output."""
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
