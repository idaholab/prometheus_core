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

"""Non-OSTI search tools for the deep-agent orchestrator.

``search_scholarly`` (OpenAlex + arXiv) is keyless and always available - the
fallback when OSTI is thin or the topic is outside DOE scope. ``search_web`` is
additive and OFF by default: it reports plainly that it's not configured rather
than failing when no provider is set (see ``web_search.get_web_provider``).

Both record every hit into ``ctx.search_hits[source_id]`` (title/url and, when
known, an open-access ``oa_pdf_url``) so provenance/linkify work unchanged and
``download_paper`` can fetch the direct URL later.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import List

from langchain_core.tools import BaseTool, tool

from research_agent import scholarly
from research_agent.tools import progress
from research_agent.tools.context import RunContext
from research_agent.web_search import get_web_provider

logger = logging.getLogger(__name__)

_ABSTRACT_TRUNCATE = 600
_MAX_SCHOLARLY_RESULTS = 6


def _web_source_id(url: str) -> str:
    return "url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def build_search_tools(ctx: RunContext) -> List[BaseTool]:
    """Build the web + scholarly search tools bound to one run's context."""

    @tool
    async def search_scholarly(query: str, max_results: int = 10) -> str:
        """Search the open scientific literature via OpenAlex (comprehensive
        index) and arXiv (preprints). Use when OSTI has few relevant hits or the
        topic is outside DOE/nuclear scope. Returns a JSON list of {source_id,
        title, authors, year, abstract, doi, url, oa_pdf_url, origin};
        ``oa_pdf_url`` is present only when an open-access PDF exists on a host
        the agent may download from - pass it to download_paper(source_id,
        url=...) to read the full text. A result without one cannot be read."""
        reason = ctx.reserve_search(
            "scholarly",
            query,
            ctx.config.max_scholarly_searches,
        )
        if reason:
            exhausted = "limit reached" in reason
            return json.dumps(
                {
                    "results": [],
                    "error": f"skipped: {reason}",
                    "search_budget_exhausted": exhausted,
                    "instruction": (
                        "This search tool is used up for this run. Do not call it "
                        "again: download and analyze the most promising unread "
                        "results you already have, or use another search tool. "
                        "Emit the final JSON only when no promising result is "
                        "left or the paper or time budget is reached."
                        if exhausted
                        else "Use the earlier results instead of repeating this query."
                    ),
                }
            )

        progress.emit(f"Searching OpenAlex/arXiv for: {query}")
        hits = await scholarly.search_scholarly(
            query,
            min(max_results, _MAX_SCHOLARLY_RESULTS),
            mailto=ctx.config.openalex_mailto,
            arxiv=ctx.config.scholarly_arxiv,
        )
        out = []
        for h in hits:
            source_id = str(h.get("source_id", ""))
            if not source_id or source_id in ctx.search_hits:
                continue
            # Only offer a PDF the agent is allowed to download: a link on a
            # host that refuses scripted downloads just wastes a turn.
            oa_pdf_url = h.get("oa_pdf_url")
            if oa_pdf_url and not ctx.can_download(oa_pdf_url):
                oa_pdf_url = None
            ctx.search_hits[source_id] = {
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "oa_pdf_url": oa_pdf_url,
                "origin": h.get("origin", "openalex"),
                "abstract": h.get("abstract") or "",
                "year": h.get("year"),
            }
            out.append(
                {
                    "source_id": source_id,
                    "title": h.get("title", ""),
                    "authors": h.get("authors", []),
                    "year": h.get("year"),
                    "abstract": (h.get("abstract") or "")[:_ABSTRACT_TRUNCATE],
                    "doi": h.get("doi"),
                    "url": h.get("url", ""),
                    "oa_pdf_url": oa_pdf_url,
                    "origin": h.get("origin", "openalex"),
                }
            )
        progress.emit(f"Found {len(out)} scholarly results")
        return json.dumps(out)

    @tool
    async def search_web(query: str, max_results: int = 8) -> str:
        """General web search. Prefer for context, recent work, or finding an
        open-access PDF location when OSTI/scholarly search is thin. Returns JSON
        {available, results:[{source_id, title, url, snippet, published}]}; if web
        search is not configured, ``available`` is false and you should rely on
        search_osti/search_scholarly instead. Only download a result whose
        ``downloadable`` is true, and never invent a PDF URL."""
        provider = get_web_provider(ctx.config)
        if provider is None:
            return json.dumps(
                {
                    "available": False,
                    "reason": "web search is not configured for this deployment",
                    "results": [],
                }
            )
        progress.emit(f"Searching the web for: {query}")
        try:
            hits = await provider.search(query, max_results)
        except Exception as e:  # keep the tool contract: return a string
            logger.warning("web search failed: %s", e)
            return json.dumps({"available": True, "error": str(e), "results": []})
        out = []
        for h in hits:
            url = h.get("url", "")
            if not url:
                continue
            source_id = _web_source_id(url)
            downloadable = ctx.can_download(url)
            ctx.search_hits[source_id] = {
                "title": h.get("title", ""),
                "url": url,
                "origin": h.get("origin", "web"),
                "abstract": h.get("snippet") or "",
                "year": h.get("published"),
            }
            out.append(
                {
                    "source_id": source_id,
                    "title": h.get("title", ""),
                    "url": url,
                    "snippet": h.get("snippet", ""),
                    "published": h.get("published"),
                    "downloadable": downloadable,
                }
            )
        progress.emit(f"Found {len(out)} web results")
        return json.dumps({"available": True, "results": out})

    return [search_scholarly, search_web]
