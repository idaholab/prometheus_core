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

from platformctl.system import docker as dockermod
from platformctl.system.docker import Docker
from platformctl.system.runner import RunnerError
from tests.unit.conftest import DOCKER_INFO, FakeRunner


def docker_with(info_stdout="", info_code=0, info_stderr="", env=None) -> tuple[Docker, FakeRunner]:
    runner = FakeRunner()
    runner.reply("docker", "info", code=info_code, stdout=info_stdout, stderr=info_stderr)
    return Docker(runner, env), runner


def test_info_ok_desktop_with_containerd():
    docker, runner = docker_with(DOCKER_INFO)
    info = docker.info()
    assert info.state == dockermod.OK
    assert (info.server_version, info.architecture, info.context) == ("29.1.0", "aarch64", "desktop-linux")
    assert info.containerd_store and info.desktop and not info.rootless and not info.podman
    assert runner.calls[0][:3] == ["docker", "info", "--format"]


def test_info_engine_without_containerd_store_and_rootless():
    data = {
        "ServerVersion": "27.0",
        "OperatingSystem": "Ubuntu 24.04",
        "DriverStatus": [["Backing Filesystem", "extfs"]],
        "SecurityOptions": ["name=seccomp", "name=rootless"],
    }
    info = docker_with(json.dumps(data), env={"DOCKER_HOST": "unix:///run/user/1000/docker.sock"})[0].info()
    assert not info.containerd_store and not info.desktop and info.rootless
    assert info.docker_host.endswith("docker.sock")
    assert info.context == ""


@pytest.mark.parametrize("name", ["podman", "x"])
def test_info_detects_podman(name):
    data = {"Name": name, "ServerVersion": "5.0" if name != "x" else "podman 5"}
    assert docker_with(json.dumps(data))[0].info().podman


@pytest.mark.parametrize(
    ("stderr", "state"),
    [
        (
            "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock",
            dockermod.NO_PERMISSION,
        ),
        ("Cannot connect to the Docker daemon at unix:///x. Is the docker daemon running?", dockermod.DAEMON_DOWN),
        ("something else entirely", dockermod.UNKNOWN_ERROR),
    ],
)
def test_info_failures_are_told_apart_and_never_echo_output(stderr, state):
    info = docker_with(info_code=1, info_stderr=stderr, env={"DOCKER_HOST": "tcp://h:1"})[0].info()
    assert info.state == state
    assert info.docker_host == "tcp://h:1"
    assert stderr not in info.detail


def test_info_unreadable_output():
    assert docker_with("not json")[0].info().state == dockermod.UNKNOWN_ERROR


def test_info_missing_docker():
    runner = FakeRunner(raises={"docker": RunnerError("nope")})
    info = Docker(runner).info()
    assert info.state == dockermod.MISSING


def test_compose_version():
    runner = FakeRunner()
    runner.reply("docker", "compose", "version", stdout="v2.40.0\n")
    assert Docker(runner).compose_version() == "2.40.0"
    runner.reply("docker", "compose", "version", code=1, stderr="docker: 'compose' is not a docker command.")
    assert Docker(runner).compose_version() is None
    runner.reply("docker", "compose", "version", code=0, stdout="\n")
    assert Docker(runner).compose_version() is None
    runner.reply("docker", "compose", "version", code=0, stdout="v2", stderr="unknown shorthand flag: 'f'")
    assert Docker(runner).compose_version() is None
    assert Docker(FakeRunner(raises={"docker": RunnerError("x")})).compose_version() is None


def test_volumes_and_image_exists():
    runner = FakeRunner()
    runner.reply("docker", "volume", stdout="vol1\nvol2\n")
    docker = Docker(runner)
    assert docker.volumes("proj", "valkey-data") == ["vol1", "vol2"]
    assert "label=com.docker.compose.project=proj" in runner.calls[0]
    runner.reply("docker", "volume", code=1)
    assert docker.volumes("proj", "x") == []
    runner.reply("docker", "image", code=0)
    assert docker.image_exists("a:b")
    runner.reply("docker", "image", code=1)
    assert not docker.image_exists("a:b")


def test_holders():
    row = {
        "Names": "other-backend-1",
        "Labels": "com.docker.compose.project=other,io.prometheus.platform.root=/x/platform,nolabel,com.docker.compose.project.working_dir=/x/platform",
    }
    runner = FakeRunner()
    runner.reply("docker", "ps", stdout=json.dumps(row) + "\nnot json\n")
    assert Docker(runner).holders(8600) == [
        {"name": "other-backend-1", "project": "other", "root": "/x/platform", "working_dir": "/x/platform"}
    ]
    assert "publish=8600" in runner.calls[0]
    runner.reply("docker", "ps", code=1)
    assert Docker(runner).holders(8600) == []
