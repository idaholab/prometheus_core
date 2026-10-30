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

"""The `--json` contract: one object on every exit path, on stdout only.

See plans/platformctl/design.md, "JSON contract". Fields are only added within a
schema version; removing or changing one bumps SCHEMA_VERSION.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

SCHEMA_VERSION = 1

# A fixed list. New codes are added, never renamed.
ERROR_CODES = (
    "usage",
    "needs_terminal",
    "not_running",
    "docker_unavailable",
    "port_in_use",
    "running_elsewhere",
    "timeout",
    "config_invalid",
    "check_failed",
    "internal",
)

# Exit codes: 0 OK, 1 failure, 2 usage error, 3 platform not running, 130 interrupted.
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NOT_RUNNING, EXIT_INTERRUPTED = 0, 1, 2, 3, 130

# What this version supports, so a skill can branch on it instead of parsing versions.
FEATURES = ("doctor.checks.v1",)


def result(
    command: str,
    platform: dict[str, Any],
    *,
    ok: bool = True,
    error: dict[str, str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build the object every `--json` exit path prints."""
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": ok,
        "platform": platform,
    }
    if error is not None:
        if error["code"] not in ERROR_CODES:
            raise ValueError(f"unknown error code {error['code']!r}")
        body["error"] = {
            "code": error["code"],
            "message": error["message"],
            "hint": error.get("hint", ""),
            "check": error.get("check", ""),
        }
    body.update(fields)
    return body


def error_object(
    command: str, platform: dict[str, Any], code: str, message: str, hint: str = "", check: str = ""
) -> dict[str, Any]:
    return result(command, platform, ok=False, error={"code": code, "message": message, "hint": hint, "check": check})


def emit(body: dict[str, Any], stream: TextIO, scrub=lambda text: text) -> None:
    """Print one JSON object, scrubbed (the scrubber also matches JSON-escaped forms)."""
    stream.write(scrub(json.dumps(body, indent=2, sort_keys=True)) + "\n")
    stream.flush()
