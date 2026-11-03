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

"""`config init` on a real copy of the platform, then `doctor` against the real Docker.

Only with `pytest --live`; they never count toward coverage. The copy is made in a temporary folder, so the
real `.env` of the checkout is never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
from pathlib import Path

import pytest

from tests.live.helpers import PLATFORM, shim

pytestmark = [pytest.mark.live, pytest.mark.skipif(shutil.which("docker") is None, reason="no docker")]

SDK = PLATFORM.parent / "sdk" / "prometheus_api" / "llm_configs"
"""The SDK's LLM profiles, which `config init` reads."""


@pytest.fixture
def platform_copy(tmp_path: Path) -> Path:
    """A copy of what the tool reads: the shim, the tool, the compose files, `.env.example` and the profiles."""
    root = tmp_path / "repo" / "platform"
    root.mkdir(parents=True)
    shutil.copy2(PLATFORM / "platformctl", root / "platformctl")
    shutil.copytree(
        PLATFORM / "ctl", root / "ctl", ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", "tests")
    )
    for name in (".env.example", "docker-compose.yml"):
        shutil.copy2(PLATFORM / name, root / name)
    for compose in PLATFORM.glob("agents/*/docker-compose.yml"):
        target = root / compose.relative_to(PLATFORM)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compose, target)
        card = compose.parent / "agent_card.json"
        if card.exists():
            shutil.copy2(card, target.parent / card.name)
    shutil.copytree(SDK, tmp_path / "repo" / "sdk" / "prometheus_api" / "llm_configs")
    return root


def clean_env(**extra: str) -> dict[str, str]:
    """An environment with the real Python, Docker and HOME, and none of the checkout's own settings."""
    names = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT")
    keep = {k: v for k, v in os.environ.items() if k in names}
    return {**keep, "LLM_CONFIG_PROFILE": "ollama", **extra}


def run(root: Path, *args: str, env: dict[str, str]):
    """Run the copy's own shim, so the platform folder it finds is the copy and never the real checkout."""
    return shim(*args, cwd=root, env=env, script=root / "platformctl")


@pytest.fixture(autouse=True)
def real_checkout_stays_clean():
    """The tests write `.env` and generated files: none may ever appear in the real platform folder."""
    names = (".env", ".platform.env", "docker-compose.platform.yml", "docker-compose.agents.yml")
    before = {name: (PLATFORM / name).exists() for name in names}
    yield
    after = {name: (PLATFORM / name).exists() for name in names}
    assert after == before, "a live test wrote into the real platform folder"


def test_config_init_creates_a_private_env_and_doctor_passes_the_preflight(platform_copy):
    """A fresh copy: `.env` created 0600 with generated secrets, and the preflight `doctor` reports no FAIL."""
    init = run(platform_copy, "config", "init", "--no-local-sdk", "--no-local-deeplynx", env=clean_env())
    assert init.returncode == 0, init.stdout + init.stderr
    assert "Created .env from .env.example." in init.stdout and "Generated in .env: " in init.stdout
    env_file = platform_copy / ".env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert (platform_copy / "ctl" / "platformctl").is_dir()

    done = run(platform_copy, "doctor", "--json", "--tag", "preflight", env=clean_env())
    body = json.loads(done.stdout)
    failed = [c["id"] + ": " + c["evidence"] for c in body["checks"] if c["status"] == "FAIL"]
    assert body["ok"] and failed == [], failed


def test_config_init_a_second_time_changes_nothing(platform_copy):
    """Running it again reports no creation and leaves the file byte for byte as it was."""
    args = ("config", "init", "--no-local-sdk", "--no-local-deeplynx")
    assert run(platform_copy, *args, env=clean_env()).returncode == 0
    before = (platform_copy / ".env").read_bytes()
    again = run(platform_copy, *args, env=clean_env())
    assert again.returncode == 0 and "Created" not in again.stdout and "Generated" not in again.stdout
    assert (platform_copy / ".env").read_bytes() == before


def test_doctor_names_the_process_that_holds_a_port(platform_copy):
    """A port held by this test process fails `ports-free` and names the holder."""
    assert (
        run(platform_copy, "config", "init", "--no-local-sdk", "--no-local-deeplynx", env=clean_env()).returncode == 0
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("0.0.0.0", 0))
        holder.listen()
        port = holder.getsockname()[1]
        # --set, not the environment: `.env` (which has BACKEND_PORT from .env.example) beats the environment
        done = run(
            platform_copy,
            "--set",
            f"BACKEND_PORT={port}",
            "--set",
            "PROFILE=",
            "doctor",
            "ports-free",
            "--json",
            env=clean_env(),
        )
    check = json.loads(done.stdout)["checks"][0]
    assert done.returncode == 1 and check["status"] == "FAIL"
    assert str(port) in check["evidence"] and "BACKEND_PORT" in check["fix"]
