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

"""Embedding-backed atomic-fact store.

Replaces the retrieval internals of the legacy ``memory.py`` implementation:
each atomic fact carries an embedding, and retrieval uses ``SCAN`` plus
in-process cosine ranking instead of a blocking ``KEYS`` query and an LLM call.
The cached-answer path keeps the exact question-hash fast path and adds a
near-duplicate (cosine > 0.95) hit.

The legacy ``osti:factoid:{id}`` key prefix, ``factoid_id`` payload field, and
topic/paper indexes remain unchanged so existing atomic facts stay readable.
Missing embeddings are backfilled lazily on read or in bulk by
``scripts/backfill_atomic_fact_embeddings.py``.

Nothing here imports prometheus_api or a2a: ``redis_client`` is a plain redis-py
client (or None, degrading to empty results) and ``embed`` is injected.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

import redis

from research_agent.core.llm import EmbedFn

logger = logging.getLogger(__name__)

# Bound the SCAN sweep so lookup work remains predictable without requiring a
# Redis vector index.
_MAX_SCAN = 1000
# Below this cosine an atomic fact is considered irrelevant to the query.
_MIN_FACT_SCORE = 0.15
# A cached answer this close to the asked question is treated as the same
# question (the near-duplicate hit that replaces fuzzy check_memory).
_NEAR_DUP_THRESHOLD = 0.95


class KnowledgeStore(Protocol):
    async def search_facts(self, query: str, k: int = 8) -> List[Dict]: ...
    async def store_fact(
        self,
        *,
        content: str,
        source_id: str,
        source_title: str = "",
        source_url: str = "",
        topics: Optional[List[str]] = None,
        origin: str = "osti",
        question: str = "",
        confidence: float = 0.85,
    ) -> str: ...
    async def get_cached_answer(self, question: str) -> Optional[Dict]: ...
    async def cache_answer(
        self, question: str, answer: str, sources: List[Dict]
    ) -> None: ...


def cosine(a: List[float], b: List[float]) -> float:
    """Plain-Python cosine similarity; 0.0 for empty/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _question_key(question: str) -> str:
    qhash = hashlib.md5(question.lower().encode()).hexdigest()
    return f"osti:question:{qhash}:answer"


class RedisKnowledgeStore:
    """A :class:`KnowledgeStore` over redis-py (decode_responses=True) with an
    injected async ``embed`` function. Degrades to empty results when
    ``redis_client`` is None so the CLI's --no-redis mode and tests work."""

    def __init__(
        self,
        redis_client: Optional[redis.Redis],
        embed: EmbedFn,
        *,
        min_fact_score: float = _MIN_FACT_SCORE,
        near_dup_threshold: float = _NEAR_DUP_THRESHOLD,
    ):
        self._redis = redis_client
        self._embed = embed
        self._min_fact_score = min_fact_score
        self._near_dup_threshold = near_dup_threshold

    # --- atomic facts -----------------------------------------------------

    async def search_facts(self, query: str, k: int = 8) -> List[Dict]:
        if self._redis is None:
            return []
        qvec = await self._embed_safe(query)
        if not qvec:
            return []
        scored: List[tuple] = []
        for fact in await self._iter_atomic_facts():
            vec = fact.get("embedding") or await self._backfill_fact_embedding(fact)
            score = cosine(qvec, vec)
            if score >= self._min_fact_score:
                scored.append((score, fact))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [self._normalize_fact(f, score) for score, f in scored[:k]]

    async def store_fact(
        self,
        *,
        content: str,
        source_id: str,
        source_title: str = "",
        source_url: str = "",
        topics: Optional[List[str]] = None,
        origin: str = "osti",
        question: str = "",
        confidence: float = 0.85,
    ) -> str:
        if self._redis is None or not content:
            return ""
        topics = topics or []
        source_id = str(source_id)
        embedding = await self._embed_safe(content)
        fact_id = str(uuid.uuid4())
        atomic_fact = {
            # Retain the legacy field name for persisted-data compatibility.
            "factoid_id": fact_id,
            "content": content,
            "source": {
                "id": source_id,
                "title": source_title,
                "url": source_url,
                "origin": origin,
            },
            # Mirror the legacy shape so old readers (pipeline's
            # synthesize_from_memory) still resolve source metadata.
            "source_paper": {
                "osti_id": source_id,
                "title": source_title,
                "url": source_url,
            },
            "topics": topics,
            "embedding": embedding,
            "confidence": confidence,
            "extracted_at": _now_iso(),
            "question_answered": question,
        }
        try:
            await asyncio.to_thread(
                self._redis.set, f"osti:factoid:{fact_id}", json.dumps(atomic_fact)
            )
            if source_id:
                await asyncio.to_thread(
                    self._redis.sadd, f"osti:paper:{source_id}:facts", fact_id
                )
            for topic in topics:
                await asyncio.to_thread(
                    self._redis.sadd, f"osti:topic:{topic}:factoids", fact_id
                )
        except Exception as e:
            logger.warning("store_fact failed: %s", e)
            return ""
        return fact_id

    async def backfill_all(self) -> int:
        """Compute and persist embeddings for every atomic fact missing one.

        Returns the number backfilled. Used by the migration script."""
        if self._redis is None:
            return 0
        count = 0
        for fact in await self._iter_atomic_facts():
            if fact.get("embedding"):
                continue
            vec = await self._backfill_fact_embedding(fact)
            if vec:
                count += 1
        return count

    # --- cached answers ---------------------------------------------------

    async def get_cached_answer(self, question: str) -> Optional[Dict]:
        if self._redis is None:
            return None
        # Fast path: exact question hash.
        try:
            raw = await asyncio.to_thread(self._redis.get, _question_key(question))
        except Exception as e:
            logger.warning("cached-answer lookup failed: %s", e)
            return None
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        # Near-duplicate path: an earlier question close enough to reuse.
        qvec = await self._embed_safe(question)
        if not qvec:
            return None
        best: Optional[Dict] = None
        best_score = 0.0
        for payload in await self._iter_cached_answers():
            vec = payload.get("embedding")
            if not vec:
                continue
            score = cosine(qvec, vec)
            if score > best_score:
                best_score, best = score, payload
        if best is not None and best_score >= self._near_dup_threshold:
            return best
        return None

    async def cache_answer(
        self, question: str, answer: str, sources: List[Dict]
    ) -> None:
        if self._redis is None:
            return
        embedding = await self._embed_safe(question)
        payload = {
            "question": question,
            "answer": answer,
            "sources": sources,
            "embedding": embedding,
            "cached_at": _now_iso(),
        }
        try:
            await asyncio.to_thread(
                self._redis.set,
                _question_key(question),
                json.dumps(payload),
                30 * 24 * 3600,  # 30-day TTL (positional ex)
            )
        except Exception as e:
            logger.warning("cache_answer failed: %s", e)

    # --- internals --------------------------------------------------------

    async def _embed_safe(self, text: str) -> List[float]:
        try:
            return await self._embed(text)
        except Exception as e:
            logger.warning("embedding failed: %s", e)
            return []

    async def _iter_atomic_facts(self) -> List[Dict]:
        # The Redis key name predates the "atomic fact" terminology.
        return await self._scan_json("osti:factoid:*")

    async def _iter_cached_answers(self) -> List[Dict]:
        return await self._scan_json("osti:question:*:answer")

    async def _scan_json(self, pattern: str) -> List[Dict]:
        try:
            keys = await asyncio.to_thread(
                lambda: list(self._redis.scan_iter(match=pattern, count=200))
            )
        except Exception as e:
            logger.warning("SCAN %s failed: %s", pattern, e)
            return []
        if not keys:
            return []
        keys = keys[:_MAX_SCAN]
        try:
            values = await asyncio.to_thread(self._redis.mget, keys)
        except Exception as e:
            logger.warning("MGET failed: %s", e)
            return []
        out: List[Dict] = []
        for key, raw in zip(keys, values):
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(obj, dict):
                obj["_key"] = (
                    key if isinstance(key, str) else key.decode("utf-8", "replace")
                )
                out.append(obj)
        return out

    async def _backfill_fact_embedding(self, fact: Dict) -> List[float]:
        content = fact.get("content", "")
        if not content:
            return []
        vec = await self._embed_safe(content)
        if not vec:
            return []
        fact["embedding"] = vec
        key = fact.get("_key") or f"osti:factoid:{fact.get('factoid_id', '')}"
        payload = {k: v for k, v in fact.items() if k != "_key"}
        try:
            await asyncio.to_thread(self._redis.set, key, json.dumps(payload))
        except Exception as e:
            logger.debug("could not persist backfilled embedding for %s: %s", key, e)
        return vec

    @staticmethod
    def _normalize_fact(fact: Dict, score: float) -> Dict:
        src = fact.get("source")
        if not isinstance(src, dict):
            legacy = fact.get("source_paper") or {}
            src = {
                "id": legacy.get("osti_id", ""),
                "title": legacy.get("title", ""),
                "url": legacy.get("url", ""),
                "origin": "osti",
            }
        return {
            "content": fact.get("content", ""),
            "source_id": str(src.get("id", "")),
            "title": src.get("title", ""),
            "url": src.get("url", ""),
            "origin": src.get("origin", "osti"),
            "topics": fact.get("topics", []),
            "confidence": fact.get("confidence", 0.5),
            "score": round(score, 4),
        }
