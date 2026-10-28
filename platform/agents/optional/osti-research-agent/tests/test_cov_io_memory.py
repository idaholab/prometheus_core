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
"""Tests for RedisCaches key layout and lazy client construction (fake Redis)."""

from research_agent import memory
from research_agent.memory import RedisCaches


class FakeRedisClient:
    def __init__(self, decode_responses):
        self.decode_responses = decode_responses
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex


def _patched(monkeypatch):
    built = []

    def fake_from_url(url, *, decode_responses, password):
        built.append((url, decode_responses, password))
        return FakeRedisClient(decode_responses)

    monkeypatch.setattr(memory.redis.Redis, "from_url", staticmethod(fake_from_url))
    return built


def test_clients_are_built_lazily_once_each(monkeypatch):
    built = _patched(monkeypatch)
    caches = RedisCaches("redis://h:6379/0", "pw")

    assert built == []
    text = caches.client
    binary = caches.binary_client

    assert caches.client is text and caches.binary_client is binary
    assert built == [("redis://h:6379/0", True, "pw"), ("redis://h:6379/0", False, "pw")]
    assert text.decode_responses is True and binary.decode_responses is False


def test_pdf_round_trip_uses_binary_client(monkeypatch):
    _patched(monkeypatch)
    caches = RedisCaches("redis://h")

    caches.put_pdf("42", b"%PDF", ttl_s=60)

    assert caches.get_pdf("42") == b"%PDF"
    assert caches.binary_client.ttls["osti:paper:pdf_bytes:42"] == 60
    assert caches.get_pdf("missing") is None


def test_artifacts_round_trip_uses_versioned_key(monkeypatch):
    _patched(monkeypatch)
    caches = RedisCaches("redis://h")

    caches.put_artifacts("42", b"tar", ttl_s=5)

    assert caches.get_artifacts("42") == b"tar"
    assert "osti:paper:artifacts:v1:42" in caches.binary_client.store


def test_figjson_round_trip_uses_text_client(monkeypatch):
    _patched(monkeypatch)
    caches = RedisCaches("redis://h")

    caches.put_figjson("42", 3, '{"readable": true}', ttl_s=7)

    assert caches.get_figjson("42", 3) == '{"readable": true}'
    assert caches.client.ttls["osti:paper:figjson:v1:42:3"] == 7
    assert caches.get_figjson("42", 4) is None
