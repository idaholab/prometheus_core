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

"""Checks on `.env`: required values, the base-image pin, hidden and derived keys, file mode."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

from platformctl.config import DERIVED_KEYS
from platformctl.diagnostics.base import (
    FAIL,
    FIX_SAFE,
    FIX_YES,
    FIX_YOU,
    PASS,
    SKIP,
    TAG_DIAGNOSE,
    TAG_PREFLIGHT,
    WARN,
    Check,
    Result,
)

if TYPE_CHECKING:
    from platformctl.context import Context

# Blank or placeholder values `.env.example` ships with.
PLACEHOLDERS = ("sk-ant-...", "sk-change-me", "change-me")
REQUIRED = (
    "AGENT_SECRET",
    "REDIS_PASSWORD",
    "ADMIN_DB_PASSWORD",
    "BACKEND_JWT_SECRET",
    "ADMIN_DB_ENCRYPTION_KEY",
    "LLM_CONFIG_PROFILE",
)


def _unset(value: str | None) -> bool:
    return not value or value.startswith(("change-me", "your-")) or value in PLACEHOLDERS


def check_platform_env(ctx: Context) -> Result:
    path = ctx.paths.env
    if not path.exists():
        return Result(
            FAIL,
            ".env does not exist",
            "Run `make init-env`: it creates .env, fills blank secrets and asks for the LLM profile and key.",
        )
    if ctx.config.dotenv_error is not None:
        return Result(FAIL, f".env has a bad line ({ctx.config.dotenv_error})", "Fix that line in .env.")
    values = ctx.config.dotenv
    missing = [key for key in REQUIRED if _unset(values.get(key))]
    if missing:
        return Result(
            FAIL,
            "not set: " + ", ".join(missing),
            "Run `make init-env`: it fills blank secrets and asks for the LLM profile and key.",
        )
    return Result(PASS, f"{len(REQUIRED)} required values are set")


def check_base_image_pin(ctx: Context) -> Result:
    dotenv = ctx.config.dotenv
    if ctx.config.local_sdk:
        return Result(PASS, "LOCAL_SDK=true: the base image is built from ../sdk")
    for key in ("PROMETHEUS_API_BASE_IMAGE_HASH", "PROMETHEUS_API_BASE_IMAGE_REPO"):
        if key in dotenv and dotenv[key] == "":
            return Result(
                WARN,
                f"{key} is blank in .env (the tool falls back to the default; a hand-run Compose fails with 'invalid reference format')",
                f"Remove the empty {key}= line from .env, or set LOCAL_SDK=true.",
            )
    repo, tag = ctx.config.base_image()
    return Result(PASS, f"the base image is {repo}:{tag}")


def check_env_hides_environment(ctx: Context) -> Result:
    hidden = ctx.config.env_hiding_value()
    if not hidden:
        return Result(PASS, "no .env value hides a different environment value")
    return Result(
        WARN,
        "the .env value wins over a different environment value for: " + ", ".join(hidden),
        "Remove the line from .env, or unset the environment variable, so only one is set.",
    )


def check_env_derived_keys(ctx: Context) -> Result:
    keys = [k for k in ctx.config.hidden_by_dotenv(DERIVED_KEYS)]
    if not keys:
        return Result(PASS, ".env sets no key the tool derives")
    return Result(
        WARN,
        ".env sets " + ", ".join(keys) + ", which a hand-run `docker compose` will use instead of the derived value",
        "Remove those lines from .env unless you want a hand-run Compose to differ from ./platformctl.",
    )


def check_env_file(ctx: Context) -> Result:
    path = ctx.paths.env
    if not path.exists():
        return Result(SKIP, ".env does not exist")
    if ctx.host.on_windows_drive(ctx.paths.root):
        return Result(SKIP, "file modes have no effect on a /mnt drive")
    mode = stat.S_IMODE(path.stat().st_mode)
    problems = []
    if mode & 0o077:
        problems.append(f"mode is {mode:04o}, readable by others")
    if _tracked_or_unignored(ctx):
        problems.append("not ignored by git")
    if problems:
        return Result(
            WARN,
            ".env " + " and ".join(problems),
            "Run `chmod 600 .env` and make sure `.env` is in .gitignore.",
        )
    return Result(PASS, ".env is mode 0600 and ignored by git")


def _tracked_or_unignored(ctx: Context) -> bool:
    root = str(ctx.paths.root)
    if ctx.runner.run(["git", "-C", root, "ls-files", "--error-unmatch", ".env"]).ok:
        return True  # tracked
    ignored = ctx.runner.run(["git", "-C", root, "check-ignore", "-q", ".env"])
    inside_git = ctx.runner.run(["git", "-C", root, "rev-parse", "--is-inside-work-tree"]).ok
    return inside_git and not ignored.ok


PLATFORM_ENV = Check("platform-env", "platform", (TAG_PREFLIGHT, TAG_DIAGNOSE), check_platform_env, fix_kind=FIX_YES)
BASE_IMAGE_PIN = Check(
    "base-image-pin", "laptop", (TAG_PREFLIGHT, TAG_DIAGNOSE), check_base_image_pin, fix_kind=FIX_YES
)
ENV_HIDES_ENVIRONMENT = Check(
    "env-hides-environment", "platform", (TAG_DIAGNOSE,), check_env_hides_environment, fix_kind=FIX_YOU
)
ENV_DERIVED_KEYS = Check("env-derived-keys", "platform", (TAG_DIAGNOSE,), check_env_derived_keys, fix_kind=FIX_YOU)
ENV_FILE = Check("env-file", "platform", (TAG_PREFLIGHT, TAG_DIAGNOSE), check_env_file, fix_kind=FIX_SAFE)
