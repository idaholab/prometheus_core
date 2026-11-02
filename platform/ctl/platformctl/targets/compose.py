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

"""The Docker Compose target: the only one for now."""

from __future__ import annotations

from platformctl import compose_files
from platformctl.config import PlatformConfig, host_arch
from platformctl.paths import Paths
from platformctl.system.compose import Compose
from platformctl.system.docker import Docker
from platformctl.targets.base import FOREGROUND, PASSTHROUGH, YOUR_AGENTS, Target

_PORT_SETTINGS = {
    "backend": "BACKEND_PORT",
    "frontend-dev": "FRONTEND_DEV_PORT",
    "frontend-prod": "FRONTEND_PROD_PORT",
    "client-agent": "CLIENT_AGENT_PORT",
    "redis": "REDIS_LOCAL_PORT",
}
"""The setting that holds each service's host port."""


class ComposeTarget(Target):
    """The platform on Docker Compose, through the generated entry file."""

    name = "compose"
    """The target's name."""
    capabilities = frozenset({PASSTHROUGH, YOUR_AGENTS, FOREGROUND})
    """What this target supports."""

    def __init__(self, paths: Paths, config: PlatformConfig, compose: Compose, docker: Docker) -> None:
        """Keep the paths, settings and adapters the target works through."""
        self.paths = paths
        self.config = config
        self.compose = compose
        self.docker = docker

    def build_cache_on(self) -> bool:
        """The registry cache needs the containerd image store; without it, it's turned off."""
        return self.config.flag("USE_BUILD_CACHE") and self.docker.info().containerd_store

    def generate(self) -> dict[str, str]:
        """Write the generated compose files, with the build cache only if the image store allows it."""
        agents = compose_files.discover_agents(self.paths.root, self.config)
        info = self.docker.info()
        written = compose_files.write_generated(
            self.paths.root,
            self.config,
            agents,
            build_cache=self.config.flag("USE_BUILD_CACHE") and info.containerd_store,
            arch=host_arch(info.architecture),
        )
        return {name: str(path) for name, path in written.items()}

    def service_url(self, service: str) -> str | None:
        """The host URL of a service, from its port setting, or None when it has none."""
        setting = _PORT_SETTINGS.get(service)
        return f"http://localhost:{self.config.int(setting)}" if setting else None
