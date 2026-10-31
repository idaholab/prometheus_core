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

"""Fixtures for the unit tests: a FakeRunner, a throwaway platform folder and a Context."""

from __future__ import annotations

import io
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from platformctl.config import PlatformConfig
from platformctl.context import Context, build
from platformctl.output import Output, Scrubber
from platformctl.paths import Paths
from platformctl.system.runner import Result


@dataclass
class FakeRunner:
    """Records each argv and returns canned results.

    `responses` maps an argv prefix (tuple) to a Result; the longest matching prefix wins.
    """

    responses: dict[tuple[str, ...], Result] = field(default_factory=dict)
    """Canned results by argv prefix."""
    calls: list[list[str]] = field(default_factory=list)
    """Every argv run, in order."""
    envs: list[Mapping[str, str] | None] = field(default_factory=list)
    """The environment each call was given."""
    raises: dict[str, Exception] = field(default_factory=dict)
    """Exceptions to raise, by command name."""

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, **_: object) -> Result:
        """Record the call and return the canned result with the longest matching prefix, else success."""
        argv = list(argv)
        self.calls.append(argv)
        self.envs.append(env)
        if argv[0] in self.raises:
            raise self.raises[argv[0]]
        for size in range(len(argv), 0, -1):
            hit = self.responses.get(tuple(argv[:size]))
            if hit is not None:
                return Result(argv, hit.returncode, hit.stdout, hit.stderr)
        return Result(argv, 0)

    def execvp(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
        """Record the call instead of replacing the process."""
        self.calls.append(list(argv))
        self.envs.append(env)

    def reply(self, *prefix: str, code: int = 0, stdout: str = "", stderr: str = "") -> None:
        """Make commands starting with `prefix` return this result."""
        self.responses[prefix] = Result(list(prefix), code, stdout, stderr)


DOCKER_INFO = (
    '{"ServerVersion": "29.1.0", "OperatingSystem": "Docker Desktop", "Architecture": "aarch64",'
    ' "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]], "SecurityOptions": ["name=seccomp"],'
    ' "Name": "docker-desktop", "ClientInfo": {"Context": "desktop-linux"}}'
)
"""A recorded `docker info` from Docker Desktop on a Mac with the containerd store."""


@pytest.fixture
def runner() -> FakeRunner:
    """A `FakeRunner` that answers `docker info`, `docker compose version` and `git log` like a healthy machine."""
    fake = FakeRunner()
    fake.reply("docker", "info", stdout=DOCKER_INFO)
    fake.reply("docker", "compose", "version", stdout="v2.40.0\n")
    fake.reply("git", "-C", code=0, stdout="2026-10-30-abc1234\n")
    return fake


@pytest.fixture
def platform_root(tmp_path: Path) -> Path:
    """A minimal platform folder: a compose file and one agent."""
    root = tmp_path / "platform"
    (root / "agents" / "client-agent").mkdir(parents=True)
    (root / "agents" / "client-agent" / "docker-compose.yml").write_text("services: {}\n")
    (root / "docker-compose.yml").write_text("services: {}\n")
    return root


def make_context(
    root: Path, runner: FakeRunner, env: dict[str, str] | None = None, sets: dict[str, str] | None = None, **kw
) -> tuple[Context, io.StringIO, io.StringIO]:
    """Build a real `Context` over a fake runner, returning it with its captured stdout and stderr."""
    out, err = io.StringIO(), io.StringIO()
    env = {"PATH": "/usr/bin"} if env is None else env
    config = PlatformConfig(root, env, sets)
    scrubber = Scrubber()
    scrubber.add_all(config.secret_values())
    output = Output(scrubber, out=out, err=err, env=env)
    ctx = build(Paths(root), config, output, runner, **kw)  # type: ignore[arg-type]
    return ctx, out, err


GOLDEN = Path(__file__).resolve().parent / "golden"
"""Where the golden JSON files live."""


def _normalized(value, root: Path):
    """`value` with the temporary platform folder and the git-derived platform version replaced by placeholders."""
    if isinstance(value, dict):
        return {
            k: "<version>" if k in ("version", "platform_version") and isinstance(v, str) else _normalized(v, root)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_normalized(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), "<root>")
    return value


def assert_golden(name: str, body: dict, root: Path) -> None:
    """Compare a `--json` object with `golden/<name>.json`, so a changed field name or shape fails a test.

    Run with `UPDATE_GOLDEN=1` to rewrite the file, then review the diff: the contract only
    grows within a `schema_version`.
    """
    text = json.dumps(_normalized(body, root), indent=2, sort_keys=True) + "\n"
    path = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text)
    assert path.read_text() == text, f"{path.name} differs; if the change is intended, run with UPDATE_GOLDEN=1"


@pytest.fixture
def ctx_factory(platform_root: Path, runner: FakeRunner):
    """A function that builds a context over the temporary platform folder and the fake runner."""

    def factory(env=None, sets=None, **kw):
        """Build a context with the given environment, `--set` values and options."""
        return make_context(platform_root, runner, env, sets, **kw)

    return factory
