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
"""Ranking every unread search hit against the question: BM25, embeddings,
RRF fusion, the rank_candidates tool, and the keep-going nudge's order."""

import asyncio
import json
import math

from research_agent import rerank
from research_agent.core import deep_runner
from research_agent.core.config import AgentConfig
from research_agent.scholarly import RRF_K
from research_agent.tools import RunContext
from research_agent.tools.rank import build_rank_tools

QUESTION = "What is the creep rate of stainless steel 316 at 400 C and 15 MPa?"


def _ctx(embed_batch=None):
    ctx = RunContext(config=AgentConfig(litellm_base_url="http://unused"), complete=None)
    ctx.question = QUESTION
    ctx.embed_batch = embed_batch
    return ctx


def _embedder(vectors_by_word, calls=None):
    """Fake embed_batch: each text maps to the vector of the first keyword it
    contains, so tests choose the cosine order."""

    async def embed_batch(texts):
        if calls is not None:
            calls.append(list(texts))
        out = []
        for text in texts:
            low = text.lower()
            out.append(next((v for w, v in vectors_by_word.items() if w in low), [0.0, 0.0, 1.0]))
        return out

    return embed_batch


# --- tokens and BM25 --------------------------------------------------------


def test_tokenize_keeps_numbers_and_drops_stopwords():
    assert rerank.tokenize("The creep of 316L at 400.5 C") == ["creep", "316l", "400.5", "c"]


def test_hit_text_uses_the_osti_description():
    assert rerank.hit_text({"title": "T", "description": "osti abstract"}) == "T. osti abstract"
    assert rerank.hit_text({"title": "T", "abstract": "a"}) == "T. a"


def test_bm25_matches_a_hand_calculation():
    docs = ["creep creep steel", "steel", "zirconium oxide"]

    scores = rerank.bm25_scores("creep", docs)

    n, df, avg = 3, 1, (3 + 1 + 2) / 3
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    k1, b = rerank.BM25_K1, rerank.BM25_B
    expected = idf * 2 * (k1 + 1) / (2 + k1 * (1 - b + b * 3 / avg))
    assert math.isclose(scores[0], expected)
    assert scores[1] == 0.0 and scores[2] == 0.0


def test_bm25_rewards_exact_numbers():
    docs = ["Creep of 316 stainless steel at 400 C", "Creep of 304 stainless steel at 600 C"]

    scores = rerank.bm25_scores(QUESTION, docs)

    assert scores[0] > scores[1]


def test_bm25_of_no_documents_is_empty():
    assert rerank.bm25_scores("q", []) == []


# --- fusion -----------------------------------------------------------------


def _question_first_embedder(question_vector, vectors_by_word):
    inner = _embedder(vectors_by_word)

    async def embed_batch(texts):
        vecs = await inner(texts)
        return [question_vector if t == QUESTION else v for t, v in zip(texts, vecs)]

    return embed_batch


def test_embedding_rank_follows_cosine_similarity_to_the_question():
    hits = [("far", {"title": "far topic"}), ("near", {"title": "near topic"})]
    embed = _question_first_embedder(
        [1.0, 0.0, 0.0], {"near": [1.0, 0.1, 0.0], "far": [0.0, 1.0, 0.0]}
    )

    ranked = asyncio.run(rerank.rank_hits(QUESTION, hits, embed, {}))

    ranks = {r["source_id"]: r["embedding_rank"] for r in ranked}
    assert ranks == {"near": 1, "far": 2}


def test_fused_scores_follow_the_rrf_formula():
    # BM25 order: kw (1), both (2), sem (3) - by how many question terms match.
    hits = [
        ("kw", {"title": "creep rate stainless steel 316 400 15 mpa"}),
        ("both", {"title": "creep rate 316 400 alloy"}),
        ("sem", {"title": "deformation under load"}),
    ]
    # Embedding order against the question vector: sem (1), both (2), kw (3).
    embed = _question_first_embedder(
        [1.0, 0.0, 0.0],
        {"deformation": [1.0, 0.0, 0.0], "alloy": [0.8, 0.6, 0.0], "mpa": [0.0, 1.0, 0.0]},
    )

    ranked = asyncio.run(rerank.rank_hits(QUESTION, hits, embed, {}))

    by_id = {r["source_id"]: r for r in ranked}
    assert (by_id["kw"]["bm25_rank"], by_id["kw"]["embedding_rank"]) == (1, 3)
    assert (by_id["both"]["bm25_rank"], by_id["both"]["embedding_rank"]) == (2, 2)
    assert (by_id["sem"]["bm25_rank"], by_id["sem"]["embedding_rank"]) == (3, 1)
    for r in ranked:
        expected = 1 / (RRF_K + r["bm25_rank"]) + 1 / (RRF_K + r["embedding_rank"])
        assert math.isclose(r["score"], expected)
    # RRF slightly favours a first place: 1/61 + 1/63 > 2/62. kw and sem tie,
    # and the tie keeps the order found.
    assert [r["source_id"] for r in ranked] == ["kw", "sem", "both"]


def test_a_hit_both_signals_rank_first_wins_clearly():
    hits = [
        ("kw_only", {"title": "creep 316 400 mpa"}),
        ("best", {"title": "creep rate stainless steel 316 400 15 mpa"}),
        ("sem_only", {"title": "deformation under load"}),
    ]
    embed = _question_first_embedder(
        [1.0, 0.0, 0.0],
        {"stainless": [1.0, 0.0, 0.0], "deformation": [0.7, 0.7, 0.0], "creep 316": [0.0, 1.0, 0.0]},
    )

    ranked = asyncio.run(rerank.rank_hits(QUESTION, hits, embed, {}))

    assert ranked[0]["source_id"] == "best"
    assert (ranked[0]["bm25_rank"], ranked[0]["embedding_rank"]) == (1, 1)


def test_without_an_embedder_bm25_alone_ranks():
    hits = [("off", {"title": "Zirconium oxide"}), ("on", {"title": "Creep of 316 at 400 C"})]

    ranked = asyncio.run(rerank.rank_hits(QUESTION, hits, None, {}))

    assert [r["source_id"] for r in ranked] == ["on", "off"]
    assert all(r["embedding_rank"] is None for r in ranked)


def test_an_embedding_failure_falls_back_to_bm25(caplog):
    async def broken(texts):
        raise RuntimeError("embedding endpoint down")

    hits = [("a", {"title": "Creep of 316"}), ("b", {"title": "other"})]

    ranked = asyncio.run(rerank.rank_hits(QUESTION, hits, broken, {}))

    assert [r["source_id"] for r in ranked] == ["a", "b"]
    assert ranked[0]["embedding_rank"] is None
    assert "Reranking without embeddings: embedding endpoint down" in caplog.text


def test_a_slow_embedder_falls_back_to_bm25(monkeypatch, caplog):
    async def hangs(texts):
        await asyncio.sleep(10)

    monkeypatch.setattr(rerank, "EMBED_TIMEOUT_S", 0.01)
    hits = [("a", {"title": "Creep of 316"}), ("b", {"title": "other"})]

    ranked = asyncio.run(rerank.rank_hits(QUESTION, hits, hangs, {}))

    assert [r["source_id"] for r in ranked] == ["a", "b"]
    assert ranked[0]["embedding_rank"] is None
    assert "no response in 0 s" in caplog.text


def test_a_short_embedding_response_falls_back_to_bm25(caplog):
    async def short(texts):
        return [[1.0]]

    ranked = asyncio.run(rerank.rank_hits(QUESTION, [("a", {"title": "x"})], short, {}))

    assert ranked[0]["embedding_rank"] is None
    assert "got 1 vectors for 2 texts" in caplog.text


def test_ties_keep_the_order_found():
    hits = [("first", {"title": "same"}), ("second", {"title": "same"})]

    ranked = asyncio.run(rerank.rank_hits("unrelated words", hits, None, {}))

    assert [r["source_id"] for r in ranked] == ["first", "second"]


def test_no_hits_ranks_nothing():
    assert asyncio.run(rerank.rank_hits(QUESTION, [], None, {})) == []


def test_embeddings_are_cached_and_only_new_hits_embedded():
    calls = []
    embed = _embedder({}, calls)
    cache = {}
    first = [("a", {"title": "A"}), ("b", {"title": "B"})]

    asyncio.run(rerank.rank_hits(QUESTION, first, embed, cache))
    asyncio.run(rerank.rank_hits(QUESTION, first + [("c", {"title": "C"})], embed, cache))
    asyncio.run(rerank.rank_hits(QUESTION, first, embed, cache))

    assert len(calls) == 2  # the third call embeds nothing
    assert calls[0][0] == QUESTION and len(calls[0]) == 3
    assert calls[1] == ["C."]


def test_long_abstracts_are_truncated_before_embedding():
    calls = []
    hits = [("a", {"title": "T", "abstract": "x" * 10_000})]

    asyncio.run(rerank.rank_hits(QUESTION, hits, _embedder({}, calls), {}))

    assert max(len(t) for t in calls[0]) == rerank._EMBED_CHARS


# --- unread hits on the run context -----------------------------------------


def test_ranked_unread_hits_skip_read_and_undownloadable_hits():
    ctx = _ctx()
    ctx.search_hits = {
        "111": {"title": "Creep of 316 at 400 C", "origin": "osti"},
        "222": {"title": "Already analyzed", "origin": "osti"},
        "333": {"title": "Downloaded, not yet analyzed", "origin": "osti"},
        "10.1_x": {"title": "Paywalled creep of 316", "origin": "openalex", "oa_pdf_url": None},
        "10.1_y": {"title": "Open creep of 316 at 400 C", "origin": "openalex",
                   "oa_pdf_url": "https://arxiv.org/y"},
    }
    ctx.paper_analysis_results["222"] = {"answered": False}
    ctx.pdf_paths["333"] = "/tmp/333.pdf"

    ranked = asyncio.run(ctx.ranked_unread_hits())

    # A downloaded paper not yet analyzed is still a candidate.
    assert {sid for sid, _, _ in ranked} == {"111", "333", "10.1_y"}


# --- rank_candidates tool ---------------------------------------------------


def _tool(ctx):
    return next(t for t in build_rank_tools(ctx) if t.name == "rank_candidates")


def test_rank_candidates_lists_unread_hits_best_first():
    ctx = _ctx(_embedder({"400 c": [1.0, 0.0, 0.0]}))
    ctx.search_hits = {
        "111": {"title": "Zirconium oxidation", "description": "steam", "origin": "osti"},
        "222": {"title": "Creep of type 316 stainless steel at 400 C and 15 MPa",
                "description": "creep rate data " * 50, "origin": "osti"},
        "10.1_y": {"title": "Open paper", "abstract": "x", "origin": "openalex",
                   "oa_pdf_url": "https://arxiv.org/y", "year": 2020},
    }

    out = json.loads(asyncio.run(_tool(ctx).ainvoke({"max_results": 2})))

    assert out["question"] == QUESTION and out["ranking"] == "bm25+embedding"
    assert out["total_unread"] == 3 and len(out["candidates"]) == 2
    top = out["candidates"][0]
    assert top["rank"] == 1 and top["source_id"] == "222"
    assert top["downloadable_via"] == "osti_id" and len(top["abstract"]) == 300
    assert {"bm25_rank", "embedding_rank"} <= set(top)


def test_rank_candidates_says_how_to_download_an_open_access_hit():
    ctx = _ctx()
    ctx.search_hits = {
        "10.1_y": {"title": "Open", "origin": "openalex", "oa_pdf_url": "https://arxiv.org/y"},
    }

    (candidate,) = json.loads(asyncio.run(_tool(ctx).ainvoke({})))["candidates"]

    assert candidate["downloadable_via"] == "oa_pdf_url"
    assert candidate["oa_pdf_url"] == "https://arxiv.org/y"


def test_rank_candidates_without_embeddings_reports_bm25():
    ctx = _ctx()
    ctx.search_hits = {"111": {"title": "Creep", "origin": "osti"}}

    out = json.loads(asyncio.run(_tool(ctx).ainvoke({"max_results": 0})))

    assert out["ranking"] == "bm25" and len(out["candidates"]) == 1  # at least one


def test_rank_candidates_with_nothing_unread():
    out = json.loads(asyncio.run(_tool(_ctx()).ainvoke({})))

    assert out["candidates"] == [] and out["total_unread"] == 0


# --- the keep-going nudge uses the ranking ----------------------------------


def test_nudge_lists_unread_results_in_ranked_order():
    ctx = _ctx()
    ctx.search_hits = {
        "1": {"title": "Zirconium oxide in steam", "origin": "osti"},
        "2": {"title": "Creep of 316 stainless steel at 400 C and 15 MPa", "origin": "osti"},
    }

    nudge = asyncio.run(deep_runner.keep_going_nudge(ctx))

    assert "most relevant to the question first" in nudge
    assert nudge.index("- 2: Creep of 316") < nudge.index("- 1: Zirconium")
