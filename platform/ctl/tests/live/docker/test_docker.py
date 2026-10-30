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

"""Live tests of the `Docker` adapter (`platformctl/system/docker.py`) against the real daemon.

Each method that wraps a `docker` command runs here for real, and its answer is compared with what
the CLI itself says. Resources are throwaway: a random name, a free port, removed afterwards.
Only with `pytest --live`; they never count toward coverage.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import socket
import subprocess
from collections.abc import Iterator

import pytest

from platformctl.system.compose import MIN_VERSION, parse_version
from platformctl.system.docker import OK, Docker
from platformctl.system.runner import Runner
from tests.live.helpers import PLATFORM

pytestmark = [pytest.mark.live, pytest.mark.skipif(shutil.which("docker") is None, reason="no docker")]

MISSING_IMAGE = "platformctl-live-test/does-not-exist:never"
"""An image reference that no registry or local store has."""


def pinned_image() -> str:
    """The platform's pinned Valkey image from `docker-compose.yml`, so the digest lives in one place."""
    match = re.search(
        r"image:\s*(valkey/valkey-bundle:\S+@sha256:[0-9a-f]{64})", (PLATFORM / "docker-compose.yml").read_text()
    )
    assert match, "docker-compose.yml no longer pins a valkey/valkey-bundle image"
    return match.group(1)


def docker_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run the real `docker` directly, for setting up and checking, not through the adapter."""
    done = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=300)
    if check and done.returncode != 0:
        raise AssertionError(f"docker {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def free_port() -> int:
    """A host port that was free a moment ago."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def docker() -> Docker:
    """The adapter over the real runner."""
    return Docker(Runner())


@pytest.fixture(scope="module")
def image() -> str:
    """The pinned image, pulled once for the module."""
    ref = pinned_image()
    docker_cli("pull", "--quiet", ref)
    return ref


@pytest.fixture
def name() -> str:
    """A random name for this test's resources."""
    return f"platformctl-live-{secrets.token_hex(4)}"


@pytest.fixture
def volume(name: str) -> Iterator[tuple[str, str, str]]:
    """A volume labelled like Compose's, returned as (volume name, project, compose volume label); removed after."""
    project, label = f"{name}-project", "valkey-data"
    docker_cli(
        "volume", "create",
        "--label", f"com.docker.compose.project={project}",
        "--label", f"com.docker.compose.volume={label}",
        name,
    )  # fmt: skip
    yield name, project, label
    docker_cli("volume", "rm", "--force", name, check=False)


@pytest.fixture
def container(name: str, image: str) -> Iterator[tuple[str, int]]:
    """A container publishing a free port, labelled like a platform one, as (name, port); removed after."""
    port = free_port()
    docker_cli(
        "run", "--detach", "--name", name,
        "--publish", f"127.0.0.1:{port}:6379",
        "--label", f"com.docker.compose.project={name}-project",
        "--label", "com.docker.compose.project.working_dir=/live/test/platform",
        "--label", "io.prometheus.platform.root=/live/test/root",
        image,
    )  # fmt: skip
    yield name, port
    docker_cli("rm", "--force", name, check=False)


def test_info_matches_the_daemon(docker):
    """`info` reads the real daemon's version, OS, architecture and image store."""
    info = docker.info()
    raw = json.loads(docker_cli("info", "--format", "{{json .}}").stdout)
    assert info.state == OK
    assert info.server_version == raw["ServerVersion"]
    assert info.operating_system == raw["OperatingSystem"]
    assert info.architecture == raw["Architecture"]
    assert info.containerd_store == any("containerd" in " ".join(row) for row in raw.get("DriverStatus") or [])
    assert not info.podman


def test_compose_version_matches_the_plugin(docker):
    """`compose_version` is the Compose plugin's own `--short` version, and at least the supported minimum."""
    version = docker.compose_version()
    assert version == docker_cli("compose", "version", "--short").stdout.strip().lstrip("v")
    parsed = parse_version(version)
    assert parsed is not None and parsed[: len(MIN_VERSION)] >= MIN_VERSION


def test_image_exists_for_a_pulled_image(docker, image):
    """`image_exists` is true for the pulled, digest-pinned image."""
    assert docker.image_exists(image)


def test_image_exists_is_false_for_an_image_that_does_not_exist(docker):
    """`image_exists` is false, not an error, for an image the store doesn't have."""
    assert not docker.image_exists(MISSING_IMAGE)


def test_volumes_finds_a_volume_by_its_compose_labels(docker, volume):
    """`volumes` returns exactly the volume with this project and compose volume label."""
    name, project, label = volume
    assert docker.volumes(project, label) == [name]


def test_volumes_is_empty_for_other_projects_and_labels(docker, volume):
    """`volumes` doesn't return a volume of another project or with another label."""
    _, project, label = volume
    assert docker.volumes(f"{project}-other", label) == []
    assert docker.volumes(project, f"{label}-other") == []


def test_holders_names_the_container_publishing_a_port(docker, container):
    """`holders` finds the container on the port, with its project, working directory and platform root."""
    name, port = container
    assert docker.holders(port) == [
        {
            "name": name,
            "project": f"{name}-project",
            "root": "/live/test/root",
            "working_dir": "/live/test/platform",
        }
    ]


def test_holders_is_empty_for_a_port_nothing_publishes(docker):
    """`holders` is empty for a free port."""
    assert docker.holders(free_port()) == []


def test_holders_stops_finding_the_container_once_it_is_gone(docker, container):
    """After the container is removed, its port has no holder."""
    name, port = container
    assert docker.holders(port)
    docker_cli("rm", "--force", name)
    assert docker.holders(port) == []
