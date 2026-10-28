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
"""Run-context budgets, progress writer failures, and tool edge cases."""

import asyncio
import json
import time

import langgraph.config
from test_search_tools import FakeKnowledge
from test_tools import _ctx, _parsed, _tool

from research_agent import osti_client, scholarly
from research_agent.core.events import Finding
from research_agent.parsing import pipeline as parse_pipeline
from research_agent.tools import progress
from research_agent.tools import search as search_tools
from research_agent.tools.memory import build_memory_tools
from research_agent.tools.osti import build_osti_tools
from research_agent.tools.search import build_search_tools


def test_budget_reason_reports_a_nearly_exhausted_time_budget():
    ctx = _ctx()
    assert ctx.budget_reason() is None

    ctx.deadline = time.monotonic() + 1.0

    assert ctx.budget_reason().startswith("time budget nearly exhausted")


def test_progress_survives_a_failing_stream_writer(monkeypatch, caplog):
    sent = []

    def broken_writer(payload):
        sent.append(payload)
        raise RuntimeError("stream closed")

    monkeypatch.setattr(langgraph.config, "get_stream_writer", lambda: broken_writer)
    caplog.set_level("DEBUG", logger=progress.__name__)

    progress.emit("Parsing OSTI #1", {"source_id": "1"})

    assert sent == [{"message": "Parsing OSTI #1", "detail": {"source_id": "1"}}]
    assert "writer failed for: Parsing OSTI #1" in caplog.text


def test_store_facts_skips_entries_without_content():
    ctx = _ctx()
    ctx.knowledge = FakeKnowledge()
    ctx.findings.append(Finding(source_id="123", answer="verified"))
    store = _tool(build_memory_tools(ctx), "store_facts")

    facts = json.dumps(["just a string", {"content": "", "source_id": "123"},
                        {"source_id": "123"}, {"content": "kept", "source_id": "123"}])
    out = json.loads(asyncio.run(store.ainvoke({"facts_json": facts})))

    assert out == {"stored": 1, "rejected": 0}
    assert [f["content"] for f in ctx.knowledge.stored] == ["kept"]


def test_osti_record_without_an_open_access_copy_fails_cleanly(monkeypatch, tmp_path):
    monkeypatch.setattr(osti_client, "download_paper", lambda sid, cache: None)
    lookups = []

    async def no_copy(doi, *, mailto=None):
        lookups.append(doi)
        return None

    monkeypatch.setattr(scholarly, "openalex_oa_pdf_url", no_copy)
    emitted = []
    monkeypatch.setattr(progress, "emit", lambda msg, detail=None: emitted.append(msg))
    ctx = _ctx()
    ctx.run_workdir = tmp_path
    ctx.search_hits["42"] = {"title": "T", "doi": "10.1/x"}
    download = _tool(build_osti_tools(ctx), "download_paper")

    out = json.loads(asyncio.run(download.ainvoke({"source_id": "42"})))

    assert out["ok"] is False and "not available" in out["error"]
    assert lookups == ["10.1/x"]
    assert "OSTI #42 has no full text and no open-access copy of DOI 10.1/x" in emitted


def test_parse_paper_forwards_pipeline_progress(monkeypatch):
    emitted = []
    monkeypatch.setattr(progress, "emit", lambda msg, detail=None: emitted.append((msg, detail)))

    async def fake_pipeline(pdf_path, source_id, config, caches, *, emit, deadline):
        await emit("Parsed tables", tables=1)
        await emit("Parsed figures")
        return _parsed()

    monkeypatch.setattr(parse_pipeline, "parse_paper_pipeline", fake_pipeline)
    ctx = _ctx()
    ctx.pdf_paths["123"] = "/tmp/123.pdf"
    parse = _tool(build_osti_tools(ctx), "parse_paper")

    out = json.loads(asyncio.run(parse.ainvoke({"source_id": "123"})))

    assert out["ok"] is True
    assert ("Parsed tables", {"tables": 1}) in emitted
    assert ("Parsed figures", None) in emitted


def test_search_web_skips_results_without_a_url(monkeypatch):
    class Provider:
        async def search(self, query, max_results):
            return [{"title": "no link"}, {"title": "page", "url": "https://a.example/p"}]

    monkeypatch.setattr(search_tools, "get_web_provider", lambda config: Provider())
    ctx = _ctx()
    web = _tool(build_search_tools(ctx), "search_web")

    out = json.loads(asyncio.run(web.ainvoke({"query": "titanium"})))

    assert [r["title"] for r in out["results"]] == ["page"]
    assert len(ctx.search_hits) == 1
