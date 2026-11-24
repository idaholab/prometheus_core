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
"""read_top_candidates: code reads papers in rank order, 3 at a time, with a
failed download or parse replaced by the next paper, until 6 are read."""

import asyncio
import json

from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.tools import RunContext
from research_agent.tools import batch

QUESTION = "What is the creep rate of stainless steel 316 at 400 C and 15 MPa?"


def _ctx(n_hits=8, **config):
    ctx = RunContext(
        config=AgentConfig(litellm_base_url="http://unused", **config), complete=None
    )
    ctx.question = QUESTION
    # Ranked by BM25 alone (no embedder). Hit i repeats "creep" n_hits - i
    # times, so every hit shares a question term and earlier hits rank higher.
    for i in range(n_hits):
        title = " ".join(["creep"] * (n_hits - i) + [f"paper{i}"])
        ctx.search_hits[str(1000 + i)] = {"title": title, "origin": "osti"}
    return ctx


class Steps:
    """Fake download/parse/analyze with the real tools' budget bookkeeping:
    a parse counts a paper slot, a failed parse gives it back."""

    def __init__(self, ctx, *, fail_download=(), fail_parse=(), findings=None, delay=0.01):
        self.ctx, self.delay = ctx, delay
        self.fail_download, self.fail_parse = set(fail_download), set(fail_parse)
        self.findings = findings or {}
        self.order, self.active, self.peak = [], 0, 0

    async def download(self, args):
        sid = args["source_id"]
        self.order.append(sid)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(self.delay)
        self.active -= 1
        if sid in self.fail_download:
            self.ctx.download_failures[sid] = "PDF not available"
            return json.dumps({"ok": False, "error": "PDF not available"})
        self.ctx.pdf_paths[sid] = f"/tmp/{sid}.pdf"
        return json.dumps({"ok": True})

    async def parse(self, args):
        sid = args["source_id"]
        self.ctx.papers_attempted += 1
        await asyncio.sleep(self.delay)
        if sid in self.fail_parse:
            self.ctx.papers_attempted -= 1
            self.ctx.parse_failures[sid] = "parse failed"
            return json.dumps({"ok": False, "error": "parse failed"})
        return json.dumps({"source_id": sid})

    async def analyze(self, args):
        sid = args["source_id"]
        if sid in self.findings:
            match = self.findings[sid]
            self.ctx.findings.append(Finding(source_id=sid, answer=f"rate {sid}", match=match))
            result = {"source_id": sid, "answer": f"rate {sid}", "match": match}
        else:
            result = {"answered": False, "reason": f"{sid} has data at 600 C only"}
        self.ctx.paper_analysis_results[sid] = result
        return json.dumps(result)

    async def run(self):
        return await batch.read_top_candidates(self.ctx, self.download, self.parse, self.analyze)


def test_a_batch_reads_the_top_three_in_rank_order_in_parallel():
    ctx = _ctx()
    steps = Steps(ctx)

    out = asyncio.run(steps.run())

    assert steps.order == ["1000", "1001", "1002"]  # best ranked first
    assert steps.peak == 3  # all three at once
    assert [r["source_id"] for r in out["read"]] == ["1000", "1001", "1002"]
    assert all(r["read"] and r["answered"] is False for r in out["read"])
    assert out["reason"].startswith("budget left") and out["stop"] is False
    assert out["papers_read_this_batch"] == 3 and out["paper_slots_used"] == 3


def test_two_batches_read_six_papers_then_stop():
    ctx = _ctx()
    steps = Steps(ctx)

    first = asyncio.run(steps.run())
    second = asyncio.run(steps.run())
    third = asyncio.run(steps.run())

    assert first["stop"] is False and second["stop"] is True
    assert "paper budget reached (6/6 papers)" in second["reason"]
    assert steps.order == [str(1000 + i) for i in range(6)]  # no paper read twice
    assert third == {"read": [], "stop": True, "reason": second["reason"], "packages": []}


def test_a_failed_download_is_replaced_by_the_next_ranked_paper():
    ctx = _ctx()
    steps = Steps(ctx, fail_download={"1001"})

    out = asyncio.run(steps.run())

    assert steps.order == ["1000", "1001", "1002", "1003"]
    read = [r["source_id"] for r in out["read"] if r["read"]]
    assert sorted(read) == ["1000", "1002", "1003"]
    failed = next(r for r in out["read"] if not r["read"])
    assert failed == {"source_id": "1001", "read": False, "step": "download",
                      "error": "PDF not available"}
    assert ctx.papers_attempted == 3


def test_a_failed_parse_gives_its_slot_to_the_next_paper():
    ctx = _ctx()
    steps = Steps(ctx, fail_parse={"1000", "1002"})

    out = asyncio.run(steps.run())

    read = sorted(r["source_id"] for r in out["read"] if r["read"])
    assert read == ["1001", "1003", "1004"]
    assert {r["step"] for r in out["read"] if not r["read"]} == {"parse"}
    assert ctx.papers_attempted == 3


def test_failures_keep_refilling_until_the_candidates_run_out():
    ctx = _ctx(n_hits=4)
    steps = Steps(ctx, fail_download={"1000", "1001", "1002"})

    out = asyncio.run(steps.run())

    assert [r["source_id"] for r in out["read"] if r["read"]] == ["1003"]
    assert len(out["read"]) == 4 and out["stop"] is False


def test_two_exact_findings_stop_reading():
    ctx = _ctx()
    steps = Steps(ctx, findings={"1000": "exact", "1002": "exact"})

    out = asyncio.run(steps.run())
    again = asyncio.run(steps.run())

    assert out["stop"] is True and "2 papers gave an exact finding" in out["reason"]
    assert again["read"] == [] and again["stop"] is True
    answered = {r["source_id"]: r["match"] for r in out["read"] if r.get("answered")}
    assert answered == {"1000": "exact", "1002": "exact"}


def test_nearest_findings_do_not_stop_reading():
    ctx = _ctx()
    steps = Steps(ctx, findings={"1000": "nearest", "1001": "nearest", "1002": "exact"})

    out = asyncio.run(steps.run())

    assert out["stop"] is False  # one exact finding is not enough


def test_papers_sharing_no_word_with_the_question_are_skipped():
    ctx = _ctx(n_hits=2)
    ctx.search_hits["9"] = {"title": "Zirconium hydride reorientation", "origin": "osti"}
    steps = Steps(ctx)

    out = asyncio.run(steps.run())

    assert "9" not in steps.order and out["skipped_unrelated"] == 1


def test_no_related_paper_left_asks_for_another_search():
    ctx = _ctx(n_hits=0)
    ctx.search_hits["9"] = {"title": "Zirconium hydride reorientation", "origin": "osti"}

    out = asyncio.run(Steps(ctx).run())

    assert out["read"] == [] and out["stop"] is False
    assert "Search again" in out["instruction"]


def test_the_last_batch_reads_only_the_slots_left():
    ctx = _ctx(max_papers_analyzed=4)
    steps = Steps(ctx)

    asyncio.run(steps.run())
    out = asyncio.run(steps.run())

    assert len(out["read"]) == 1 and steps.order[-1] == "1003"
    assert out["stop"] is True


def test_an_open_access_hit_is_downloaded_from_its_pdf_link():
    ctx = _ctx(n_hits=0)
    ctx.search_hits["10.1_x"] = {"title": "creep of 316 at 400 C", "origin": "openalex",
                                 "oa_pdf_url": "https://arxiv.org/pdf/x"}
    seen = []
    steps = Steps(ctx)

    async def download(args):
        seen.append(args)
        return await steps.download(args)

    asyncio.run(batch.read_top_candidates(ctx, download, steps.parse, steps.analyze))

    assert seen == [{"source_id": "10.1_x", "url": "https://arxiv.org/pdf/x"}]


def test_a_paper_that_crashes_does_not_stop_the_batch(caplog):
    ctx = _ctx(n_hits=4)
    steps = Steps(ctx)

    async def analyze(args):
        if args["source_id"] == "1001":
            raise RuntimeError("analyzer exploded")
        return await steps.analyze(args)

    out = asyncio.run(batch.read_top_candidates(ctx, steps.download, steps.parse, analyze))

    crashed = next(r for r in out["read"] if r["source_id"] == "1001")
    assert crashed == {"source_id": "1001", "read": False, "step": "error",
                       "error": "analyzer exploded"}
    assert "Reading paper 1001 failed: analyzer exploded" in caplog.text
    assert sorted(r["source_id"] for r in out["read"] if r["read"]) == ["1000", "1002", "1003"]


def test_no_time_left_reads_nothing():
    ctx = _ctx()
    ctx.deadline = 0.0

    out = asyncio.run(Steps(ctx).run())

    assert out["read"] == [] and out["stop"] is True
    assert "time budget nearly exhausted" in out["reason"]


def test_without_a_topic_a_hit_sharing_a_question_word_is_kept():
    from research_agent.rerank import relevance_tier

    assert relevance_tier(QUESTION, None, {"title": "Creep of Inconel"}) is not None
    assert relevance_tier(QUESTION, None, {"title": "Zirconium hydrides"}) is None
    assert relevance_tier(QUESTION, None, {"title": "x", "description": "at 400 C"}) is not None
