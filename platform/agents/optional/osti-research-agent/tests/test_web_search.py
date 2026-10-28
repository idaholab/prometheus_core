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

"""Tests for web-search providers and get_web_provider selection.

Web search is additive and OFF by default: get_web_provider returns None unless
a provider is configured with its key/url.
"""

import asyncio

import httpx
import respx

from research_agent.core.config import AgentConfig
from research_agent.web_search import (
    SearxngProvider,
    TavilyProvider,
    get_web_provider,
)


def _config(**overrides):
    return AgentConfig(litellm_base_url="http://unused", **overrides)


# --- provider selection ---------------------------------------------------


def test_get_web_provider_default_is_none():
    assert get_web_provider(_config()) is None


def test_get_web_provider_tavily_requires_key():
    assert get_web_provider(_config(web_search_provider="tavily")) is None
    p = get_web_provider(_config(web_search_provider="tavily", tavily_api_key="k"))
    assert isinstance(p, TavilyProvider)


def test_get_web_provider_searxng_requires_url():
    assert get_web_provider(_config(web_search_provider="searxng")) is None
    p = get_web_provider(
        _config(web_search_provider="searxng", searxng_url="http://searx.local")
    )
    assert isinstance(p, SearxngProvider)


# --- Tavily ---------------------------------------------------------------


@respx.mock
def test_tavily_normalizes_results():
    route = respx.post("https://api.tavily.com/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Result A",
                        "url": "https://a.example",
                        "content": "snippet a",
                        "published_date": "2024-01-01",
                    }
                ]
            },
        )
    )
    hits = asyncio.run(TavilyProvider("secret").search("query", 5))
    assert hits[0] == {
        "title": "Result A",
        "url": "https://a.example",
        "snippet": "snippet a",
        "published": "2024-01-01",
        "origin": "tavily",
    }
    # api key is sent in the body
    import json

    assert json.loads(route.calls.last.request.content)["api_key"] == "secret"


# --- SearXNG --------------------------------------------------------------


@respx.mock
def test_searxng_normalizes_results_and_strips_trailing_slash():
    respx.get("http://searx.local/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Result B",
                        "url": "https://b.example",
                        "content": "snippet b",
                        "publishedDate": "2023-05-05",
                    }
                ]
            },
        )
    )
    provider = SearxngProvider("http://searx.local/")  # trailing slash
    hits = asyncio.run(provider.search("query", 5))
    assert hits[0]["title"] == "Result B"
    assert hits[0]["url"] == "https://b.example"
    assert hits[0]["origin"] == "searxng"
