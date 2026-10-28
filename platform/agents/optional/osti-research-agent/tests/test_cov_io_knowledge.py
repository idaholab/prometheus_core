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
"""Edge-case and failure-path tests for RedisKnowledgeStore over a fake Redis."""

import asyncio
import fnmatch
import json

from research_agent.knowledge import RedisKnowledgeStore, _question_key, cosine


class FakeRedis:
    """decode_responses=True Redis stand-in; ``fail`` names methods that raise."""

    def __init__(self, fail=()):
        self.store = {}
        self.sets = {}
        self.fail = set(fail)

    def _check(self, name):
        if name in self.fail:
            raise ConnectionError(f"{name} down")

    def set(self, key, value, ex=None):
        self._check("set")
        self.store[key] = value

    def get(self, key):
        self._check("get")
        return self.store.get(key)

    def mget(self, keys):
        self._check("mget")
        return [self.store.get(k) for k in keys]

    def scan_iter(self, match="*", count=100):
        self._check("scan_iter")
        for key in list(self.store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    def sadd(self, key, member):
        self._check("sadd")
        self.sets.setdefault(key, set()).add(member)


async def _unit_embed(text):
    return [1.0, 0.0]


async def _empty_embed(text):
    return []


async def _boom_embed(text):
    raise RuntimeError("embedder offline")


def _run(coro):
    return asyncio.run(coro)


# --- cosine ------------------------------------------------------------------


def test_cosine_is_zero_for_empty_or_mismatched_vectors():
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 2.0], [1.0]) == 0.0


def test_cosine_is_zero_when_a_vector_has_zero_norm():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_of_parallel_vectors_is_one():
    assert cosine([2.0, 0.0], [5.0, 0.0]) == 1.0


# --- search_facts / store_fact -------------------------------------------------


def test_search_returns_nothing_when_the_query_cannot_be_embedded():
    redis = FakeRedis()
    redis.store["osti:factoid:1"] = json.dumps({"content": "x", "embedding": [1.0, 0.0]})
    store = RedisKnowledgeStore(redis, _empty_embed)

    assert _run(store.search_facts("anything")) == []


def test_store_fact_without_redis_or_content_returns_empty_id():
    assert _run(RedisKnowledgeStore(None, _unit_embed).store_fact(
        content="c", source_id="1")) == ""
    assert _run(RedisKnowledgeStore(FakeRedis(), _unit_embed).store_fact(
        content="", source_id="1")) == ""


def test_store_fact_indexes_every_topic():
    redis = FakeRedis()
    store = RedisKnowledgeStore(redis, _unit_embed)

    fact_id = _run(store.store_fact(content="c", source_id="9", topics=["creep", "steel"]))

    assert fact_id
    assert redis.sets["osti:topic:creep:factoids"] == {fact_id}
    assert redis.sets["osti:topic:steel:factoids"] == {fact_id}
    assert redis.sets["osti:paper:9:facts"] == {fact_id}


def test_store_fact_returns_empty_id_when_redis_write_fails():
    store = RedisKnowledgeStore(FakeRedis(fail={"sadd"}), _unit_embed)

    assert _run(store.store_fact(content="c", source_id="9", topics=["t"])) == ""


# --- backfill ----------------------------------------------------------------


def test_backfill_all_without_redis_is_zero():
    assert _run(RedisKnowledgeStore(None, _unit_embed).backfill_all()) == 0


def test_backfill_skips_facts_without_content_or_embedding():
    redis = FakeRedis()
    redis.store["osti:factoid:empty"] = json.dumps({"factoid_id": "empty", "content": ""})
    redis.store["osti:factoid:text"] = json.dumps({"factoid_id": "text", "content": "c"})

    assert _run(RedisKnowledgeStore(redis, _empty_embed).backfill_all()) == 0
    assert "embedding" not in json.loads(redis.store["osti:factoid:text"])


def test_backfill_still_returns_vector_when_persisting_it_fails():
    redis = FakeRedis()
    redis.store["osti:factoid:a"] = json.dumps({"factoid_id": "a", "content": "c"})
    redis.fail.add("set")

    assert _run(RedisKnowledgeStore(redis, _unit_embed).backfill_all()) == 1


def test_backfill_uses_factoid_id_key_when_fact_has_no_key():
    redis = FakeRedis()
    store = RedisKnowledgeStore(redis, _unit_embed)

    vec = _run(store._backfill_fact_embedding({"factoid_id": "z", "content": "c"}))

    assert vec == [1.0, 0.0]
    assert json.loads(redis.store["osti:factoid:z"])["embedding"] == [1.0, 0.0]


# --- cached answers ------------------------------------------------------------


def test_get_cached_answer_without_redis_is_none():
    assert _run(RedisKnowledgeStore(None, _unit_embed).get_cached_answer("q")) is None


def test_get_cached_answer_is_none_when_redis_get_fails():
    store = RedisKnowledgeStore(FakeRedis(fail={"get"}), _unit_embed)

    assert _run(store.get_cached_answer("q")) is None


def test_corrupt_exact_hit_falls_through_to_near_duplicate_search():
    redis = FakeRedis()
    redis.store[_question_key("q")] = "{not json"
    redis.store[_question_key("other")] = json.dumps(
        {"question": "other", "answer": "A", "embedding": [1.0, 0.0]}
    )
    store = RedisKnowledgeStore(redis, _unit_embed)

    hit = _run(store.get_cached_answer("q"))

    assert hit["answer"] == "A"


def test_get_cached_answer_is_none_when_question_cannot_be_embedded():
    store = RedisKnowledgeStore(FakeRedis(), _boom_embed)

    assert _run(store.get_cached_answer("q")) is None


def test_cached_answers_without_embeddings_are_ignored():
    redis = FakeRedis()
    redis.store[_question_key("old")] = json.dumps({"question": "old", "answer": "A"})
    store = RedisKnowledgeStore(redis, _unit_embed)

    assert _run(store.get_cached_answer("new")) is None


def test_cache_answer_swallows_redis_write_failure():
    redis = FakeRedis(fail={"set"})
    store = RedisKnowledgeStore(redis, _unit_embed)

    assert _run(store.cache_answer("q", "a", [])) is None
    assert redis.store == {}


# --- _scan_json ----------------------------------------------------------------


def test_scan_json_is_empty_when_scan_fails():
    store = RedisKnowledgeStore(FakeRedis(fail={"scan_iter"}), _unit_embed)

    assert _run(store._scan_json("osti:factoid:*")) == []


def test_scan_json_is_empty_when_no_keys_match():
    store = RedisKnowledgeStore(FakeRedis(), _unit_embed)

    assert _run(store._scan_json("osti:factoid:*")) == []


def test_scan_json_is_empty_when_mget_fails():
    redis = FakeRedis(fail={"mget"})
    redis.store["osti:factoid:1"] = json.dumps({"content": "c"})

    assert _run(RedisKnowledgeStore(redis, _unit_embed)._scan_json("osti:factoid:*")) == []


def test_scan_json_skips_missing_corrupt_and_non_dict_values():
    class BytesKeyRedis(FakeRedis):
        def scan_iter(self, match="*", count=100):
            yield b"osti:factoid:bytes"
            yield "osti:factoid:gone"
            yield "osti:factoid:bad"
            yield "osti:factoid:list"

        def mget(self, keys):
            return [json.dumps({"content": "ok"}), None, "{bad", json.dumps([1, 2])]

    out = _run(RedisKnowledgeStore(BytesKeyRedis(), _unit_embed)._scan_json("x"))

    assert out == [{"content": "ok", "_key": "osti:factoid:bytes"}]


def test_cache_answer_without_redis_is_a_noop():
    assert _run(RedisKnowledgeStore(None, _boom_embed).cache_answer("q", "a", [])) is None
