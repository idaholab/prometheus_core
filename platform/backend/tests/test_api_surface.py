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

"""Guard the backend's behavioral HTTP surface against accidental change.

Fails when a path, method, success status, parameter, request body or schema
differs from ``tests/snapshots/api_surface.json``. Documentation-only edits
(summaries, descriptions, examples, tags, error responses) do not trip it; see
``tests/api_surface.py`` for exactly what is compared and how to regenerate the
golden file when a change is intentional.
"""

from __future__ import annotations

import difflib

from fastapi import FastAPI

from app.main import app
from tests.api_surface import SNAPSHOT_PATH, build_surface, render


def test_api_surface_matches_snapshot() -> None:
    expected = SNAPSHOT_PATH.read_text()
    actual = render(build_surface())
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile="snapshots/api_surface.json",
                tofile="live app",
            )
        )
        raise AssertionError(
            "The API surface changed. If intentional, regenerate with "
            "`uv run python -m tests.api_surface` and commit the diff.\n\n" + diff
        )


def test_new_endpoint_is_reported() -> None:
    """Adding a route without regenerating the snapshot must fail the guard above."""
    probe = FastAPI()
    probe.router.routes.extend(app.routes)

    @probe.get("/api/__surface_probe")
    def _probe() -> dict[str, str]:
        return {}

    actual = render(build_surface(probe))
    assert actual != SNAPSHOT_PATH.read_text()
    assert "/api/__surface_probe" in actual
