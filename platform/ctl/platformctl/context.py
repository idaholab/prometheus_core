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

"""The Context passed to actions: config, target, adapters and output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platformctl.config import PlatformConfig, platform_version
from platformctl.output import Output
from platformctl.paths import Paths
from platformctl.system.compose import Compose
from platformctl.system.docker import Docker
from platformctl.system.host import Host
from platformctl.system.runner import Runner
from platformctl.targets import check_name
from platformctl.targets.compose import ComposeTarget


@dataclass
class Context:
    paths: Paths
    config: PlatformConfig
    output: Output
    runner: Runner
    docker: Docker
    host: Host
    compose: Compose
    target: ComposeTarget
    dry_run: bool = False
    yes: bool = False
    json_mode: bool = False
    debug: bool = False

    def platform_info(self) -> dict[str, Any]:
        """The `platform{root, project, version}` block of every JSON object."""
        return {
            "root": str(self.paths.root),
            "project": self.config.project,
            "version": platform_version(self.paths.root, self.runner),
        }


def build(
    paths: Paths,
    config: PlatformConfig,
    output: Output,
    runner: Runner,
    *,
    target: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    json_mode: bool = False,
    debug: bool = False,
) -> Context:
    check_name(target or config.get("PLATFORM_TARGET"))
    if config.get("PLATFORM_SOURCE") != "build":
        from platformctl.targets.base import UnsupportedError

        raise UnsupportedError("PLATFORM_SOURCE `image` is not supported yet (only `build`)")
    env = config.child_env()
    docker = Docker(runner, env)
    profiles = [p for p in [config.frontend_profile()] if p]
    compose = Compose(runner, paths.entry_file, paths.root, profiles, env)
    return Context(
        paths=paths,
        config=config,
        output=output,
        runner=runner,
        docker=docker,
        host=Host(runner, docker),
        compose=compose,
        target=ComposeTarget(paths, config, compose, docker),
        dry_run=dry_run,
        yes=yes,
        json_mode=json_mode,
        debug=debug,
    )
