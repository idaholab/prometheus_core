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

"""When the Makefile's .env rule runs scripts/init_env.py, and that its answers count in the same run.

The platform Makefile and .env.example are copied next to a stub init_env.py that
writes LOCAL_SDK=true and LOCAL_DEEPLYNX=true into a new .env and logs each run.
``make -n`` only prints the recipes, but still runs the rule that rebuilds an
included .env, so nothing here needs Docker.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="needs GNU make")

STUB = """\
import os, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
with open(root / "runs.log", "a") as log:
    log.write("ran\\n")
env = root / ".env"
if not env.exists():
    env.write_text("LOCAL_SDK=true\\nLOCAL_DEEPLYNX=true\\n")
if os.environ.get("STUB_FAIL"):
    raise SystemExit(1)
"""


@pytest.fixture
def platform(tmp_path: Path, project_root: Path) -> Path:
    root = tmp_path / "platform"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(project_root / "Makefile", root)
    shutil.copy(project_root / ".env.example", root)
    (root / "scripts" / "init_env.py").write_text(STUB)
    return root


def make(root: Path, *goals: str, keep_going: bool = True, **env: str) -> subprocess.CompletedProcess:
    # -k: keep going past recipes that fail without the rest of the repo (../sdk)
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE"))}
    return subprocess.run(
        ["make", "-n", *(["-k"] if keep_going else []), *goals],
        cwd=root,
        env={**clean, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def runs(root: Path) -> int:
    log = root / "runs.log"
    return len(log.read_text().splitlines()) if log.exists() else 0


@pytest.mark.parametrize("goal", ["up", "restart", "ng-up", "build", "deeplynx-setup", "init-env"])
def test_answers_saved_on_the_first_run_count_in_that_run(platform, goal):
    """No .env: the rule creates it once, and make rereads it, so LOCAL_SDK/LOCAL_DEEPLYNX apply now."""
    result = make(platform, goal)

    assert runs(platform) == 1
    assert (platform / ".env").exists()
    if goal in ("up", "ng-up", "build"):
        assert "build-local LOCAL_IMAGE=prometheus_api:local" in result.stdout
    if goal in ("up", "restart", "ng-up", "deeplynx-setup"):
        assert "scripts/deeplynx_setup.py" in result.stdout


def test_a_complete_env_runs_the_script_once_per_call(platform):
    make(platform, "up")
    make(platform, "up")
    assert runs(platform) == 2


@pytest.mark.parametrize("goal", ["", "help", "down", "down-v", "logs", "ps", "check", "generate", "test-static"])
def test_other_goals_never_create_env(platform, goal):
    make(platform, *([goal] if goal else []))
    assert runs(platform) == 0
    assert not (platform / ".env").exists()


def test_a_failing_script_stops_make(platform):
    """As make up runs it (no -k): nothing after the .env rule runs."""
    result = make(platform, "up", keep_going=False, STUB_FAIL="1")
    assert result.returncode != 0
    assert runs(platform) == 1
    assert "scripts/deeplynx_setup.py" not in result.stdout
    assert "docker compose" not in result.stdout
