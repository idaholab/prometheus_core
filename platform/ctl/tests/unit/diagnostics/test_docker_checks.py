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

import pytest

from platformctl.diagnostics import docker_checks as dc
from platformctl.diagnostics.base import FAIL, PASS, SKIP, WARN
from tests.unit.conftest import make_context

# Recorded `docker info` / error output.
MAC_DESKTOP = json.dumps(
    {
        "ServerVersion": "29.1.0",
        "OperatingSystem": "Docker Desktop",
        "Architecture": "aarch64",
        "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]],
        "ClientInfo": {"Context": "desktop-linux"},
    }
)
"""A recorded `docker info` from Docker Desktop on a Mac."""
UBUNTU_ENGINE = json.dumps(
    {
        "ServerVersion": "27.3.1",
        "OperatingSystem": "Ubuntu 24.04.1 LTS",
        "Architecture": "x86_64",
        "DriverStatus": [["Backing Filesystem", "extfs"]],
        "ClientInfo": {"Context": "default"},
    }
)
"""A recorded `docker info` from Docker Engine on Ubuntu, without the containerd store."""
WSL_DESKTOP = json.dumps(
    {
        "ServerVersion": "28.0.4",
        "OperatingSystem": "Docker Desktop",
        "Architecture": "x86_64",
        "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]],
    }
)
"""A recorded `docker info` from Docker Desktop reached from WSL."""
PERMISSION = "permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock"
"""The error when the user is not in the docker group."""
NO_DAEMON = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?"
"""The error when the daemon is not running."""


def run_check(runner, platform_root, check, *, system="darwin", release="", env=None):
    """Run a check on a pretend OS and kernel release."""
    ctx, _, _ = make_context(platform_root, runner, env)
    ctx.host.system = system
    ctx.host.release_reader = lambda: release
    return check.run(ctx)


@pytest.mark.parametrize(
    ("info", "compose", "system", "release", "evidence"),
    [
        (MAC_DESKTOP, "v2.40.0", "darwin", "", "Docker Desktop 29.1.0, Compose 2.40.0, context desktop-linux"),
        (UBUNTU_ENGINE, "2.29.7\n", "linux", "6.8.0-generic", "Docker Engine 27.3.1, Compose 2.29.7, context default"),
        (
            WSL_DESKTOP,
            "v2.34.0-desktop.1",
            "linux",
            "5.15.167.4-microsoft-standard-WSL2",
            "Docker Desktop 28.0.4, Compose 2.34.0-desktop.1",
        ),
    ],
)
def test_docker_passes(runner, platform_root, info, compose, system, release, evidence):
    """A healthy Docker passes on a Mac, Ubuntu and WSL, with recorded `docker info` output from each."""
    runner.reply("docker", "info", stdout=info)
    runner.reply("docker", "compose", "version", stdout=compose)
    result = run_check(runner, platform_root, dc.DOCKER, system=system, release=release)
    assert (result.status, result.evidence) == (PASS, evidence)


def test_docker_rootless_is_noted(runner, platform_root):
    """A rootless daemon passes, and the evidence says so."""
    runner.reply("docker", "info", stdout=json.dumps({"ServerVersion": "27", "SecurityOptions": ["name=rootless"]}))
    assert run_check(runner, platform_root, dc.DOCKER).evidence.endswith(", rootless")


def test_docker_podman_warns(runner, platform_root):
    """Podman is a WARN, because it is not supported."""
    runner.reply("docker", "info", stdout=json.dumps({"ServerVersion": "5", "Name": "podman"}))
    result = run_check(runner, platform_root, dc.DOCKER)
    assert result.status == WARN and "Podman is not supported" in result.fix


def test_docker_not_installed(runner, platform_root):
    """A missing `docker` command is a FAIL with an install fix."""
    from platformctl.system.runner import RunnerError

    runner.raises = {"docker": RunnerError("nope")}
    result = run_check(runner, platform_root, dc.DOCKER)
    assert result.status == FAIL and "docker command was not found" in result.evidence


@pytest.mark.parametrize(
    ("system", "release", "fix_part"),
    [
        ("darwin", "", "Start Docker Desktop, wait"),
        ("linux", "5.15-microsoft-standard-WSL2", "WSL integration"),
        ("linux", "6.8.0-generic", "systemctl start docker"),
    ],
)
def test_docker_daemon_down_has_a_fix_for_each_os(runner, platform_root, system, release, fix_part):
    """Docker daemon down has a fix for each os."""
    runner.reply("docker", "info", code=1, stderr=NO_DAEMON)
    result = run_check(runner, platform_root, dc.DOCKER, system=system, release=release)
    assert result.status == FAIL and result.evidence == "the daemon is not running" and fix_part in result.fix


def test_docker_host_set_is_named_without_its_value(runner, platform_root):
    """Docker host set is named without its value."""
    runner.reply("docker", "info", code=1, stderr=NO_DAEMON)
    result = run_check(runner, platform_root, dc.DOCKER, env={"DOCKER_HOST": "tcp://user:hunter2hunter2@h:2375"})
    assert result.evidence == "DOCKER_HOST is set (remote)"
    assert "hunter2" not in result.evidence + result.fix


def test_docker_permission_denied_has_its_own_fix(runner, platform_root):
    """Docker permission denied has its own fix."""
    runner.reply("docker", "info", code=1, stderr=PERMISSION)
    result = run_check(runner, platform_root, dc.DOCKER, system="linux", release="6.8")
    assert result.status == FAIL and "usermod -aG docker" in result.fix


def test_docker_other_error(runner, platform_root):
    """An unrecognised `docker info` error is a FAIL that doesn't echo the output."""
    runner.reply("docker", "info", code=1, stderr="weird")
    result = run_check(runner, platform_root, dc.DOCKER)
    assert result.status == FAIL and result.evidence == "docker info failed"


@pytest.mark.parametrize(("system", "fix_part"), [("darwin", "Update Docker Desktop"), ("linux", "docker-compose-v2")])
def test_docker_without_the_compose_plugin(runner, platform_root, system, fix_part):
    """Docker without the compose plugin."""
    runner.reply("docker", "compose", "version", code=1, stderr="docker: 'compose' is not a docker command.")
    result = run_check(runner, platform_root, dc.DOCKER, system=system, release="6.8")
    assert result.status == FAIL and "'compose' is not a docker command" in result.evidence and fix_part in result.fix


@pytest.mark.parametrize("version", ["2.19.1", "1.29.2", "garbage"])
def test_docker_old_or_unreadable_compose(runner, platform_root, version):
    """Docker old or unreadable compose."""
    runner.reply("docker", "compose", "version", stdout=version)
    result = run_check(runner, platform_root, dc.DOCKER)
    assert result.status == FAIL and "older than 2.20" in result.evidence


def test_docker_minimum_compose_passes(runner, platform_root):
    """Compose 2.20.0, the minimum, passes."""
    runner.reply("docker", "compose", "version", stdout="2.20.0")
    assert run_check(runner, platform_root, dc.DOCKER).status == PASS


# -- build-cache-store -------------------------------------------------------------------------


def test_build_cache_store_pass(runner, platform_root):
    """With the containerd image store on, `build-cache-store` passes."""
    assert run_check(runner, platform_root, dc.BUILD_CACHE_STORE).status == PASS


def test_build_cache_store_missing_warns_with_the_daemon_json_fix(runner, platform_root):
    """Build cache store missing warns with the daemon json fix."""
    runner.reply("docker", "info", stdout=UBUNTU_ENGINE)
    result = run_check(runner, platform_root, dc.BUILD_CACHE_STORE, system="linux", release="6.8")
    assert result.status == WARN and "containerd-snapshotter" in result.fix and "daemon.json" in result.fix


def test_build_cache_store_missing_is_fine_when_the_cache_is_off(runner, platform_root):
    """Build cache store missing is fine when the cache is off."""
    runner.reply("docker", "info", stdout=UBUNTU_ENGINE)
    ctx, _, _ = make_context(platform_root, runner, sets={"USE_BUILD_CACHE": "false"})
    result = dc.BUILD_CACHE_STORE.run(ctx)
    assert result.status == PASS and "off" in result.evidence


def test_build_cache_store_is_skipped_on_podman(runner, platform_root):
    """Build cache store is skipped on podman."""
    runner.reply("docker", "info", stdout=json.dumps({"ServerVersion": "5", "Name": "podman"}))
    assert run_check(runner, platform_root, dc.BUILD_CACHE_STORE).status == SKIP


def test_the_checks_are_wired():
    """The two checks have their ids, tags and dependency."""
    assert dc.DOCKER.id == "docker" and set(dc.DOCKER.tags) == {"preflight", "diagnose"}
    assert dc.BUILD_CACHE_STORE.depends_on == ("docker",)
