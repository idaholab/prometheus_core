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

import json
from pathlib import Path

import pytest

from platformctl.system.compose import Compose, parse_version
from tests.unit.conftest import FakeRunner


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2.20.3", (2, 20, 3)), ("v5.6.1-desktop.1", (5, 6, 1)), ("2.40.0+x", (2, 40, 0)), ("garbage", None), ("", None)],
)
def test_parse_version(text, expected):
    """Versions parse with or without a `v`, a suffix or build metadata, and garbage gives None."""
    assert parse_version(text) == expected


def make(profiles=()) -> tuple[Compose, FakeRunner]:
    """A `Compose` over a fake runner, with a canned environment."""
    runner = FakeRunner()
    return Compose(runner, Path("/p/docker-compose.platform.yml"), Path("/p"), profiles, {"A": "1"}), runner


def test_argv_uses_the_entry_file_and_profiles():
    """Argv uses the entry file and profiles."""
    compose, _ = make(["dev"])
    assert compose.argv("ps") == ["docker", "compose", "-f", "docker-compose.platform.yml", "--profile", "dev", "ps"]
    assert make()[0].argv("ps") == ["docker", "compose", "-f", "docker-compose.platform.yml", "ps"]


def test_run_passes_env_and_cwd():
    """Run passes env and cwd."""
    compose, runner = make()
    compose.run("ps")
    assert runner.calls == [["docker", "compose", "-f", "docker-compose.platform.yml", "ps"]]
    assert runner.envs == [{"A": "1"}]


def test_config_and_services():
    """`config` and `services` return the parsed output, or None or empty when Compose fails or prints junk."""
    compose, runner = make()
    runner.reply(
        "docker",
        "compose",
        "-f",
        "docker-compose.platform.yml",
        "config",
        "--format",
        "json",
        stdout='{"services": {}}',
    )
    assert compose.config() == {"services": {}}
    runner.reply("docker", "compose", "-f", "docker-compose.platform.yml", "config", "--format", "json", stdout="nope")
    assert compose.config() is None
    runner.reply("docker", "compose", "-f", "docker-compose.platform.yml", "config", "--format", "json", code=1)
    assert compose.config() is None
    runner.reply("docker", "compose", "-f", "docker-compose.platform.yml", "config", "--services", stdout="a\nb\n")
    assert compose.services() == ["a", "b"]
    runner.reply("docker", "compose", "-f", "docker-compose.platform.yml", "config", "--services", code=1)
    assert compose.services() == []


def test_ps_reads_json_lines_and_arrays():
    """Ps reads json lines and arrays."""
    compose, runner = make()
    out = json.dumps({"Service": "a"}) + "\n" + json.dumps([{"Service": "b"}, {"Service": "c"}]) + "\nbad\n"
    runner.reply("docker", "compose", "-f", "docker-compose.platform.yml", "ps", stdout=out)
    assert [r["Service"] for r in compose.ps()] == ["a", "b", "c"]


def test_up_variants():
    """`up` builds the right arguments for services, build, detach, wait and extras."""
    compose, runner = make()
    compose.up(["backend"], wait=600, extra=["--force-recreate"])
    compose.up(build=False, detach=False)
    tail = lambda call: call[4:]  # noqa: E731
    assert tail(runner.calls[0]) == [
        "up",
        "--build",
        "-d",
        "--wait",
        "--wait-timeout",
        "600",
        "--force-recreate",
        "backend",
    ]
    assert tail(runner.calls[1]) == ["up"]


def test_down_variants():
    """`down` adds `--remove-orphans` and `-v` only when asked."""
    compose, runner = make()
    compose.down()
    compose.down(volumes=True, remove_orphans=True)
    assert runner.calls[0][4:] == ["down"]
    assert runner.calls[1][4:] == ["down", "--remove-orphans", "-v"]


def test_exec_adds_T_without_a_terminal_and_forwards_env_names_only():
    """Exec adds T without a terminal and forwards env names only.

    Covers REQ-003-12.
    """
    compose, runner = make()
    compose.exec("redis", ["valkey-cli", "ping"], tty=False, env_names=["REDISCLI_AUTH"])
    compose.exec("redis", ["sh"], tty=True)
    assert runner.calls[0][4:] == ["exec", "-T", "-e", "REDISCLI_AUTH", "redis", "valkey-cli", "ping"]
    assert runner.calls[1][4:] == ["exec", "redis", "sh"]
