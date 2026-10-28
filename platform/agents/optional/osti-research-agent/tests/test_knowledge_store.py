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

"""Tests for RedisKnowledgeStore with fake Redis and a deterministic embedder.

Covers the store->search round-trip and cosine ranking, the near-duplicate
cached-answer hit, lazy backfill of legacy atomic facts missing an embedding, and
bulk backfill - all without a real Redis or embedding model, and using SCAN
(never KEYS)."""

import asyncio
import fnmatch
import json
import re

from research_agent.knowledge import RedisKnowledgeStore

# A tiny fixed vocabulary; each embedding dimension counts a keyword, so cosine
# similarity reflects shared keywords. Deterministic and offline.
_VOCAB = [
    "titanium",
    "creep",
    "steel",
    "corrosion",
    "temperature",
    "high",
    "rate",
    "resistance",
    "neutron",
    "irradiation",
]


async def _embed(text: str):
    tokens = re.findall(r"[a-z]+", text.lower())
    return [float(tokens.count(word)) for word in _VOCAB]


class FakeRedis:
    """Minimal decode_responses=True Redis: string values, SCAN, sets."""

    def __init__(self):
        self.store = {}
        self.sets = {}

    def set(self, key, value, ex=None):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def mget(self, keys):
        return [self.store.get(k) for k in keys]

    def scan_iter(self, match="*", count=100):
        for key in list(self.store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)


def _store():
    return RedisKnowledgeStore(FakeRedis(), _embed)


# --- atomic facts ---------------------------------------------------------


def test_store_and_search_round_trip_ranks_by_cosine():
    store = _store()

    async def run():
        await store.store_fact(
            content="titanium creep at high temperature",
            source_id="1",
            source_title="Ti paper",
            source_url="http://osti/1",
        )
        await store.store_fact(
            content="steel corrosion resistance",
            source_id="2",
        )
        return await store.search_facts("titanium creep", k=8)

    results = asyncio.run(run())
    ids = [r["source_id"] for r in results]
    assert ids == ["1"]  # steel/corrosion fact is below the relevance floor
    assert results[0]["title"] == "Ti paper"
    assert results[0]["url"] == "http://osti/1"


def test_search_without_redis_returns_empty():
    store = RedisKnowledgeStore(None, _embed)
    assert asyncio.run(store.search_facts("anything")) == []


def test_store_fact_uses_scan_not_keys():
    store = _store()
    redis = store._redis
    # scan_iter is the only iteration primitive; keys() the store must not use.
    redis.keys = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call KEYS")
    )

    async def run():
        await store.store_fact(content="titanium creep rate", source_id="1")
        return await store.search_facts("titanium creep")

    results = asyncio.run(run())
    assert results and results[0]["source_id"] == "1"


# --- cached answers -------------------------------------------------------


def test_cached_answer_exact_and_near_duplicate():
    store = _store()

    async def run():
        await store.cache_answer(
            "titanium creep rate", "creep rate is X", [{"source": "OSTI #1"}]
        )
        exact = await store.get_cached_answer("titanium creep rate")
        near = await store.get_cached_answer("titanium creep rate?")  # different hash
        miss = await store.get_cached_answer("steel corrosion")
        return exact, near, miss

    exact, near, miss = asyncio.run(run())
    assert exact["answer"] == "creep rate is X"
    assert near["answer"] == "creep rate is X"  # cosine ~1.0 near-duplicate
    assert miss is None


# --- lazy + bulk backfill -------------------------------------------------


def _seed_legacy_atomic_fact(redis, fid, content, osti_id):
    redis.set(
        f"osti:factoid:{fid}",
        json.dumps(
            {
                "factoid_id": fid,
                "content": content,
                "source_paper": {"osti_id": osti_id, "title": "T", "url": "u"},
                "topics": [],
                "confidence": 0.85,
            }
        ),
    )


def test_search_lazily_backfills_missing_embedding():
    store = _store()
    redis = store._redis
    _seed_legacy_atomic_fact(redis, "legacy", "neutron irradiation of steel", "9")

    results = asyncio.run(store.search_facts("neutron irradiation"))
    assert results and results[0]["source_id"] == "9"
    # embedding was persisted back onto the legacy key
    stored = json.loads(redis.get("osti:factoid:legacy"))
    assert stored.get("embedding")


def test_backfill_all_counts_and_persists():
    store = _store()
    redis = store._redis
    _seed_legacy_atomic_fact(redis, "a", "titanium creep", "1")
    _seed_legacy_atomic_fact(redis, "b", "steel corrosion", "2")

    count = asyncio.run(store.backfill_all())
    assert count == 2
    assert json.loads(redis.get("osti:factoid:a")).get("embedding")
    assert json.loads(redis.get("osti:factoid:b")).get("embedding")
    # re-running is a no-op (everything already embedded)
    assert asyncio.run(store.backfill_all()) == 0
