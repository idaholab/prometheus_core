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

"""Tests for the shared Redis connection factory."""

import logging

from prometheus_api.redis_utils import create_redis_client, redis_url_from_env


def test_unreachable_redis_returns_none_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="prometheus_api.redis_utils"):
        client = create_redis_client("redis://localhost:1/0")
    assert client is None
    assert any("Redis unavailable" in record.message for record in caplog.records)


def test_url_from_env(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert redis_url_from_env() == "redis://localhost:6379"
    monkeypatch.setenv("REDIS_URL", "redis://example:6380")
    assert redis_url_from_env() == "redis://example:6380"


def test_explicit_password_overrides_env(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "from-env")
    client = create_redis_client("redis://localhost:1/0", password="explicit", ping=False)
    # ping=False: client object is built without contacting the server.
    assert client is not None
    assert client.connection_pool.connection_kwargs["password"] == "explicit"


def test_env_password_used_when_not_passed(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "from-env")
    client = create_redis_client("redis://localhost:1/0", ping=False)
    assert client is not None
    assert client.connection_pool.connection_kwargs["password"] == "from-env"
