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

"""General web search behind a provider abstraction, so deployment can pick
what egress allows: Tavily (hosted, needs a key) or a self-hosted SearXNG. Web
search is additive and OFF by default - ``get_web_provider`` returns None unless
a provider is configured, and the ``search_web`` tool then reports that plainly
rather than failing.

httpx (async) throughout, so providers are exercised under respx in tests.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Protocol

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 30
_USER_AGENT = "osti-research-agent/1.0"


class WebSearchProvider(Protocol):
    name: str

    async def search(self, query: str, k: int) -> List[dict]:
        """Return a list of {title, url, snippet, published, origin} dicts."""
        ...


class TavilyProvider:
    """Tavily hosted search API (https://tavily.com). Needs an API key and
    egress to api.tavily.com."""

    name = "tavily"
    _URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def search(self, query: str, k: int) -> List[dict]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max(1, min(k, 20)),
        }
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await client.post(self._URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "published": r.get("published_date"),
                "origin": "tavily",
            }
            for r in data.get("results", [])[:k]
        ]


class SearxngProvider:
    """Self-hosted SearXNG instance (JSON output must be enabled on it)."""

    name = "searxng"

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    async def search(self, query: str, k: int) -> List[dict]:
        params = {"q": query, "format": "json"}
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = await client.get(f"{self._base_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "published": r.get("publishedDate"),
                "origin": "searxng",
            }
            for r in data.get("results", [])[:k]
        ]


def get_web_provider(config) -> Optional[WebSearchProvider]:
    """Build the configured web-search provider, or None if web search is
    disabled or misconfigured (missing key/url)."""
    choice = getattr(config, "web_search_provider", "none")
    if choice == "tavily" and config.tavily_api_key:
        return TavilyProvider(config.tavily_api_key)
    if choice == "searxng" and config.searxng_url:
        return SearxngProvider(config.searxng_url)
    if choice != "none":
        logger.warning(
            "web_search_provider=%s but its key/url is not set; web search disabled",
            choice,
        )
    return None
