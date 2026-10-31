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


def pytest_configure(config: pytest.Config) -> None:
    """With `--live` and no path given, test `tests/live`: `testpaths` only lists `tests/unit`.

    The paths come from pytest's own parse of the command line, so an option's value (such as
    `--rootdir /some/folder`) is never taken for a test path.
    """
    named = getattr(config.known_args_namespace, "file_or_dir", None)
    if config.getoption("--live") and not named:
        config.args = [str(config.rootpath / "tests" / "live")]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the live tests unless `--live` is given; refuse `--live` under coverage or when it finds none."""
    live = config.getoption("--live")
    if live and coverage_active(config):
        raise pytest.UsageError("--live can't run with coverage: live tests never count toward it")
    if live:
        if not any(item.get_closest_marker("live") for item in items):
            raise pytest.UsageError("--live found no live tests to run: name a folder such as tests/live")
        return
    skip = pytest.mark.skip(reason="live test: run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
