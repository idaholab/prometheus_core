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

"""Tests for OpenAlex and arXiv search over respx-mocked HTTP.

Covers OpenAlex abstract reconstruction and DOI-slug source ids, arXiv Atom
parsing and PDF-link extraction, and the merged/deduped ``search_scholarly``.
"""

import asyncio

import httpx
import respx

from research_agent import scholarly

_OPENALEX_PAYLOAD = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "title": "Creep of Titanium Alloys",
            "publication_year": 2019,
            "doi": "https://doi.org/10.1234/abc",
            "abstract_inverted_index": {
                "Titanium": [0],
                "creeps": [1],
                "at": [2],
                "high": [3],
                "temperature": [4],
            },
            "best_oa_location": {"pdf_url": "https://oa.example/abc.pdf"},
            "open_access": {"oa_url": "https://oa.example/abc"},
            "authorships": [
                {"author": {"display_name": "A. Researcher"}},
                {"author": {"display_name": "B. Scientist"}},
            ],
        }
    ]
}

_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Neutron Irradiation of Steel</title>
    <summary>We study irradiation effects on steel.</summary>
    <published>2021-01-01T00:00:00Z</published>
    <author><name>C. Author</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2101.00001v1" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""


@respx.mock
def test_openalex_hit_reconstructs_abstract_and_doi_slug():
    respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json=_OPENALEX_PAYLOAD)
    )
    hits = asyncio.run(scholarly.search_openalex("titanium creep", 5))
    assert len(hits) == 1
    h = hits[0]
    assert h["source_id"] == "10.1234_abc"
    assert h["doi"] == "10.1234_abc"
    assert h["abstract"] == "Titanium creeps at high temperature"
    assert h["oa_pdf_url"] == "https://oa.example/abc.pdf"
    assert h["origin"] == "openalex"
    assert h["authors"] == ["A. Researcher", "B. Scientist"]
    assert h["year"] == 2019


def test_openalex_does_not_treat_landing_page_as_pdf():
    work = {
        "id": "https://openalex.org/W2",
        "title": "Landing Page Only",
        "open_access": {"oa_url": "https://repository.example/item/2"},
    }

    hit = scholarly._openalex_hit(work)

    assert hit["oa_pdf_url"] is None


@respx.mock
def test_arxiv_entry_parsing_and_pdf_link():
    assert scholarly.ARXIV_URL == "https://export.arxiv.org/api/query"
    respx.get(scholarly.ARXIV_URL).mock(
        return_value=httpx.Response(200, text=_ARXIV_ATOM)
    )
    hits = asyncio.run(scholarly.search_arxiv("neutron steel", 5))
    assert len(hits) == 1
    h = hits[0]
    assert h["title"] == "Neutron Irradiation of Steel"
    assert h["oa_pdf_url"] == "http://arxiv.org/pdf/2101.00001v1"
    assert h["origin"] == "arxiv"
    assert h["authors"] == ["C. Author"]
    assert h["year"] == 2021
    assert h["source_id"].startswith("url_")


@respx.mock
def test_search_scholarly_merges_both_sources():
    respx.get(scholarly.OPENALEX_URL).mock(
        return_value=httpx.Response(200, json=_OPENALEX_PAYLOAD)
    )
    respx.get(scholarly.ARXIV_URL).mock(
        return_value=httpx.Response(200, text=_ARXIV_ATOM)
    )
    hits = asyncio.run(scholarly.search_scholarly("materials", 10))
    origins = {h["origin"] for h in hits}
    assert origins == {"openalex", "arxiv"}
    assert len(hits) == 2


@respx.mock
def test_openalex_failure_degrades_to_empty():
    respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(500))
    hits = asyncio.run(scholarly.search_openalex("x", 5))
    assert hits == []


@respx.mock
def test_arxiv_retries_once_after_a_429():
    route = respx.get(scholarly.ARXIV_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, text=_ARXIV_ATOM),
        ]
    )

    hits = asyncio.run(scholarly.search_arxiv("neutron steel", 5))

    assert route.call_count == 2 and len(hits) == 1


@respx.mock
def test_arxiv_gives_up_after_a_second_429(caplog):
    respx.get(scholarly.ARXIV_URL).mock(return_value=httpx.Response(429))

    with caplog.at_level("WARNING", logger="research_agent.scholarly"):
        hits = asyncio.run(scholarly.search_arxiv("neutron steel", 5))

    assert hits == []
    assert "429" in caplog.records[-1].getMessage()


@respx.mock
def test_arxiv_requests_are_spaced(monkeypatch):
    monkeypatch.setattr(scholarly, "ARXIV_MIN_INTERVAL_S", 0.3)
    respx.get(scholarly.ARXIV_URL).mock(return_value=httpx.Response(200, text=_ARXIV_ATOM))
    import time

    async def two_at_once():
        start = time.monotonic()
        await asyncio.gather(
            scholarly.search_arxiv("a", 1), scholarly.search_arxiv("b", 1)
        )
        return time.monotonic() - start

    assert asyncio.run(two_at_once()) >= 0.3


@respx.mock
def test_empty_error_messages_name_the_error_type(caplog):
    respx.get(scholarly.ARXIV_URL).mock(side_effect=httpx.ReadTimeout(""))

    with caplog.at_level("WARNING", logger="research_agent.scholarly"):
        asyncio.run(scholarly.search_arxiv("neutron steel", 5))

    assert caplog.records[-1].getMessage() == "arXiv search failed: ReadTimeout"


@respx.mock
def test_arxiv_can_be_turned_off():
    respx.get(scholarly.OPENALEX_URL).mock(return_value=httpx.Response(200, json={"results": []}))
    arxiv = respx.get(scholarly.ARXIV_URL).mock(return_value=httpx.Response(200, text=_ARXIV_ATOM))

    hits = asyncio.run(scholarly.search_scholarly("materials", 10, arxiv=False))

    assert hits == [] and arxiv.call_count == 0


def test_scholarly_arxiv_setting(monkeypatch):
    from research_agent.core.config import AgentConfig

    monkeypatch.setenv("SCHOLARLY_ARXIV", "false")
    assert AgentConfig.from_env().scholarly_arxiv is False
    monkeypatch.delenv("SCHOLARLY_ARXIV")
    assert AgentConfig.from_env().scholarly_arxiv is True
