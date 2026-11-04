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
import signal
import subprocess
import time
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
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV"))}
    return subprocess.run(
        ["make", "-n", *(["-k"] if keep_going else []), *goals],
        cwd=root,
        # make -n skips the .env rule unless told otherwise; these tests are about that rule
        env={**clean, "INIT_ENV_ON_DRY_RUN": "true", **env},
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


def test_a_missing_env_is_announced_once_before_make_looks_for_it(platform):
    """Make 3.81 warns 'No such file or directory' for the include; the line before says that's expected."""
    first = make(platform, "up").stdout
    assert first.count("Creating .env") == 1
    # The reread after the rule must not announce it again, and an existing .env needs no announcement
    assert "Creating .env" not in make(platform, "up").stdout


def test_a_complete_env_runs_the_script_once_per_call(platform):
    make(platform, "up")
    make(platform, "up")
    assert runs(platform) == 2


@pytest.mark.parametrize("goal", ["", "help", "down", "down-v", "logs", "ps", "check", "generate", "test-static"])
def test_other_goals_never_create_env(platform, goal):
    make(platform, *([goal] if goal else []))
    assert runs(platform) == 0
    assert not (platform / ".env").exists()


@pytest.mark.parametrize("flags", [["-n"], ["-nk"], ["-k", "-n"], ["--dry-run"], ["-n", "-j4"], ["--just-print"]])
def test_a_dry_run_leaves_env_alone(platform, flags):
    """Make remakes included makefiles even under -n, so the rule is skipped: -n must not create .env."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV"))}
    result = subprocess.run(
        ["make", *flags, "-k", "up"], cwd=platform, env=clean, capture_output=True, text=True, timeout=60
    )
    assert runs(platform) == 0, result.stderr
    assert not (platform / ".env").exists()


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--no-print-directory"],
        ["-k"],
        ["-s"],
        ["--warn-undefined-variables"],
        ["-j4"],
        ["FOO=n"],
        ["CHECK=n", "-k"],
    ],
)
def test_other_flags_still_run_the_script(platform, flags):
    """Only a dry run skips the rule: the flag test must not mistake --no-print-directory or similar for -n."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV"))}
    # init-env's own recipe is a no-op, so this really runs make without -n and starts nothing
    result = subprocess.run(
        ["make", *flags, "init-env"], cwd=platform, env=clean, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert runs(platform) == 1
    assert (platform / ".env").exists()


SLOW_STUB = """\
import pathlib, time
root = pathlib.Path(__file__).resolve().parent.parent
(root / ".env").write_text("LOCAL_SDK=true\\nSECRET=kept\\n")
(root / "ready").write_text("")
time.sleep(30)
"""


def test_ctrl_c_while_the_script_runs_keeps_env(platform):
    """Make deletes the target of an interrupted rule unless it is .PRECIOUS; .env holds secrets and answers."""
    (platform / "scripts" / "init_env.py").write_text(SLOW_STUB)
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV"))}
    # Own process group, so the signal reaches make and the script like a Ctrl-C does
    proc = subprocess.Popen(
        ["make", "-n", "-k", "up"],
        cwd=platform,
        env={**clean, "INIT_ENV_ON_DRY_RUN": "true"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        for _ in range(100):
            if (platform / "ready").exists():
                break
            time.sleep(0.1)
        else:
            pytest.fail("the script never started")
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
    assert (platform / ".env").read_text() == "LOCAL_SDK=true\nSECRET=kept\n"


def test_a_failing_script_stops_make(platform):
    """As make up runs it (no -k): nothing after the .env rule runs."""
    result = make(platform, "up", keep_going=False, STUB_FAIL="1")
    assert result.returncode != 0
    assert runs(platform) == 1
    assert "scripts/deeplynx_setup.py" not in result.stdout
    assert "docker compose" not in result.stdout
