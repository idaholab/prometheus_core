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

"""Knowledge-base tools for the deep-agent orchestrator.

``search_knowledge_base`` returns semantically-ranked facts plus any
near-duplicate cached answer from ``ctx.knowledge`` (an embedding-backed
:class:`~research_agent.knowledge.KnowledgeStore`), and ``store_facts`` persists
facts with per-fact embeddings. Both are no-ops when there is no knowledge store
(no Redis).
"""

from __future__ import annotations

import json
import logging
from typing import List

from langchain_core.tools import BaseTool, tool

from research_agent.tools.context import RunContext

logger = logging.getLogger(__name__)


def build_memory_tools(ctx: RunContext) -> List[BaseTool]:
    """Build the knowledge-base tools bound to one run's context."""

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search facts and cached answers stored from past research. ALWAYS call
        this first. Returns JSON {cached_answer, facts}: ``cached_answer`` is a
        prior answer to (nearly) this same question with its sources, or null;
        ``facts`` is a list of {content, source_id, title, url} ranked by
        relevance (empty if nothing relevant is stored). These are search and
        source-selection hints only; final evidence must be re-read and verified
        from the current run's parsed paper artifacts."""
        if ctx.knowledge is not None:
            facts = await ctx.knowledge.search_facts(query, k=8)
            cached = await ctx.knowledge.get_cached_answer(query)
            cached_out = None
            if isinstance(cached, dict) and cached.get("answer"):
                cached_out = {
                    "answer": cached.get("answer", ""),
                    "sources": cached.get("sources", []),
                }
            return json.dumps(
                {
                    "cached_answer": cached_out,
                    "facts": [
                        {
                            "content": f.get("content", ""),
                            "source_id": f.get("source_id", ""),
                            "title": f.get("title", ""),
                            "url": f.get("url", ""),
                        }
                        for f in facts
                    ],
                }
            )

        return json.dumps({"cached_answer": None, "facts": []})

    @tool
    async def store_facts(facts_json: str) -> str:
        """Store 3-10 discrete, reusable facts extracted from the papers you
        analyzed, so future questions can be answered from memory. Input is a
        JSON array of {content, topics, source_id, source_title, source_url}
        (source_title/source_url are optional - they're filled in from the search
        results when omitted). Returns JSON {stored: <count>}."""
        try:
            facts = json.loads(facts_json)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"stored": 0, "error": "facts_json was not valid JSON"})
        if not isinstance(facts, list):
            return json.dumps({"stored": 0, "error": "expected a JSON array of facts"})

        stored = 0
        rejected = 0
        verified_source_ids = {finding.source_id for finding in ctx.findings}
        for fact in facts:
            if not isinstance(fact, dict) or not fact.get("content"):
                continue
            # Accept either the new source_id or the legacy source_osti_id key.
            source_id = str(fact.get("source_id") or fact.get("source_osti_id") or "")
            if source_id not in verified_source_ids:
                rejected += 1
                continue
            hit = ctx.search_hits.get(source_id, {})
            title = fact.get("source_title") or hit.get("title", "")
            url = fact.get("source_url") or hit.get("url", "")

            if ctx.knowledge is None:
                continue
            fact_id = await ctx.knowledge.store_fact(
                content=fact["content"],
                source_id=source_id,
                source_title=title,
                source_url=url,
                topics=fact.get("topics", []),
                origin=hit.get("origin", "osti"),
                question=ctx.question,
            )
            if fact_id:
                stored += 1
        ctx.facts_stored += stored
        return json.dumps({"stored": stored, "rejected": rejected})

    return [search_knowledge_base, store_facts]
