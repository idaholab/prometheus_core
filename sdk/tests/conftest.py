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

"""Pytest configuration for prometheus_api tests."""

from types import SimpleNamespace

import pytest

from prometheus_api.agent import PrometheusAgent


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests in test_integration.py with the integration marker."""
    for item in items:
        if "test_integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


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
