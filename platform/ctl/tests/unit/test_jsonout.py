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

from __future__ import annotations

import io
import json

import pytest

from platformctl import jsonout

PLATFORM = {"root": "/p", "project": "x", "version": "v"}
"""A `platform` block for the JSON objects."""


def test_result_shape():
    """Every object has the schema version, command, ok and platform, plus the extra fields.

    Covers REQ-001-19.
    """
    body = jsonout.result("status", PLATFORM, services=[1])
    assert body == {"schema_version": 1, "command": "status", "ok": True, "platform": PLATFORM, "services": [1]}


def test_error_object_has_every_field():
    """Error object has every field.

    Covers REQ-001-19.
    """
    body = jsonout.error_object("up", PLATFORM, "port_in_use", "8600 is taken", "run down", "ports-free")
    assert body["ok"] is False
    assert body["error"] == {
        "code": "port_in_use",
        "message": "8600 is taken",
        "hint": "run down",
        "check": "ports-free",
    }
    assert jsonout.error_object("up", PLATFORM, "usage", "m")["error"]["hint"] == ""


def test_error_codes_are_the_fixed_list():
    """Error codes are the fixed list.

    Covers REQ-001-20.
    """
    assert jsonout.ERROR_CODES == (
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
    with pytest.raises(ValueError, match="unknown error code"):
        jsonout.error_object("up", PLATFORM, "made_up", "m")


def test_exit_codes():
    """The exit codes are 0, 1, 2, 3 and 130.

    Covers REQ-001-14.
    """
    assert (
        jsonout.EXIT_OK,
        jsonout.EXIT_FAIL,
        jsonout.EXIT_USAGE,
        jsonout.EXIT_NOT_RUNNING,
        jsonout.EXIT_INTERRUPTED,
    ) == (0, 1, 2, 3, 130)


def test_emit_prints_one_scrubbed_object():
    """Emit prints one scrubbed object."""
    out = io.StringIO()
    jsonout.emit(
        jsonout.result("x", PLATFORM, note="hide-this-value"), out, lambda text: text.replace("hide-this-value", "***")
    )
    assert json.loads(out.getvalue())["note"] == "***"
    assert out.getvalue().count("\n") > 1 and out.getvalue().endswith("}\n")
    plain = io.StringIO()
    jsonout.emit({"a": 1}, plain)
    assert json.loads(plain.getvalue()) == {"a": 1}
