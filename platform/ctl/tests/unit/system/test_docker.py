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
    """A `Docker` whose `docker info` returns the given result."""
    runner = FakeRunner()
    runner.reply("docker", "info", code=info_code, stdout=info_stdout, stderr=info_stderr)
    return Docker(runner, env), runner


def test_info_ok_desktop_with_containerd():
    """Info ok desktop with containerd."""
    docker, runner = docker_with(DOCKER_INFO)
    info = docker.info()
    assert info.state == dockermod.OK
    assert (info.server_version, info.architecture, info.context) == ("29.1.0", "aarch64", "desktop-linux")
    assert info.containerd_store and info.desktop and not info.rootless and not info.podman
    assert runner.calls[0][:3] == ["docker", "info", "--format"]


def test_info_engine_without_containerd_store_and_rootless():
    """Info engine without containerd store and rootless."""
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
    """Podman is recognised by the server's name or version."""
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
    """Info failures are told apart and never echo output."""
    info = docker_with(info_code=1, info_stderr=stderr, env={"DOCKER_HOST": "tcp://h:1"})[0].info()
    assert info.state == state
    assert info.docker_host == "tcp://h:1"
    assert stderr not in info.detail


def test_info_unreadable_output():
    """Output that isn't JSON is an error state."""
    assert docker_with("not json")[0].info().state == dockermod.UNKNOWN_ERROR


def test_info_missing_docker():
    """A missing `docker` command is the `missing` state."""
    runner = FakeRunner(raises={"docker": RunnerError("nope")})
    info = Docker(runner).info()
    assert info.state == dockermod.MISSING


def test_compose_version():
    """The Compose version is returned, or None when the plugin is missing or prints nothing."""
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
    """`volumes` filters by project and volume label, and `image_exists` follows the exit code."""
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
    """Containers publishing a port are listed with their project and platform labels, skipping junk lines."""
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


def test_registry_reachable_reads_the_manifest_with_a_timeout():
    """A test "pull" that downloads nothing: it succeeds when the manifest can be read."""
    docker, runner = docker_with()
    runner.reply("docker", "manifest", "inspect", code=0)
    assert docker.registry_reachable("registry.example/img:tag", timeout=7) is True
    assert runner.calls == [["docker", "manifest", "inspect", "registry.example/img:tag"]]


MANIFEST_LIST = (
    '{"schemaVersion": 2, "manifests": ['
    '{"platform": {"architecture": "amd64", "os": "linux"}}, '
    '{"platform": {"architecture": "unknown", "os": "unknown"}}]}'
)
"""A manifest list that publishes amd64 only (plus the attestation entry BuildKit adds)."""


@pytest.mark.parametrize(
    ("manifest", "arch", "expected"),
    [
        (MANIFEST_LIST, "amd64", True),
        (MANIFEST_LIST, "arm64", False),
        (
            '{"manifests": [{"platform": {"architecture": "arm64"}}, {"platform": {"architecture": "amd64"}}]}',
            "arm64",
            True,
        ),
        ('[{"Descriptor": {"platform": {"architecture": "arm64"}}}]', "amd64", True),  # no list: not ours to judge
        ('{"schemaVersion": 2, "config": {}}', "arm64", True),  # a single-image manifest names no architecture
        ("not json", "arm64", True),
        ("", "arm64", True),
    ],
)
def test_registry_reachable_checks_the_architecture_when_asked(manifest, arch, expected):
    """A pin that publishes only amd64 is not "reachable" on an arm64 machine: it would fail or run emulated."""
    docker, runner = docker_with()
    runner.reply("docker", "manifest", "inspect", code=0, stdout=manifest)
    assert docker.registry_reachable("registry.example/img:tag", arch=arch) is expected


def test_registry_reachable_ignores_the_architecture_when_not_asked():
    """Without `arch` any readable manifest counts, as before."""
    docker, runner = docker_with()
    runner.reply("docker", "manifest", "inspect", code=0, stdout=MANIFEST_LIST)
    assert docker.registry_reachable("registry.example/img:tag") is True


def test_registry_reachable_is_false_when_the_manifest_is_refused_or_slow():
    """A login or network failure, or the timeout (exit 124), means unreachable."""
    for code in (1, 124):
        docker, runner = docker_with()
        runner.reply("docker", "manifest", "inspect", code=code)
        assert docker.registry_reachable("registry.example/img:tag") is False


def test_registry_reachable_is_false_without_docker():
    """No `docker` command is unreachable, not an error."""
    docker, runner = docker_with()
    runner.raises["docker"] = RunnerError("can't run docker")
    assert docker.registry_reachable("registry.example/img:tag") is False
