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

"""``read_top_candidates``: code, not the model, picks which papers to read.

Each call ranks every unread search hit against the question
(``RunContext.ranked_unread_hits``: BM25 + embedding, fused by RRF), then
downloads, parses and analyzes the top ``BATCH_SIZE`` in parallel. A paper
whose download or parse fails gives its slot to the next one in rank order.
The run reads at most ``max_papers_analyzed`` papers (6: two batches of 3).

The download, parse and analyze steps are the existing tools, called from
code, so their budget, allowlist and bookkeeping rules all still apply.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Dict, List, Optional

from research_agent.rerank import tokenize
from research_agent.tools import progress
from research_agent.tools.context import RunContext

logger = logging.getLogger(__name__)

BATCH_SIZE = 3
# Stop reading once this many papers gave an exact finding.
EXACT_FINDINGS_TO_STOP = 2

# Each step is one existing tool, called as ``await step(args) -> JSON str``.
Step = Callable[[dict], Awaitable[str]]


def shares_a_question_term(question: str, hit: dict) -> bool:
    """Whether the hit's title or abstract contains any word of the question.

    The ranking orders candidates but never says "none of these fit"; a hit
    with no word in common with the question (a BM25 score of 0) is skipped
    rather than read just for being next in line."""
    from research_agent.rerank import hit_text

    terms = set(tokenize(question))
    return bool(terms & set(tokenize(hit_text(hit))))


def stop_reason(ctx: RunContext) -> Optional[str]:
    """Why no further batch should be read, or None."""
    exact = {f.source_id for f in ctx.findings if f.match == "exact"}
    if len(exact) >= EXACT_FINDINGS_TO_STOP:
        return (
            f"{len(exact)} papers gave an exact finding; check that they agree "
            "before reading more"
        )
    return ctx.budget_reason()


async def _read_one(
    source_id: str,
    hit: dict,
    question: str,
    download: Step,
    parse: Step,
    analyze: Step,
) -> dict:
    """Download, parse and analyze one paper; a summary of what happened."""
    args = {"source_id": source_id}
    if hit.get("oa_pdf_url"):
        args["url"] = hit["oa_pdf_url"]
    downloaded = json.loads(await download(args))
    if not downloaded.get("ok"):
        return {"source_id": source_id, "read": False, "step": "download",
                "error": downloaded.get("error", "download failed")}
    parsed = json.loads(await parse({"source_id": source_id}))
    if parsed.get("ok") is False:
        return {"source_id": source_id, "read": False, "step": "parse",
                "error": parsed.get("error", "parse failed")}
    analyzed = json.loads(await analyze({"source_id": source_id, "question": question}))
    if analyzed.get("answered") is False:
        return {"source_id": source_id, "read": True, "answered": False,
                "reason": analyzed.get("reason", "")}
    return {"source_id": source_id, "read": True, "answered": True,
            "match": analyzed.get("match", "exact"), "answer": analyzed.get("answer", "")}


async def read_top_candidates(
    ctx: RunContext,
    download: Step,
    parse: Step,
    analyze: Step,
) -> Dict:
    """Read the next batch of top-ranked papers. See the module docstring."""
    reason = stop_reason(ctx)
    if reason:
        return {"read": [], "stop": True, "reason": reason}

    ranked = await ctx.ranked_unread_hits()
    queue = [(sid, hit) for sid, hit, _ in ranked if shares_a_question_term(ctx.question, hit)]
    rank_of = {sid: i for i, (sid, _) in enumerate(queue)}
    skipped = len(ranked) - len(queue)
    slots = min(BATCH_SIZE, ctx.config.max_papers_analyzed - ctx.papers_attempted)
    if not queue:
        return {
            "read": [],
            "stop": False,
            "reason": "no unread search result shares a word with the question",
            "instruction": "Search again with a reformulated query, then call this again.",
        }

    progress.emit(
        f"Reading the top {min(slots, len(queue))} of {len(queue)} ranked paper(s)",
        {"slots": slots, "candidates": len(queue)},
    )
    results: List[dict] = []
    in_flight: Dict[asyncio.Task, str] = {}
    # Papers of this batch read or being read. A failed download or parse frees
    # its place for the next one in rank order (and the parse tool gives back
    # its paper-budget slot), so a batch reads `slots` papers when it can.
    reading = 0

    def start_next() -> None:
        nonlocal reading
        while queue and reading < slots and ctx.budget_reason() is None:
            sid, hit = queue.pop(0)
            task = asyncio.create_task(_read_one(sid, hit, ctx.question, download, parse, analyze))
            in_flight[task] = sid
            reading += 1

    start_next()
    while in_flight:
        done, _ = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            sid = in_flight.pop(task)
            try:
                result = task.result()
            except Exception as e:  # one paper failing must not stop the batch
                logger.warning("Reading paper %s failed: %s", sid, e)
                result = {"source_id": sid, "read": False, "step": "error", "error": str(e)}
            results.append(result)
            if not result["read"]:
                reading -= 1
                start_next()

    after = stop_reason(ctx)
    # Papers finish in any order; report them in rank order.
    results.sort(key=lambda r: rank_of.get(r["source_id"], len(rank_of)))
    return {
        "read": results,
        "skipped_unrelated": skipped,
        "papers_read_this_batch": sum(1 for r in results if r["read"]),
        "paper_slots_used": ctx.papers_attempted,
        "paper_budget": ctx.config.max_papers_analyzed,
        "stop": after is not None,
        "reason": after or "budget left; another batch can be read",
    }
