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

"""The one registry of settings, and how a value is chosen.

Order: defaults < environment < `.env` < `--set`, the same as Make today.
Every key not marked safe here is secret and never printed (deny by default).
See plans/platformctl/design.md, "Settings and precedence" and "Secrets".
"""

from __future__ import annotations

import os
import platform as _platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformctl.system import envfile
from platformctl.system.runner import MAKE_VARIABLES, Runner, RunnerError

DEFAULT_BASE_IMAGE_REPO = "containers.github.inl.gov/genesis/prometheus_api"
DEFAULT_BASE_IMAGE_HASH = "1914b55"
DEFAULT_BUILD_CACHE = "ghcr.io/idaholab/prometheus_core/buildcache-prometheus"

TRUE_VALUES = {"true"}


@dataclass(frozen=True)
class Setting:
    name: str
    default: str
    description: str
    # A blank `.env` line normally wins ("kept blank"); these fall back to the default instead.
    blank_means_default: bool = False
    # Safe to print. Anything not in the registry is secret.
    safe: bool = True
    kind: str = "str"  # str | bool | int


def _s(name: str, default: str, description: str, **kw) -> Setting:
    return Setting(name, default, description, **kw)


SETTINGS: tuple[Setting, ...] = (
    _s("COMPOSE_PROJECT_NAME", "prometheus_platform", "Compose project name"),
    _s("LOCAL_SDK", "false", "Build the prometheus_api base image from ../sdk", kind="bool"),
    _s(
        "PROMETHEUS_API_BASE_IMAGE_REPO",
        DEFAULT_BASE_IMAGE_REPO,
        "Registry repo of the prometheus_api base image",
        blank_means_default=True,
    ),
    _s(
        "PROMETHEUS_API_BASE_IMAGE_HASH",
        DEFAULT_BASE_IMAGE_HASH,
        "Tag of the prometheus_api base image",
        blank_means_default=True,
    ),
    _s("DEBUG_AGENTS", "false", "Also include agents/debug-agents/*", kind="bool"),
    _s("OPTIONAL_AGENTS", "false", "Also include agents/optional/*", kind="bool"),
    _s("LOCAL_DEEPLYNX", "false", "Run DeepLynx next to the platform", kind="bool"),
    _s("DEEPLYNX_SERVER_PORT", "5000", "Host port of the local DeepLynx API", kind="int"),
    _s("DEEPLYNX_UI_PORT", "3000", "Host port of the local DeepLynx UI", kind="int"),
    _s("PROMETHEUS_SYSTEM_TESTING", "false", "Publish the client-agent port for system tests", kind="bool"),
    _s("PROMETHEUS_SYSTEM_TEST_URL", "", "URL the system tests use (default: the client-agent port)"),
    _s("CLIENT_AGENT_PORT", "8001", "Host port of the client agent", kind="int"),
    _s("PROFILE", "dev", "React frontend: dev, prod, or blank for none"),
    _s("UP_ARGS", "", "Extra arguments for `docker compose up`"),
    _s("CHECK", "true", "Wait for health and registration after starting", kind="bool"),
    _s("RESTART_AGENTS", "true", "Restart your agents after the platform restarts", kind="bool"),
    _s("WAIT_TIMEOUT", "600", "Seconds to wait for healthchecks", kind="int"),
    _s("CHECK_TIMEOUT", "300", "Seconds to wait for the registration check", kind="int"),
    _s("BACKEND_PORT", "8600", "Host port of the backend", kind="int"),
    _s("FRONTEND_DEV_PORT", "5150", "Host port of the dev frontend", kind="int"),
    _s("FRONTEND_PROD_PORT", "8080", "Host port of the prod frontend", kind="int"),
    _s("REDIS_LOCAL_PORT", "6379", "Host port of Valkey", kind="int"),
    _s("USE_BUILD_CACHE", "true", "Import the registry build cache (needs the containerd image store)", kind="bool"),
    _s("BUILD_CACHE", DEFAULT_BUILD_CACHE, "Prefix of the registry build cache"),
    _s("BUILD_CACHE_PLATFORM", "", "Build cache tag (default: the Docker daemon's architecture)"),
    _s("SKIP_PREREQUISITES", "", "Skip the prerequisite checks (CI)"),
    _s("PLATFORM_TARGET", "compose", "Where the platform runs: compose (k3d: not supported yet)"),
    _s("PLATFORM_SOURCE", "build", "Where the code comes from: build (image: not supported yet)"),
)

REGISTRY: dict[str, Setting] = {s.name: s for s in SETTINGS}

# Settings a hand-run Compose reads from .env, so a `.env` value hides the derived one.
DERIVED_KEYS = (
    "PROMETHEUS_API_BASE_IMAGE_REPO",
    "PROMETHEUS_API_BASE_IMAGE_HASH",
    "BUILD_CACHE",
    "BUILD_CACHE_PLATFORM",
    "USE_BUILD_CACHE",
)

SOURCE_DEFAULT, SOURCE_ENV, SOURCE_DOTENV, SOURCE_SET, SOURCE_MAKE = "default", "environment", ".env", "--set", "make"


class ConfigError(ValueError):
    """An invalid setting or `--set`."""


def is_safe(name: str) -> bool:
    """Deny by default: only registered, safe keys may be printed."""
    setting = REGISTRY.get(name)
    return bool(setting and setting.safe)


def parse_set(items: list[str]) -> dict[str, str]:
    """`--set KEY=VALUE` pairs. Refuses secret keys: they'd land in history and `ps`."""
    result: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ConfigError(f"--set expects KEY=VALUE, got {key or item!r}")
        if not is_safe(key):
            raise ConfigError(f"{key} can't be set with --set (it may be a secret): set {key} in .env instead")
        result[key] = value
    return result


def make_overrides(env: Mapping[str, str]) -> dict[str, str]:
    """Values of command-line variables given to `make` (`make X=y up`).

    Names come from the words after ` -- ` in MAKEFLAGS (`\\ ` unescaped), values from
    the environment, where Make exports them. Only when run through Make.
    """
    if env.get("PLATFORMCTL_VIA_MAKE") != "1":
        return {}
    flags = env.get("MAKEFLAGS", "")
    _, sep, tail = flags.partition(" -- ")
    if not sep:
        return {}
    words = re.split(r"(?<!\\) ", tail)
    result: dict[str, str] = {}
    for word in words:
        name = word.replace("\\ ", " ").partition("=")[0]
        if name and name in env:
            result[name] = env[name]
    return result


def platform_version(root: Path, runner: Runner) -> str:
    """`<commit date>-<7 char sha>` of the checkout, like the published image tags."""
    try:
        done = runner.run(["git", "-C", str(root), "log", "-1", "--format=%cs-%h", "--abbrev=7"], timeout=10)
    except RunnerError:
        return "unknown"
    version = done.stdout.strip()
    return version if done.ok and version else "unknown"


@dataclass(frozen=True)
class Value:
    value: str
    source: str


class PlatformConfig:
    """The resolved settings and where each came from."""

    def __init__(
        self,
        root: Path,
        env: Mapping[str, str] | None = None,
        sets: dict[str, str] | None = None,
    ) -> None:
        self.root = root
        self.env = dict(os.environ if env is None else env)
        self.dotenv_path = root / ".env"
        # A malformed .env is recorded, not raised, so `doctor` can report it. Every other
        # command calls `require_valid_dotenv()` and stops.
        self.dotenv_error: envfile.EnvFileError | None = None
        self.dotenv: dict[str, str] = {}
        if self.dotenv_path.exists():
            try:
                self.dotenv = envfile.read(self.dotenv_path)
            except envfile.EnvFileError as exc:
                self.dotenv_error = exc
        self.sets = sets or {}
        self.make = make_overrides(self.env)
        self._cache: dict[str, Value] = {}

    def require_valid_dotenv(self) -> None:
        if self.dotenv_error is not None:
            raise self.dotenv_error

    # -- resolution ----------------------------------------------------

    def resolve(self, name: str) -> Value:
        if name in self._cache:
            return self._cache[name]
        setting = REGISTRY.get(name)
        default = setting.default if setting else ""
        value = Value(default, SOURCE_DEFAULT)
        if name in self.env:
            value = Value(self.env[name], SOURCE_ENV)
        if name in self.dotenv:
            value = Value(self.dotenv[name], SOURCE_DOTENV)
        if name in self.make:
            value = Value(self.make[name], SOURCE_MAKE)
        if name in self.sets:
            value = Value(self.sets[name], SOURCE_SET)
        # A blank line wins over the environment, except where the default is meant.
        if setting and setting.blank_means_default and value.value == "":
            value = Value(setting.default, SOURCE_DEFAULT)
        self._cache[name] = value
        return value

    def get(self, name: str) -> str:
        return self.resolve(name).value

    def flag(self, name: str) -> bool:
        return self.get(name).strip().lower() in TRUE_VALUES

    def int(self, name: str) -> int:
        raw = self.get(name).strip()
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(
                f"{name} must be a number, got {'a blank value' if not raw else 'something else'}"
            ) from None

    # -- derived values ------------------------------------------------

    @property
    def project(self) -> str:
        return self.get("COMPOSE_PROJECT_NAME") or "prometheus_platform"

    @property
    def local_sdk(self) -> bool:
        return self.flag("LOCAL_SDK")

    def base_image(self) -> tuple[str, str]:
        """(repo, tag): `prometheus_api:local` with LOCAL_SDK, else the pin."""
        if self.local_sdk:
            return "prometheus_api", "local"
        return self.get("PROMETHEUS_API_BASE_IMAGE_REPO"), self.get("PROMETHEUS_API_BASE_IMAGE_HASH")

    def frontend_profile(self) -> str:
        profile = self.get("PROFILE").strip()
        return profile if profile in ("dev", "prod") else ""

    def hidden_by_dotenv(self, keys: tuple[str, ...] = DERIVED_KEYS) -> list[str]:
        """Derived keys that `.env` sets, which a hand-run Compose will use instead."""
        return [k for k in keys if k in self.dotenv]

    def env_hiding_value(self) -> list[str]:
        """Keys set in both the environment and `.env` with different values (by name only)."""
        return sorted(k for k in self.dotenv if k in self.env and self.env[k] != self.dotenv[k])

    def secret_values(self) -> list[str]:
        """Every value that must never be printed.

        All `.env` and `--set` keys not marked safe, and the environment's values for keys that
        `.env` also sets or whose names look like secrets. Other environment values (paths and
        the like) are left alone, or ordinary paths would print as `***`.
        """
        values: list[str] = []
        for source in (self.dotenv, self.sets):
            values.extend(v for k, v in source.items() if v and not is_safe(k))
        for key, value in self.env.items():
            if value and not is_safe(key) and (key in self.dotenv or _SECRET_NAME.search(key)):
                values.append(value)
        return values

    def secret_keys(self) -> list[str]:
        return sorted({k for k in {*self.dotenv, *self.sets} if not is_safe(k)})

    def child_env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """The environment for a child process, matching Make's.

        For keys in both the environment and `.env`, the `.env` value is passed. The derived
        values are added. Every other `.env` key is left for Compose to read itself. Make's own
        variables are dropped.
        """
        child = {k: v for k, v in self.env.items() if k not in MAKE_VARIABLES and k != "PLATFORMCTL_VIA_MAKE"}
        for key in self.dotenv:
            if key in child:
                child[key] = self.dotenv[key]
        repo, tag = self.base_image()
        child.update(
            COMPOSE_PROJECT_NAME=self.project,
            PROMETHEUS_API_BASE_IMAGE_REPO=repo,
            PROMETHEUS_API_BASE_IMAGE_HASH=tag,
        )
        for name in self.sets:
            child[name] = self.sets[name]
        for name, value in self.make.items():
            if name in REGISTRY:
                child[name] = value
        if extra:
            child.update(extra)
        return child


_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASS|CREDENTIAL|PRIVATE|AUTH", re.I)


def host_arch(docker_arch: str | None = None) -> str:
    """`arm64` or `amd64`, from the daemon's architecture (not `uname -m`, which lies under Rosetta)."""
    arch = (docker_arch or _platform.machine()).lower()
    return "arm64" if arch in ("arm64", "aarch64") else "amd64"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
