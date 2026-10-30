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

"""A compose project: `-f` entry file, profiles, and the verbs the compose target needs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from platformctl.system.runner import Result, Runner

# Compose 2.20 added `include:` and `additional_contexts`; `include: env_file` needs a later 2.x.
MIN_VERSION = (2, 20)
"""The oldest Compose that supports `include:` (2.20; `env_file` under it is unverified)."""


def parse_version(text: str) -> tuple[int, ...] | None:
    """`2.20.3` or `v5.6.1-desktop.1` -> (2, 20, 3)."""
    head = text.strip().lstrip("v").split("-")[0].split("+")[0]
    try:
        return tuple(int(part) for part in head.split("."))
    except ValueError:
        return None


@dataclass
class Compose:
    """A compose project, run through the generated entry file."""

    runner: Runner
    entry_file: Path
    cwd: Path
    profiles: Sequence[str] = ()
    env: Mapping[str, str] | None = None

    def argv(self, *args: str) -> list[str]:
        """`docker compose -f <entry> [--profile p]... <args>`."""
        argv = ["docker", "compose", "-f", self.entry_file.name]
        for profile in self.profiles:
            argv += ["--profile", profile]
        return [*argv, *args]

    def run(self, *args: str, capture: bool = True, interactive: bool = False, timeout: float | None = None) -> Result:
        """Run a Compose command and return its result."""
        return self.runner.run(
            self.argv(*args), env=self.env, cwd=self.cwd, capture=capture, interactive=interactive, timeout=timeout
        )

    def config(self) -> dict | None:
        """`docker compose config --format json`, or None when it fails."""
        done = self.run("config", "--format", "json")
        if not done.ok:
            return None
        try:
            return json.loads(done.stdout)
        except ValueError:
            return None

    def services(self) -> list[str]:
        """The names of the services in the project."""
        done = self.run("config", "--services")
        return done.stdout.split() if done.ok else []

    def ps(self) -> list[dict]:
        """The project's containers, including stopped ones, as dicts."""
        done = self.run("ps", "--all", "--format", "json")
        rows: list[dict] = []
        for line in done.stdout.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            rows.extend(row if isinstance(row, list) else [row])
        return rows

    def up(
        self,
        services: Sequence[str] = (),
        *,
        build: bool = True,
        detach: bool = True,
        wait: int | None = None,
        extra: Sequence[str] = (),
        capture: bool = False,
    ) -> Result:
        """Run `up`, optionally building, detached and waiting for health."""
        args = ["up"]
        if build:
            args.append("--build")
        if detach:
            args.append("-d")
        if wait is not None:
            args += ["--wait", "--wait-timeout", str(wait)]
        return self.run(*args, *extra, *services, capture=capture, interactive=not detach)

    def down(self, *, volumes: bool = False, remove_orphans: bool = False) -> Result:
        """Run `down`, optionally removing volumes and orphans."""
        args = ["down"]
        if remove_orphans:
            args.append("--remove-orphans")
        if volumes:
            args.append("-v")
        return self.run(*args, capture=False)

    def exec(self, service: str, argv: Sequence[str], *, tty: bool, env_names: Sequence[str] = ()) -> Result:
        """`exec`, passing `-T` without a terminal; `-e NAME` forwards values from our environment."""
        args = ["exec"]
        if not tty:
            args.append("-T")
        for name in env_names:
            args += ["-e", name]
        return self.run(*args, service, *argv)
