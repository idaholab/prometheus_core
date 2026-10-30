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

"""Shared test setup: the `--live` option and its refusal under coverage."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register `--live`, which runs the live tests against the real Docker."""
    parser.addoption("--live", action="store_true", default=False, help="Run the live tests against the real Docker")


def coverage_active(config: pytest.Config) -> bool:
    """True when pytest-cov is collecting coverage (live tests never count toward it)."""
    return bool(getattr(config.option, "cov_source", None))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the live tests unless `--live` is given, and refuse `--live` under coverage."""
    live = config.getoption("--live")
    if live and coverage_active(config):
        raise pytest.UsageError("--live can't run with coverage: live tests never count toward it")
    if live:
        return
    skip = pytest.mark.skip(reason="live test: run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
