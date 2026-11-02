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

"""The `--json` envelope."""

from __future__ import annotations

import io
import json

from speccheck import jsonout
from speccheck.specs import Problem


def test_the_envelope_and_emit():
    """The fixed fields, extra fields, and one line-safe object."""
    body = jsonout.envelope("lint", False, [Problem("a", 1, "b\n::x")], specs=[])
    assert body == {
        "schema_version": 1,
        "command": "lint",
        "ok": False,
        "problems": [{"path": "a", "line": 1, "message": "b\n::x"}],
        "specs": [],
    }
    stream = io.StringIO()
    jsonout.emit(body, stream)
    assert json.loads(stream.getvalue()) == body
    assert "\n::x" not in stream.getvalue()
    assert jsonout.error("verify", "no config")["error"] == {"code": "usage", "message": "no config"}


def test_emit_cant_start_a_log_command():
    """No line of the object starts `::`, and `##[` inside a string is written so a log ignores it."""
    body = jsonout.envelope("verify", False, [Problem("::error::x", 1, "##[error]y")])
    stream = io.StringIO()
    jsonout.emit(body, stream)
    text = stream.getvalue()
    assert json.loads(text) == body
    assert "##[" not in text and not any(line.lstrip().startswith("::") for line in text.splitlines())
