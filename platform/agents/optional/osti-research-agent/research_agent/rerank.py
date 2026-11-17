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

"""Rank every search hit of a run against the research question.

Each search API ranks only its own results, against its own query. Before the
orchestrator picks what to download, ``rank_hits`` puts every unread hit from
every search in one order, by two signals over title + abstract:

- **BM25** keyword relevance to the question, computed here over the
  candidates themselves (no index, no dependency). It rewards the exact terms
  embeddings blur, such as "316" or "400 C".
- **Embedding** cosine similarity to the question, which rewards papers worded
  differently from it.

The two rankings are fused by reciprocal rank fusion (``scholarly.RRF_K``), so
their incompatible scales don't matter. If embedding fails, BM25 alone ranks.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from research_agent.knowledge import cosine
from research_agent.scholarly import RRF_K

logger = logging.getLogger(__name__)

EmbedBatchFn = Callable[[List[str]], Awaitable[List[List[float]]]]

# Okapi BM25 parameters (Robertson & Zaragoza's usual defaults).
BM25_K1 = 1.2
BM25_B = 0.75

# Text sent to the embedder per hit; abstracts past this add little.
_EMBED_CHARS = 2000
# Ranking runs inside a time-limited research run, and the embedder's own HTTP
# timeout is 60 s; past this, rank by BM25 alone. A batch of ~30 abstracts
# took about 2-5 s in testing.
EMBED_TIMEOUT_S = 20.0

# Words that carry no topic in a research question.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it of on or that the "
    "this to was were what which with does do can its their there these those "
    "between under over into about than then".split()
)
# Words, and numbers with their decimal point ("15", "0.5", "316l").
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokenize(text: str) -> List[str]:
    """Lowercase word and number tokens, without stopwords."""
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOPWORDS]


def hit_text(hit: dict) -> str:
    """Title plus abstract; OSTI hits keep their abstract in ``description``."""
    abstract = hit.get("abstract") or hit.get("description") or ""
    return f"{hit.get('title') or ''}. {abstract}".strip()


def bm25_scores(query: str, documents: Sequence[str]) -> List[float]:
    """Okapi BM25 score of each document for ``query``, with document
    frequencies taken from ``documents`` themselves."""
    docs = [tokenize(d) for d in documents]
    if not docs:
        return []
    terms = set(tokenize(query))
    avg_len = sum(len(d) for d in docs) / len(docs) or 1.0
    df = {t: sum(1 for d in docs if t in d) for t in terms}
    n = len(docs)
    scores = []
    for doc in docs:
        tf = Counter(doc)
        score = 0.0
        for term in terms:
            if not tf[term]:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            norm = tf[term] + BM25_K1 * (1 - BM25_B + BM25_B * len(doc) / avg_len)
            score += idf * tf[term] * (BM25_K1 + 1) / norm
        scores.append(score)
    return scores


def _ranks(scores: Sequence[float]) -> List[int]:
    """1-based rank of each score, highest first; ties keep input order."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ranks = [0] * len(scores)
    for rank, i in enumerate(order, start=1):
        ranks[i] = rank
    return ranks


async def rank_hits(
    question: str,
    hits: List[Tuple[str, dict]],
    embed_batch: Optional[EmbedBatchFn],
    cache: Dict[str, List[float]],
) -> List[dict]:
    """Rank ``(source_id, hit)`` pairs against ``question``, best first.

    Returns one dict per hit: ``source_id``, ``score`` (the fused RRF score),
    ``bm25_rank``, and ``embedding_rank`` (None when embeddings are
    unavailable). Ties keep the input order. ``cache`` maps source_id (and the
    question under a reserved key) to its embedding, so a later call only
    embeds new hits."""
    if not hits:
        return []
    texts = [hit_text(hit) for _, hit in hits]
    bm25_rank = _ranks(bm25_scores(question, texts))
    embedding_rank = await _embedding_ranks(question, hits, texts, embed_batch, cache)

    ranked = []
    for i, (source_id, _) in enumerate(hits):
        score = 1.0 / (RRF_K + bm25_rank[i])
        if embedding_rank is not None:
            score += 1.0 / (RRF_K + embedding_rank[i])
        ranked.append(
            {
                "source_id": source_id,
                "score": score,
                "bm25_rank": bm25_rank[i],
                "embedding_rank": embedding_rank[i] if embedding_rank else None,
            }
        )
    # Stable sort: ties keep the order the hits were found in.
    return sorted(ranked, key=lambda r: -r["score"])


_QUESTION_KEY = "\0question:"


async def _embedding_ranks(
    question: str,
    hits: List[Tuple[str, dict]],
    texts: List[str],
    embed_batch: Optional[EmbedBatchFn],
    cache: Dict[str, List[float]],
) -> Optional[List[int]]:
    """Cosine-similarity rank of each hit, or None if embedding is unavailable."""
    if embed_batch is None:
        return None
    question_key = _QUESTION_KEY + question
    missing = [question_key] if question_key not in cache else []
    missing += [sid for sid, _ in hits if sid not in cache]
    if missing:
        by_id = {sid: text for (sid, _), text in zip(hits, texts)}
        batch = [question if key == question_key else by_id[key] for key in missing]
        try:
            vectors = await asyncio.wait_for(
                embed_batch([t[:_EMBED_CHARS] for t in batch]), EMBED_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Reranking without embeddings: no response in %.0f s", EMBED_TIMEOUT_S
            )
            return None
        except Exception as e:  # ranking must never stop a run
            logger.warning("Reranking without embeddings: %s", e)
            return None
        if len(vectors) != len(batch) or not all(vectors):
            logger.warning(
                "Reranking without embeddings: got %d vectors for %d texts",
                len(vectors),
                len(batch),
            )
            return None
        cache.update(zip(missing, vectors))
    qvec = cache[question_key]
    return _ranks([cosine(qvec, cache[sid]) for sid, _ in hits])
