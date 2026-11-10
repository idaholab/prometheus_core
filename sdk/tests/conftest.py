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

"""Pytest configuration for prometheus_api tests.

The tests are two suites, kept apart:

- `tests/unit/` tests the code, one module or feature at a time, and is the
  suite measured by coverage (`fail_under`). Its tests claim no requirements.
- `tests/requirements/` proves the specs in `specs/`, one file per spec. Every
  test there claims what it proves with `@pytest.mark.covers(ID, how)`, and CI
  uploads its speccheck results as the evidence. It isn't measured by coverage.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from prometheus_api.agent import PrometheusAgent

TESTS = Path(__file__).resolve().parent
"""The tests folder."""


def pytest_collection_modifyitems(config, items):
    """Mark integration tests, and keep the unit and requirements suites apart.

    Collection fails on a unit test that claims a requirement, and on a
    requirements test that claims none.
    """
    problems = []
    for item in items:
        if "test_integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        path = Path(str(item.path)).resolve()
        if TESTS not in path.parents:
            continue
        suite = path.relative_to(TESTS).parts[0]
        claims = item.get_closest_marker("covers") is not None
        if suite == "unit" and claims:
            problems.append(
                f"{item.nodeid}: a unit test claims no requirement; "
                "prove requirements in tests/requirements/"
            )
        elif suite == "requirements" and not claims:
            problems.append(
                f"{item.nodeid}: a requirements test claims what it proves "
                "with @pytest.mark.covers(ID, how)"
            )
    if problems:
        raise pytest.UsageError("\n".join(problems))


@pytest.fixture(autouse=True)
def _disable_identity_for_legacy_tests(request, monkeypatch):
    """Default all tests to USER_IDENTITY_REQUIRED=false.

    Tests in test_identity.py supply their own identity env vars via an
    autouse fixture that takes precedence over this one (last-writer wins for
    monkeypatch within the same scope).  All other tests pre-date identity and
    test agent mechanics without attaching a userToken — this fixture keeps
    them passing by defaulting to non-required mode.
    """
    # Skip if the test's own module already sets USER_IDENTITY_REQUIRED.
    if "test_identity" not in str(request.fspath):
        monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")


@pytest.fixture(autouse=True)
def _stub_execution_records_for_legacy_tests(request, monkeypatch):
    """Keep A2A transport tests independent of external DeepLynx credentials."""
    if "test_a2a_payloads.py" not in str(request.fspath):
        return

    next_id = 0

    class FakeItems:
        async def create(self, item):
            nonlocal next_id
            next_id += 1
            return SimpleNamespace(id=next_id)

    class FakeStorageClient:
        def __init__(self, config):
            self.items = FakeItems()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def get_credential(self, resource, scope=None):
        assert resource == "deeplynx"
        return SimpleNamespace(
            value={
                "org_id": 1,
                "project_id": 2,
                "key": "test-key",
                "secret": "test-secret",
            }
        )

    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", FakeStorageClient)
    monkeypatch.setattr(PrometheusAgent, "get_credential", get_credential)
