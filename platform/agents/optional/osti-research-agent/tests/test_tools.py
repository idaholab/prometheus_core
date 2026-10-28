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

"""Verify that deep-agent tools can run over mocked lower-level modules without
a graph. Budget-enforcing tools must refuse by returning a string rather than
raising, because an exception would terminate the orchestrator loop.
"""

import asyncio
import json

import pytest

from research_agent import osti_client
from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.parsing import pipeline as parse_pipeline
from research_agent.parsing.artifacts import FigureArtifact, ParsedPaper, TableArtifact
from research_agent.tools import RunContext
from research_agent.tools.memory import build_memory_tools
from research_agent.tools.osti import build_osti_tools


async def _fake_complete(prompt, *, max_tokens, temperature=0):
    return "stub"


def _ctx(**overrides):
    config = AgentConfig(
        litellm_base_url="http://unused",
        total_budget_s=900,
        max_papers_analyzed=2,
        **overrides,
    )
    return RunContext(config=config, complete=_fake_complete)


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


# --- search_osti ----------------------------------------------------------


def test_search_osti_maps_hits_and_records_them(monkeypatch):
    def fake_search(query, max_results):
        assert max_results == 8
        return [
            {
                "osti_id": "123",
                "title": "Creep of Titanium",
                "description": "A" * 5000,
                "journal_name": "J. Nucl. Mater.",
                "url": "https://osti.gov/biblio/123",
            }
        ]

    monkeypatch.setattr(
        osti_client,
        "search_osti",
        fake_search,
    )
    ctx = _ctx()
    search = _tool(build_osti_tools(ctx), "search_osti")

    out = json.loads(asyncio.run(search.ainvoke({"query": "titanium creep"})))

    assert out[0]["osti_id"] == "123"
    assert out[0]["journal"] == "J. Nucl. Mater."
    assert len(out[0]["abstract"]) == 600  # truncated
    # recorded for later provenance
    assert ctx.search_hits["123"]["title"] == "Creep of Titanium"


def test_search_osti_omits_hits_already_returned_by_another_query(monkeypatch):
    monkeypatch.setattr(
        osti_client,
        "search_osti",
        lambda query, max_results: [
            {
                "osti_id": "123",
                "title": "Creep of Titanium",
                "description": "abstract",
            }
        ],
    )
    ctx = _ctx()
    search = _tool(build_osti_tools(ctx), "search_osti")

    first = json.loads(asyncio.run(search.ainvoke({"query": "titanium creep"})))
    second = json.loads(asyncio.run(search.ainvoke({"query": "titanium deformation"})))

    assert len(first) == 1
    assert second == []


def test_search_osti_deduplicates_and_caps_queries(monkeypatch):
    calls = []

    def fake_search(query, max_results):
        calls.append(query)
        return []

    monkeypatch.setattr(osti_client, "search_osti", fake_search)
    ctx = _ctx(max_osti_searches=3)
    search = _tool(build_osti_tools(ctx), "search_osti")

    asyncio.run(search.ainvoke({"query": "steel creep"}))
    duplicate = json.loads(asyncio.run(search.ainvoke({"query": "  STEEL   creep  "})))
    asyncio.run(search.ainvoke({"query": "steel creep 400 C"}))
    asyncio.run(search.ainvoke({"query": "316 steel deformation"}))
    exhausted = json.loads(
        asyncio.run(search.ainvoke({"query": "stainless creep rate"}))
    )

    assert calls == [
        "steel creep",
        "steel creep 400 C",
        "316 steel deformation",
    ]
    assert "duplicate OSTI query" in duplicate["error"]
    assert "search limit reached (3)" in exhausted["error"]
    # Running out of searches must not tell the agent to finish the run.
    assert "synthesize" not in exhausted["instruction"]
    assert "analyze the most promising unread" in exhausted["instruction"]


# --- download_paper -------------------------------------------------------


def test_download_paper_success_records_path(monkeypatch):
    calls = 0

    def fake_download(source_id, cache):
        nonlocal calls
        calls += 1
        return "/tmp/123.pdf"

    monkeypatch.setattr(osti_client, "download_paper", fake_download)
    ctx = _ctx()
    download = _tool(build_osti_tools(ctx), "download_paper")

    first = json.loads(asyncio.run(download.ainvoke({"source_id": "123"})))
    second = json.loads(asyncio.run(download.ainvoke({"source_id": "123"})))

    assert first == second
    assert first["ok"] is True
    assert first["pdf_path"] == "/tmp/123.pdf"
    assert ctx.pdf_paths["123"] == "/tmp/123.pdf"
    assert calls == 1


def test_download_paper_refuses_over_budget_without_raising():
    ctx = _ctx()
    ctx.papers_attempted = ctx.config.max_papers_analyzed  # budget hit
    download = _tool(build_osti_tools(ctx), "download_paper")

    out = json.loads(asyncio.run(download.ainvoke({"source_id": "999"})))

    assert out["ok"] is False
    assert "skipped" in out["error"]
    assert "999" not in ctx.pdf_paths


def test_download_paper_reports_missing_pdf(monkeypatch):
    calls = 0

    def missing(source_id, cache):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(osti_client, "download_paper", missing)
    ctx = _ctx()
    download = _tool(build_osti_tools(ctx), "download_paper")

    first = json.loads(asyncio.run(download.ainvoke({"source_id": "123"})))
    second = json.loads(asyncio.run(download.ainvoke({"source_id": "123"})))
    assert first == second
    assert first["ok"] is False
    assert "not available" in first["error"]
    assert "did not use up the paper budget" in first["instruction"]
    assert calls == 1


def test_download_paper_rejects_unreturned_direct_url(monkeypatch):
    called = False

    def fake_download(*args, **kwargs):
        nonlocal called
        called = True
        return "/tmp/paper.pdf"

    monkeypatch.setattr(osti_client, "download_pdf_from_url", fake_download)
    ctx = _ctx()
    ctx.search_hits["doi_1"] = {
        "origin": "openalex",
        "oa_pdf_url": "https://papers.example/original.pdf",
    }
    download = _tool(build_osti_tools(ctx), "download_paper")

    out = json.loads(
        asyncio.run(
            download.ainvoke(
                {
                    "source_id": "doi_1",
                    "url": "https://papers.example/invented.pdf",
                }
            )
        )
    )

    assert out["ok"] is False
    assert "rejected" in out["error"]
    assert called is False


def test_download_paper_writes_direct_url_into_run_workdir(monkeypatch, tmp_path):
    dests = []

    def fake_download(url, dest, *, max_bytes, cache=None, on_status=None):
        assert cache is ctx.pdf_cache
        dests.append(dest)
        return dest

    monkeypatch.setattr(osti_client, "download_pdf_from_url", fake_download)
    ctx = _ctx()
    ctx.run_workdir = tmp_path
    ctx.search_hits["10.1/x"] = {
        "origin": "openalex",
        "oa_pdf_url": "https://arxiv.org/pdf/x.pdf",
    }
    download = _tool(build_osti_tools(ctx), "download_paper")

    out = json.loads(asyncio.run(download.ainvoke({"source_id": "10.1/x"})))

    assert out["ok"] is True
    assert dests == [out["pdf_path"]]
    assert out["pdf_path"].startswith(str(tmp_path / "downloads"))


# --- parse_paper ----------------------------------------------------------


def _parsed():
    return ParsedPaper(
        source_id="123",
        title="Creep of Titanium",
        method="docling",
        page_count=7,
        tables=[
            TableArtifact(
                index=1,
                caption="Creep rates",
                md_path="tables/table_01.md",
                csv_path="tables/table_01.csv",
                n_rows=4,
                n_cols=3,
            )
        ],
        figures=[
            FigureArtifact(
                index=1,
                caption="Arrhenius plot",
                png_path="figures/fig_01.png",
                json_path="figures/fig_01.json",
                analyzed=True,
            )
        ],
        warnings=[],
    )


def test_parse_paper_summarizes_and_uses_agent_paths(monkeypatch):
    async def fake_pipeline(pdf_path, source_id, config, caches, *, emit, deadline):
        return _parsed()

    monkeypatch.setattr(parse_pipeline, "parse_paper_pipeline", fake_pipeline)
    ctx = _ctx()
    ctx.pdf_paths["123"] = "/tmp/123.pdf"
    parse = _tool(build_osti_tools(ctx), "parse_paper")

    out = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))

    assert out["ok"] is True
    assert out["dir"] == "/papers/123"
    assert out["tables"][0]["md_path"] == "/papers/123/tables/table_01.md"
    assert out["figures"][0]["json_path"] == "/papers/123/figures/fig_01.json"
    assert ctx.papers_attempted == 1


def test_parse_paper_returns_existing_summary_without_reparsing(monkeypatch):
    calls = 0

    async def fake_pipeline(pdf_path, source_id, config, caches, *, emit, deadline):
        nonlocal calls
        calls += 1
        return _parsed()

    monkeypatch.setattr(parse_pipeline, "parse_paper_pipeline", fake_pipeline)
    ctx = _ctx()
    ctx.pdf_paths["123"] = "/tmp/123.pdf"
    parse = _tool(build_osti_tools(ctx), "parse_paper")

    first = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))
    second = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))

    assert first == second
    assert calls == 1
    assert ctx.papers_attempted == 1


def test_parse_paper_requires_a_download_first():
    ctx = _ctx()
    parse = _tool(build_osti_tools(ctx), "parse_paper")
    out = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))
    assert out["ok"] is False
    assert "download_paper first" in out["error"]


def test_parse_paper_refuses_over_budget_without_running(monkeypatch):
    called = False

    async def fake_pipeline(*a, **k):
        nonlocal called
        called = True
        return _parsed()

    monkeypatch.setattr(parse_pipeline, "parse_paper_pipeline", fake_pipeline)
    ctx = _ctx()
    ctx.pdf_paths["123"] = "/tmp/123.pdf"
    ctx.papers_attempted = ctx.config.max_papers_analyzed
    parse = _tool(build_osti_tools(ctx), "parse_paper")

    out = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))
    assert out["ok"] is False and "skipped" in out["error"]
    assert called is False


def test_parse_paper_returns_error_string_when_pipeline_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("docling exploded")

    monkeypatch.setattr(parse_pipeline, "parse_paper_pipeline", boom)
    ctx = _ctx()
    ctx.pdf_paths["123"] = "/tmp/123.pdf"
    parse = _tool(build_osti_tools(ctx), "parse_paper")

    out = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))
    assert out["ok"] is False
    assert "parse failed" in out["error"]
    # A failed parse gives its paper slot back so the run can try another paper.
    assert ctx.papers_attempted == 0
    assert "did not use up the paper budget" in out["instruction"]


def test_failed_parse_is_not_retried(monkeypatch):
    calls = []

    async def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("docling exploded")

    monkeypatch.setattr(parse_pipeline, "parse_paper_pipeline", boom)
    ctx = _ctx()
    ctx.pdf_paths["123"] = "/tmp/123.pdf"
    parse = _tool(build_osti_tools(ctx), "parse_paper")

    asyncio.run(parse.ainvoke({"source_id": "123"}))
    again = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))

    assert len(calls) == 1  # remembered, so the slot refund can't loop
    assert again["ok"] is False and "parse failed" in again["error"]
    assert ctx.papers_attempted == 0


# --- knowledge base -------------------------------------------------------


class _FakeKnowledge:
    def __init__(self, facts=(), cached=None):
        self.facts, self.cached, self.stored = list(facts), cached, []

    async def search_facts(self, query, k=8):
        return self.facts

    async def get_cached_answer(self, question):
        return self.cached

    async def store_fact(self, **kwargs):
        self.stored.append(kwargs)
        return f"fact-{len(self.stored)}"


def test_search_knowledge_base_returns_facts_and_cached_answer():
    ctx = _ctx()
    ctx.knowledge = _FakeKnowledge(
        facts=[{"content": "Ti creeps above 800C", "source_id": "123", "title": "T", "url": "u"}],
        cached={"answer": "prior", "sources": [{"source": "OSTI #123"}]},
    )
    search = _tool(build_memory_tools(ctx), "search_knowledge_base")

    out = json.loads(asyncio.run(search.ainvoke({"query": "titanium"})))

    assert out["facts"][0] == {"content": "Ti creeps above 800C", "source_id": "123",
                               "title": "T", "url": "u"}
    assert out["cached_answer"] == {"answer": "prior", "sources": [{"source": "OSTI #123"}]}


def test_search_knowledge_base_without_a_store_is_empty():
    search = _tool(build_memory_tools(_ctx()), "search_knowledge_base")

    out = json.loads(asyncio.run(search.ainvoke({"query": "titanium"})))

    assert out == {"cached_answer": None, "facts": []}


def test_store_facts_counts_and_tracks():
    ctx = _ctx()
    ctx.knowledge = _FakeKnowledge()
    ctx.search_hits["123"] = {"title": "T", "url": "u"}
    ctx.findings.append(Finding(source_id="123", answer="verified"))
    store = _tool(build_memory_tools(ctx), "store_facts")

    facts = json.dumps(
        [
            {"content": "fact one", "topics": ["creep"], "source_osti_id": "123"},
            {"content": "fact two", "topics": [], "source_id": "123"},
        ]
    )
    out = json.loads(asyncio.run(store.ainvoke({"facts_json": facts})))

    assert out == {"stored": 2, "rejected": 0}
    assert ctx.facts_stored == 2
    assert ctx.knowledge.stored[0]["source_title"] == "T"


def test_store_facts_without_a_store_stores_nothing():
    ctx = _ctx()
    ctx.findings.append(Finding(source_id="123", answer="verified"))
    store = _tool(build_memory_tools(ctx), "store_facts")

    facts = json.dumps([{"content": "fact", "source_id": "123"}])
    out = json.loads(asyncio.run(store.ainvoke({"facts_json": facts})))

    assert out == {"stored": 0, "rejected": 0}


@pytest.mark.parametrize("facts_json, error", [
    ("not json", "not valid JSON"), ('{"a": 1}', "expected a JSON array"),
])
def test_store_facts_rejects_malformed_input(facts_json, error):
    store = _tool(build_memory_tools(_ctx()), "store_facts")

    out = json.loads(asyncio.run(store.ainvoke({"facts_json": facts_json})))

    assert out["stored"] == 0 and error in out["error"]


def test_store_facts_rejects_unverified_sources():
    ctx = _ctx()
    ctx.knowledge = _FakeKnowledge()
    store = _tool(build_memory_tools(ctx), "store_facts")

    facts = json.dumps(
        [{"content": "unverified", "topics": [], "source_osti_id": "123"}]
    )
    out = json.loads(asyncio.run(store.ainvoke({"facts_json": facts})))

    assert out == {"stored": 0, "rejected": 1}
    assert ctx.knowledge.stored == []


def test_store_facts_handles_bad_json_without_raising():
    ctx = _ctx()
    store = _tool(build_memory_tools(ctx), "store_facts")
    out = json.loads(asyncio.run(store.ainvoke({"facts_json": "not json"})))
    assert out["stored"] == 0
    assert "error" in out
