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

"""``rank_candidates``: every unread search hit of the run, ranked against the
research question before the orchestrator picks what to download.

Ranking is BM25 + embedding similarity fused by RRF (``research_agent.rerank``).
It orders the candidates; it does not pick them. The orchestrator still reads
the abstracts and decides.
"""

from __future__ import annotations

import json
from typing import List

from langchain_core.tools import BaseTool, tool

from research_agent.tools import progress
from research_agent.tools.context import RunContext

# Characters of each abstract shown; the search tools already returned more.
_ABSTRACT_PREVIEW = 300
_MAX_CANDIDATES = 25


def build_rank_tools(ctx: RunContext) -> List[BaseTool]:
    """Build ``rank_candidates`` bound to one run's context."""

    @tool
    async def rank_candidates(max_results: int = 15) -> str:
        """Rank every search result not yet downloaded, from all searches so far,
        against the research question. Call this after searching and before
        choosing which papers to download, and again after more searches.

        Ranking combines keyword relevance (BM25: exact terms like alloy names,
        temperatures and stresses) and similarity of meaning (embeddings) by
        reciprocal rank fusion. It orders the candidates; it does not judge
        them. Read the abstracts and download only papers that could report
        the quantity asked, usually from the top of the list.

        Returns JSON {question, candidates: [{rank, source_id, title, year,
        origin, abstract, downloadable_via, bm25_rank, embedding_rank}],
        total_unread, ranking}. ``ranking`` is "bm25+embedding", or "bm25"
        when embeddings were unavailable. ``downloadable_via`` says how to call
        download_paper: "osti_id" (pass source_id) or "oa_pdf_url" (pass
        url=oa_pdf_url)."""
        ranked = await ctx.ranked_unread_hits()
        limit = max(1, min(max_results, _MAX_CANDIDATES))
        with_embeddings = any(r["embedding_rank"] is not None for _, _, r in ranked)
        candidates = []
        for position, (source_id, hit, r) in enumerate(ranked[:limit], start=1):
            abstract = hit.get("abstract") or hit.get("description") or ""
            candidates.append(
                {
                    "rank": position,
                    "source_id": source_id,
                    "title": hit.get("title", ""),
                    "year": hit.get("year"),
                    "origin": hit.get("origin") or "osti",
                    "abstract": abstract[:_ABSTRACT_PREVIEW],
                    "downloadable_via": "oa_pdf_url" if hit.get("oa_pdf_url") else "osti_id",
                    "oa_pdf_url": hit.get("oa_pdf_url"),
                    "bm25_rank": r["bm25_rank"],
                    "embedding_rank": r["embedding_rank"],
                }
            )
        ranking = "bm25+embedding" if with_embeddings else "bm25"
        progress.emit(
            f"Ranked {len(ranked)} unread result(s) against the question ({ranking})"
        )
        return json.dumps(
            {
                "question": ctx.question,
                "candidates": candidates,
                "total_unread": len(ranked),
                "ranking": ranking,
            }
        )

    return [rank_candidates]
