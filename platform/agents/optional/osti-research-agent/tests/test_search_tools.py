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

"""Tests for scholarly/web search tools and the knowledge-store-backed memory
tools, using mocked providers and a fake store without a graph, Redis, or
network access.
"""

import asyncio
import json

from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.tools import RunContext
from research_agent.tools import search as search_tools
from research_agent.tools.memory import build_memory_tools
from research_agent.tools.search import build_search_tools


async def _fake_complete(prompt, *, max_tokens, temperature=0):
    return "stub"


def _ctx(**overrides):
    config = AgentConfig(litellm_base_url="http://unused", **overrides)
    return RunContext(config=config, complete=_fake_complete)


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


# --- search_scholarly -----------------------------------------------------


def test_search_scholarly_records_hits_with_oa_pdf(monkeypatch):
    async def fake_scholarly(query, k, *, mailto=None, arxiv=True):
        assert k == 6
        return [
            {
                "source_id": "10.1234_abc",
                "title": "Creep of Titanium",
                "authors": ["A. Researcher"],
                "year": 2019,
                "abstract": "x" * 5000,
                "doi": "10.1234_abc",
                "url": "https://doi.org/10.1234/abc",
                "oa_pdf_url": "https://arxiv.org/pdf/abc.pdf",
                "origin": "openalex",
            }
        ]

    monkeypatch.setattr(search_tools.scholarly, "search_scholarly", fake_scholarly)
    ctx = _ctx()
    scholarly = _tool(build_search_tools(ctx), "search_scholarly")

    out = json.loads(asyncio.run(scholarly.ainvoke({"query": "titanium creep"})))

    assert out[0]["source_id"] == "10.1234_abc"
    assert len(out[0]["abstract"]) == 600  # truncated
    assert out[0]["oa_pdf_url"] == "https://arxiv.org/pdf/abc.pdf"
    # recorded so download_paper can fetch the open-access PDF later
    hit = ctx.search_hits["10.1234_abc"]
    assert hit["oa_pdf_url"] == "https://arxiv.org/pdf/abc.pdf"
    assert hit["origin"] == "openalex"


def test_search_scholarly_omits_hits_already_returned_by_another_query(monkeypatch):
    async def fake_scholarly(query, k, *, mailto=None, arxiv=True):
        return [
            {
                "source_id": "10.1234_abc",
                "title": "Creep of Titanium",
                "authors": [],
                "abstract": "abstract",
                "url": "https://doi.org/10.1234/abc",
                "origin": "openalex",
            }
        ]

    monkeypatch.setattr(search_tools.scholarly, "search_scholarly", fake_scholarly)
    ctx = _ctx()
    scholarly = _tool(build_search_tools(ctx), "search_scholarly")

    first = json.loads(asyncio.run(scholarly.ainvoke({"query": "titanium creep"})))
    second = json.loads(
        asyncio.run(scholarly.ainvoke({"query": "titanium deformation"}))
    )

    assert len(first) == 1
    assert second == []


def test_search_scholarly_deduplicates_and_caps_queries(monkeypatch):
    calls = []

    async def fake_scholarly(query, k, *, mailto=None, arxiv=True):
        calls.append(query)
        return []

    monkeypatch.setattr(search_tools.scholarly, "search_scholarly", fake_scholarly)
    ctx = _ctx(max_scholarly_searches=2)
    scholarly = _tool(build_search_tools(ctx), "search_scholarly")

    asyncio.run(scholarly.ainvoke({"query": "steel creep"}))
    duplicate = json.loads(asyncio.run(scholarly.ainvoke({"query": " STEEL  creep "})))
    asyncio.run(scholarly.ainvoke({"query": "steel deformation"}))
    exhausted = json.loads(asyncio.run(scholarly.ainvoke({"query": "316 creep"})))

    assert calls == ["steel creep", "steel deformation"]
    assert "duplicate scholarly query" in duplicate["error"]
    assert "search limit reached (2)" in exhausted["error"]
    # Running out of searches must not tell the agent to finish the run.
    assert "synthesize" not in exhausted["instruction"]
    assert "analyze the most promising unread" in exhausted["instruction"]


# --- search_web -----------------------------------------------------------


def test_search_web_reports_unavailable_when_not_configured(monkeypatch):
    monkeypatch.setattr(search_tools, "get_web_provider", lambda config: None)
    ctx = _ctx()
    web = _tool(build_search_tools(ctx), "search_web")

    out = json.loads(asyncio.run(web.ainvoke({"query": "anything"})))
    assert out["available"] is False
    assert out["results"] == []


def test_search_web_records_hits_when_configured(monkeypatch):
    class FakeProvider:
        async def search(self, query, max_results):
            return [
                {
                    "title": "A page",
                    "url": "https://a.example/doc",
                    "snippet": "about titanium",
                    "published": "2024-01-01",
                    "origin": "tavily",
                }
            ]

    monkeypatch.setattr(search_tools, "get_web_provider", lambda config: FakeProvider())
    ctx = _ctx()
    web = _tool(build_search_tools(ctx), "search_web")

    out = json.loads(asyncio.run(web.ainvoke({"query": "titanium"})))
    assert out["available"] is True
    assert out["results"][0]["url"] == "https://a.example/doc"
    source_id = out["results"][0]["source_id"]
    assert source_id.startswith("url_")
    assert ctx.search_hits[source_id]["url"] == "https://a.example/doc"


def test_search_web_survives_provider_error(monkeypatch):
    class BoomProvider:
        async def search(self, query, max_results):
            raise RuntimeError("upstream 503")

    monkeypatch.setattr(search_tools, "get_web_provider", lambda config: BoomProvider())
    ctx = _ctx()
    web = _tool(build_search_tools(ctx), "search_web")

    out = json.loads(asyncio.run(web.ainvoke({"query": "titanium"})))
    assert out["available"] is True
    assert out["results"] == []
    assert "error" in out


# --- memory tools over a knowledge store ----------------------------------


class FakeKnowledge:
    """Records store_fact calls; returns canned search/cache results."""

    def __init__(self, facts=None, cached=None):
        self._facts = facts or []
        self._cached = cached
        self.stored = []

    async def search_facts(self, query, k=8):
        return self._facts

    async def get_cached_answer(self, question):
        return self._cached

    async def store_fact(self, **kwargs):
        self.stored.append(kwargs)
        return f"fact-{len(self.stored)}"

    async def cache_answer(self, question, answer, sources):
        return None


def test_search_knowledge_base_structured_output_with_knowledge():
    ctx = _ctx()
    ctx.knowledge = FakeKnowledge(
        facts=[
            {
                "content": "Ti creeps above 800C",
                "source_id": "10.1234_abc",
                "title": "Creep paper",
                "url": "https://doi.org/10.1234/abc",
            }
        ],
        cached={"answer": "prior answer", "sources": [{"source": "OSTI #1"}]},
    )
    search = _tool(build_memory_tools(ctx), "search_knowledge_base")

    out = json.loads(asyncio.run(search.ainvoke({"query": "titanium creep"})))
    assert out["cached_answer"]["answer"] == "prior answer"
    assert out["facts"][0]["source_id"] == "10.1234_abc"
    assert out["facts"][0]["title"] == "Creep paper"


def test_store_facts_via_knowledge_resolves_title_url_from_search_hits():
    ctx = _ctx()
    ctx.knowledge = FakeKnowledge()
    ctx.question = "how does titanium creep?"
    ctx.search_hits["10.1234_abc"] = {
        "title": "Creep paper",
        "url": "https://doi.org/10.1234/abc",
        "origin": "openalex",
    }
    ctx.findings.append(
        Finding(source_id="10.1234_abc", answer="Verified creep finding")
    )
    store = _tool(build_memory_tools(ctx), "store_facts")

    facts = json.dumps(
        [
            {
                "content": "Ti creeps above 800C",
                "topics": ["creep"],
                "source_id": "10.1234_abc",
            }
        ]
    )
    out = json.loads(asyncio.run(store.ainvoke({"facts_json": facts})))

    assert out["stored"] == 1
    assert ctx.facts_stored == 1
    call = ctx.knowledge.stored[0]
    assert call["source_id"] == "10.1234_abc"
    assert call["source_title"] == "Creep paper"  # resolved from search_hits
    assert call["source_url"] == "https://doi.org/10.1234/abc"
    assert call["origin"] == "openalex"
    assert call["question"] == "how does titanium creep?"
