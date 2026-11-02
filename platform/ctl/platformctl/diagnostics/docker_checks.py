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

"""Checks on Docker itself: the daemon, Compose, and the image store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from platformctl.diagnostics.base import (
    FAIL,
    FIX_YOU,
    PASS,
    SKIP,
    TAG_DIAGNOSE,
    TAG_PREFLIGHT,
    WARN,
    Check,
    Result,
)
from platformctl.system import docker as dockermod
from platformctl.system.compose import MIN_VERSION, parse_version

if TYPE_CHECKING:
    from platformctl.context import Context

COMPOSE_INSTALL_LINUX = (
    "sudo apt install docker-compose-v2   (or follow https://docs.docker.com/compose/install/linux/)"
)
"""The command that installs the Compose plugin on Debian and Ubuntu."""


def _start_docker_fix(ctx: Context) -> str:
    """How to start Docker on this OS, in plain words."""
    if ctx.host.is_mac:
        return "Start Docker Desktop, wait until it says it is running, then run this again."
    if ctx.host.is_wsl:
        return "Start Docker Desktop on Windows (with WSL integration on for this distro), or run `sudo service docker start` for an Engine inside the distro."
    return "Start the Docker daemon: `sudo systemctl start docker`."


def check_docker(ctx: Context) -> Result:
    """Check the daemon, the socket permission and the Compose plugin, each with its own fix."""
    info = ctx.docker.info()
    if info.state == dockermod.MISSING:
        return Result(
            FAIL,
            "the docker command was not found",
            "Install Docker Desktop (https://docs.docker.com/get-docker/), then run this again.",
        )
    if info.state == dockermod.NO_PERMISSION:
        return Result(
            FAIL,
            "no permission on the Docker socket",
            "Add yourself to the docker group: `sudo usermod -aG docker $USER`, then log out and back in.",
        )
    if info.state == dockermod.DAEMON_DOWN:
        where = (
            f"DOCKER_HOST is set ({'rootless' if info.rootless else 'remote'})"
            if info.docker_host
            else "the daemon is not running"
        )
        return Result(FAIL, where, _start_docker_fix(ctx))
    if info.state != dockermod.OK:
        return Result(FAIL, info.detail, "Run `docker info` yourself to see the error.")

    version = ctx.docker.compose_version()
    if version is None:
        fix = (
            "Install the Compose plugin: " + COMPOSE_INSTALL_LINUX if not ctx.host.is_mac else "Update Docker Desktop."
        )
        return Result(FAIL, "the Docker Compose plugin was not found ('compose' is not a docker command)", fix)
    parsed = parse_version(version)
    if parsed is None or parsed[: len(MIN_VERSION)] < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        return Result(FAIL, f"Compose {version} is older than {need}", "Update Docker Desktop (or the Compose plugin).")

    flavor = "Docker Desktop" if info.desktop else "Docker Engine"
    evidence = f"{flavor} {info.server_version}, Compose {version}"
    if info.context:
        evidence += f", context {info.context}"
    if info.podman:
        return Result(WARN, evidence + " (Podman)", "Podman is not supported; use Docker Desktop or Docker Engine.")
    if info.rootless:
        evidence += ", rootless"
    return Result(PASS, evidence)


def check_build_cache_store(ctx: Context) -> Result:
    """Check the containerd image store, which the registry build cache needs."""
    info = ctx.docker.info()
    if info.podman:
        return Result(SKIP, "Podman reports different fields")
    if info.containerd_store:
        return Result(PASS, "the containerd image store is on")
    if not ctx.config.flag("USE_BUILD_CACHE"):
        return Result(PASS, "the build cache is off (USE_BUILD_CACHE=false)")
    return Result(
        WARN,
        "the containerd image store is off, so the build cache is turned off and builds are slower",
        'To enable it, add {"features": {"containerd-snapshotter": true}} to /etc/docker/daemon.json '
        "and restart Docker (Docker Desktop: Settings > General > Use containerd).",
    )


DOCKER = Check("docker", "laptop", (TAG_PREFLIGHT, TAG_DIAGNOSE), check_docker, fix_kind=FIX_YOU)
"""The `docker` check."""
BUILD_CACHE_STORE = Check(
    "build-cache-store", "laptop", (TAG_PREFLIGHT,), check_build_cache_store, depends_on=("docker",), fix_kind=FIX_YOU
)
"""The `build-cache-store` check."""
