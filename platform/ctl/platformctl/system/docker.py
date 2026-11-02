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

"""The `docker` CLI: info, version, volumes, images, published ports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from platformctl.system.runner import Result, Runner, RunnerError

_PERMISSION = re.compile(r"permission denied.*docker\.sock|connect: permission denied", re.I)
"""Matches the error for no permission on the Docker socket."""
_NO_DAEMON = re.compile(
    r"cannot connect to the docker daemon|is the docker daemon running|connection refused|no such file", re.I
)
"""Matches the errors for a Docker daemon that is not running."""
_NO_COMPOSE = re.compile(r"'compose' is not a docker command|unknown shorthand flag|docker: unknown command", re.I)
"""Matches the errors for a missing Compose plugin."""

# Daemon states, told apart because each has its own fix.
OK, MISSING, DAEMON_DOWN, NO_PERMISSION, UNKNOWN_ERROR = "ok", "missing", "daemon_down", "no_permission", "error"


@dataclass
class DockerInfo:
    """What `docker info` says, or why it could not."""

    state: str = UNKNOWN_ERROR
    """ok, missing, daemon_down, no_permission or error."""
    detail: str = ""  # the error class only, never raw output
    """The error class only, never the raw output."""
    server_version: str = ""
    """The Docker server's version."""
    operating_system: str = ""
    """The server's operating system, such as `Docker Desktop`."""
    architecture: str = ""
    """The daemon's architecture, as Docker reports it."""
    driver_status: list[list[str]] = field(default_factory=list)
    """The storage driver's status rows."""
    context: str = ""
    """The Docker context in use."""
    docker_host: str = ""
    """Whether `DOCKER_HOST` is set (its value is never kept)."""
    rootless: bool = False
    """Whether the daemon is rootless."""
    podman: bool = False
    """Whether `docker` is really Podman."""

    @property
    def containerd_store(self) -> bool:
        """The containerd image store, which the registry build cache needs."""
        return any("containerd" in " ".join(row) for row in self.driver_status)

    @property
    def desktop(self) -> bool:
        """Whether the daemon is Docker Desktop."""
        return "docker desktop" in self.operating_system.lower()


class Docker:
    """The `docker` CLI."""

    def __init__(self, runner: Runner, env: dict[str, str] | None = None) -> None:
        """Keep the runner and the environment to run `docker` with."""
        self.runner = runner
        self.env = env

    def _run(self, *args: str, **kw) -> Result:
        """Run `docker` with the arguments."""
        return self.runner.run(["docker", *args], env=self.env, **kw)

    def info(self) -> DockerInfo:
        """Run `docker info` and tell a missing docker, a stopped daemon and a permission error apart."""
        try:
            done = self._run("info", "--format", "{{json .}}", timeout=30)
        except RunnerError:
            return DockerInfo(state=MISSING, detail="docker not found")
        host = (self.env or {}).get("DOCKER_HOST", "")
        if not done.ok:
            err = done.stderr
            if _PERMISSION.search(err):
                return DockerInfo(
                    state=NO_PERMISSION, detail="permission denied on the docker socket", docker_host=host
                )
            if _NO_DAEMON.search(err):
                return DockerInfo(state=DAEMON_DOWN, detail="the Docker daemon is not running", docker_host=host)
            return DockerInfo(state=UNKNOWN_ERROR, detail="docker info failed", docker_host=host)
        try:
            data = json.loads(done.stdout)
        except ValueError:
            return DockerInfo(state=UNKNOWN_ERROR, detail="docker info gave unreadable output", docker_host=host)
        options = data.get("SecurityOptions") or []
        name = str(data.get("Name", ""))
        return DockerInfo(
            state=OK,
            server_version=str(data.get("ServerVersion", "")),
            operating_system=str(data.get("OperatingSystem", "")),
            architecture=str(data.get("Architecture", "")),
            driver_status=[list(map(str, row)) for row in (data.get("DriverStatus") or [])],
            context=str(data.get("ClientInfo", {}).get("Context", "")) or "",
            docker_host=host,
            rootless=any("rootless" in str(o) for o in options),
            podman="podman" in name.lower() or "podman" in str(data.get("ServerVersion", "")).lower(),
        )

    def compose_version(self) -> str | None:
        """`2.20.0` style version of the Compose plugin, or None when it's missing."""
        try:
            done = self._run("compose", "version", "--short", timeout=30)
        except RunnerError:
            return None
        if not done.ok or _NO_COMPOSE.search(done.stderr):
            return None
        version = done.stdout.strip().lstrip("v")
        return version or None

    def volumes(self, project: str, volume: str) -> list[str]:
        """The names of a project's volumes with this compose volume label."""
        done = self._run(
            "volume", "ls", "-q",
            "--filter", f"label=com.docker.compose.project={project}",
            "--filter", f"label=com.docker.compose.volume={volume}",
        )  # fmt: skip
        return done.stdout.split() if done.ok else []

    def image_exists(self, ref: str) -> bool:
        """Whether the image is in the local store."""
        return self._run("image", "inspect", "--format", "{{.Id}}", ref).ok

    def holders(self, port: int) -> list[dict[str, str]]:
        """Containers publishing `port`: name, project and the platform root label."""
        done = self._run(
            "ps", "--filter", f"publish={port}", "--format",
            '{{json .}}',
        )  # fmt: skip
        found: list[dict[str, str]] = []
        if not done.ok:
            return found
        for line in done.stdout.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            labels = dict(pair.split("=", 1) for pair in str(row.get("Labels", "")).split(",") if "=" in pair)
            found.append(
                {
                    "name": str(row.get("Names", "")),
                    "project": labels.get("com.docker.compose.project", ""),
                    "root": labels.get("io.prometheus.platform.root", ""),
                    "working_dir": labels.get("com.docker.compose.project.working_dir", ""),
                }
            )
        return found
