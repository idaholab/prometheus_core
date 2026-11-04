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
import re
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


@pytest.fixture
def real_platform(tmp_path: Path, project_root: Path) -> Path:
    """The platform folder as `make` sees it, with the real init_env.py and the SDK's LLM profiles it reads."""
    root = tmp_path / "platform"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(project_root / "Makefile", root)
    shutil.copy(project_root / ".env.example", root)
    shutil.copy(project_root / "scripts" / "init_env.py", root / "scripts")
    shutil.copytree(
        project_root.parent / "sdk" / "prometheus_api" / "llm_configs",
        tmp_path / "sdk" / "prometheus_api" / "llm_configs",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return root


def make_real(root: Path, *goals: str, **env: str) -> subprocess.CompletedProcess:
    """`make -n` with no terminal (stdin closed), the way CI and an assistant run it."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV", "LLM_"))}
    return subprocess.run(
        ["make", "-n", "-k", *goals],
        cwd=root,
        env={**clean, "INIT_ENV_ON_DRY_RUN": "true", **env},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_real_script_creates_env_through_the_makefile_in_one_run(real_platform):
    """What `make up` does on a fresh clone: no stub, the real script and Makefile together."""
    result = make_real(real_platform, "up", LLM_CONFIG_PROFILE="ollama")

    env = real_platform / ".env"
    assert env.exists(), result.stderr
    assert oct(env.stat().st_mode & 0o777) == "0o600"
    written = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line and line[0] != "#")
    assert written["LLM_CONFIG_PROFILE"] == "ollama"
    assert written["AGENT_SECRET"] and written["BACKEND_JWT_SECRET"]
    # No terminal: both questions are skipped, and it says so
    assert "Not asked (no terminal): LOCAL_SDK, LOCAL_DEEPLYNX stay false" in result.stdout
    assert "build-local" not in result.stdout


def test_the_real_script_stops_make_when_the_profile_is_missing(real_platform):
    """No terminal and no profile: the script exits 1, and make stops before any start recipe."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV", "LLM_"))}
    result = subprocess.run(
        ["make", "-n", "up"],
        cwd=real_platform,
        env={**clean, "INIT_ENV_ON_DRY_RUN": "true"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "LLM_CONFIG_PROFILE is empty" in result.stderr
    assert "docker compose" not in result.stdout


def test_the_real_script_leaves_a_complete_env_for_the_second_run(real_platform):
    make_real(real_platform, "up", LLM_CONFIG_PROFILE="ollama")
    first = (real_platform / ".env").read_text()
    second_run = make_real(real_platform, "up")

    assert (real_platform / ".env").read_text() == first
    assert "Not asked" not in second_run.stdout
    assert "Creating .env" not in second_run.stdout


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


# The goals that build or start something and so need .env. A new documented target must be
# added here, or to NO_ENV_GOALS in the Makefile: test_every_documented_goal_is_decided fails until it is.
ENV_GOALS = {
    "up",
    "up-fg",
    "restart",
    "restart-fg",
    "ng-up",
    "ng-up-fg",
    "ng-restart",
    "ng-restart-fg",
    "init-env",
    "deeplynx-setup",
    "build",
    "build-plain",
}


def makefile_goals(project_root: Path) -> tuple[set[str], set[str]]:
    """(the targets `make help` lists, the Makefile's NO_ENV_GOALS)."""
    text = (project_root / "Makefile").read_text()
    documented = set(re.findall(r"^([A-Za-z0-9_.-]+):[^=\n]*##@", text, flags=re.M))
    block = re.search(r"^NO_ENV_GOALS\s*:=((?:.*\\\n)*.*)$", text, flags=re.M)
    assert block, "NO_ENV_GOALS not found in the Makefile"
    return documented, set(block.group(1).replace("\\", " ").split())


def test_every_documented_goal_is_decided(project_root):
    """A new `make` target must say whether it needs .env: add it to NO_ENV_GOALS, or to ENV_GOALS here.

    Left out of both, a target that needs .env would run without one, and a read-only one
    (logs, ps, down) would create one as a side effect of looking.
    """
    documented, no_env = makefile_goals(project_root)
    undecided = documented - no_env - ENV_GOALS
    assert not undecided, (
        f"decide whether these need .env (NO_ENV_GOALS in the Makefile, or ENV_GOALS here): {sorted(undecided)}"
    )
    overlap = no_env & ENV_GOALS
    assert not overlap, f"in both NO_ENV_GOALS and ENV_GOALS: {sorted(overlap)}"


def test_no_env_goals_and_env_goals_name_real_targets(project_root):
    """A renamed or removed target must not linger in either list."""
    documented, no_env = makefile_goals(project_root)
    text = (project_root / "Makefile").read_text()
    defined = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", text, flags=re.M))
    assert not (no_env - defined), f"NO_ENV_GOALS names no target: {sorted(no_env - defined)}"
    assert not (ENV_GOALS - defined), f"ENV_GOALS names no target: {sorted(ENV_GOALS - defined)}"


def test_each_decided_goal_does_what_its_list_says(platform, project_root):
    """Every ENV_GOALS goal runs the script once; no NO_ENV_GOALS goal runs it or creates .env."""
    _, no_env = makefile_goals(project_root)
    for goal in sorted(ENV_GOALS):
        for leftover in ("runs.log", ".env"):
            (platform / leftover).unlink(missing_ok=True)
        make(platform, goal)
        assert runs(platform) == 1, f"make {goal} should run init_env.py once"
    for goal in sorted(no_env):
        for leftover in ("runs.log", ".env"):
            (platform / leftover).unlink(missing_ok=True)
        make(platform, goal)
        assert runs(platform) == 0, f"make {goal} must not run init_env.py"
        assert not (platform / ".env").exists(), f"make {goal} must not create .env"


def test_env_is_created_before_the_docker_check(platform, project_root, tmp_path):
    """The order the PR changed: init_env.py runs first, so a missing Docker is reported after .env exists.

    A person without Docker running answers the questions once, and the rerun asks nothing.
    """
    scripts = tmp_path / "infrastructure" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(project_root.parent / "infrastructure" / "scripts" / "check-local-prereqs.sh", scripts)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_docker = bin_dir / "docker"
    fake_docker.write_text("#!/bin/sh\nexit 1\n")
    fake_docker.chmod(0o755)

    clean = {k: v for k, v in os.environ.items() if not k.startswith(("LOCAL_", "MAKE", "INIT_ENV", "SKIP_"))}
    # Only the fake docker on PATH (plus the basics the script's own tools need)
    result = subprocess.run(
        ["make", "up"],
        cwd=platform,
        env={**clean, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert (platform / ".env").exists(), "the .env step must run before the Docker check"
    assert runs(platform) == 1
    assert "docker" in result.stdout.lower(), result.stdout
    assert "[ERROR]" in result.stdout


def test_a_failing_script_stops_make(platform):
    """As make up runs it (no -k): nothing after the .env rule runs."""
    result = make(platform, "up", keep_going=False, STUB_FAIL="1")
    assert result.returncode != 0
    assert runs(platform) == 1
    assert "scripts/deeplynx_setup.py" not in result.stdout
    assert "docker compose" not in result.stdout
