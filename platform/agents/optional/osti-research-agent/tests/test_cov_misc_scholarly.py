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
"""OpenAlex/arXiv edge cases: empty DOIs, mailto, failed lookups, merge caps."""

import asyncio

import httpx
import respx

from research_agent import scholarly


def test_a_doi_that_is_only_a_prefix_has_no_slug():
    assert scholarly._doi_slug("https://doi.org/") is None
    assert scholarly._doi_slug("doi:/") is None
    # With no slug the source id falls back to a hash of the URL.
    assert scholarly._source_id("https://doi.org/", "https://x.example").startswith("url_")


@respx.mock
def test_openalex_search_sends_mailto():
    route = respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    hits = asyncio.run(scholarly.search_openalex("creep", 5, mailto="me@example.org"))

    assert hits == []
    assert route.calls.last.request.url.params["mailto"] == "me@example.org"


@respx.mock
def test_openalex_doi_lookup_failure_returns_none(caplog):
    respx.get(f"{scholarly.OPENALEX_URL}/doi:10.1/boom").mock(
        return_value=httpx.Response(500)
    )

    assert asyncio.run(scholarly.openalex_oa_pdf_url("doi:10.1/boom")) is None
    assert "OpenAlex DOI lookup failed for 10.1/boom" in caplog.text


@respx.mock
def test_openalex_doi_lookup_without_any_pdf_returns_none():
    respx.get(f"{scholarly.OPENALEX_URL}/doi:10.1/nopdf").mock(
        return_value=httpx.Response(
            200,
            json={"best_oa_location": None, "oa_locations": [None, {"pdf_url": ""}]},
        )
    )

    assert asyncio.run(scholarly.openalex_oa_pdf_url("10.1/nopdf")) is None


def _fake_sources(monkeypatch, openalex, arxiv):
    async def fake_openalex(query, k, *, mailto=None):
        return openalex

    async def fake_arxiv(query, k):
        return arxiv

    monkeypatch.setattr(scholarly, "search_openalex", fake_openalex)
    monkeypatch.setattr(scholarly, "search_arxiv", fake_arxiv)


def test_search_scholarly_drops_untitled_and_duplicate_hits(monkeypatch):
    _fake_sources(
        monkeypatch,
        [{"title": "Creep", "doi": "10.1_a"}, {"title": "", "doi": "10.1_b"}],
        [{"title": "creep", "doi": "10.1_a"}, {"title": "Swelling"}],
    )

    out = asyncio.run(scholarly.search_scholarly("creep", 10))

    assert [h["title"] for h in out] == ["Creep", "Swelling"]


def test_search_scholarly_stops_at_k(monkeypatch):
    _fake_sources(
        monkeypatch,
        [{"title": f"Paper {i}", "doi": f"10.1_{i}"} for i in range(4)],
        [{"title": "Preprint"}],
    )

    out = asyncio.run(scholarly.search_scholarly("creep", 2))

    assert [h["title"] for h in out] == ["Paper 0", "Paper 1"]
