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

"""The `--json` envelope: one object on every exit path, on stdout only.

Fields are only added within a schema version. Removing or changing one bumps SCHEMA_VERSION.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

from speccheck.specs import Problem

SCHEMA_VERSION = 1
"""The version of the `--json` envelope; removing or changing a field bumps it."""

EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE = 0, 1, 2
"""Exit codes: 0 fine, 1 problems found, 2 usage or config error."""


def envelope(command: str, ok: bool, problems: list[Problem], **fields: Any) -> dict[str, Any]:
    """The object every `--json` exit path prints."""
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": ok,
        "problems": [problem.to_json() for problem in problems],
    }
    body.update(fields)
    return body


def error(command: str, message: str) -> dict[str, Any]:
    """The object for a usage or config error, which has no other result."""
    return envelope(command, False, [], error={"code": "usage", "message": message})


def emit(body: dict[str, Any], stream: TextIO) -> None:
    """Print one JSON object that a CI log can't act on.

    `ensure_ascii` keeps control characters escaped, and every line starts with spaces or a
    bracket, so none can start `::`. A `##[` can only be inside a string, where `[` is written
    `\\u005b`, which reads back the same.
    """
    text = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=True).replace("##[", "##\\u005b")
    stream.write(text + "\n")
    stream.flush()
