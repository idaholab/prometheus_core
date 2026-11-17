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

"""Run-scoped state shared by every tool in one deep-agent run.

The tools are thin ``@tool`` wrappers over the search, download, parsing, and
memory modules. They also enforce the hard budget ("trust the LLM, enforce at
tools") and accumulate the provenance/findings the runner needs to assemble a
:class:`~research_agent.core.events.FinalResult` - including the
``timeout_partial`` salvage path when the outer budget fires mid-run. All of
that lives here so a test can build a ``RunContext`` over mocked modules and
drive the tools directly.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, List, Optional, Tuple

import redis

from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.tools import progress
from research_agent.core.llm import CompleteFn
from research_agent.memory import ArtifactCache, PdfCache

if TYPE_CHECKING:
    from research_agent.knowledge import KnowledgeStore

# Stop launching new expensive work (downloads, parses) once this little time
# is left, so the graded answer + fact storage always get to run. Mirrors the pipeline
# engine's 60 s guard, with extra headroom for a paper still being analyzed.
BUDGET_FLOOR_S = 90.0

# Searches that fail with an API error (not zero hits) are given back to the
# search budget this many times per provider per run.
MAX_REFUNDED_SEARCH_FAILURES = 2


@dataclass
class RunContext:
    """Everything the tools need from the runtime, plus the mutable state they
    accumulate over a single research run."""

    config: AgentConfig
    complete: CompleteFn
    question: str = ""
    redis_client: Optional[redis.Redis] = None
    caches: Optional[ArtifactCache] = None
    pdf_cache: Optional[PdfCache] = None
    # Embedding-backed fact/answer store; None (no Redis) makes the memory
    # tools no-ops.
    knowledge: Optional["KnowledgeStore"] = None
    # Batch text embedder for ranking search hits (rank_candidates); None
    # ranks by BM25 alone.
    embed_batch: Optional[Callable[[List[str]], Awaitable[List[List[float]]]]] = None
    run_workdir: Path = field(default_factory=lambda: Path("/tmp/research_agent/run"))
    # time.monotonic() value after which no new expensive work should start.
    deadline: float = field(default_factory=lambda: time.monotonic() + 900.0)

    # --- accumulated over the run ---
    # source_id -> the search hit dict (title/url/abstract), for provenance.
    search_hits: Dict[str, dict] = field(default_factory=dict)
    # source_id -> local PDF path returned by download_paper.
    pdf_paths: Dict[str, str] = field(default_factory=dict)
    # source_id -> prior terminal download failure, so retries stay local.
    download_failures: Dict[str, str] = field(default_factory=dict)
    # Hosts that refused a download (401/403) this run; skipped from then on.
    refused_hosts: set[str] = field(default_factory=set)
    # source_id -> why its parse failed; failed parses don't use a paper slot,
    # so this is what stops the same PDF from being retried.
    parse_failures: Dict[str, str] = field(default_factory=dict)
    # Successful parse summaries, used to make parse_paper idempotent.
    parsed_papers: Dict[str, dict] = field(default_factory=dict)
    # Normalized queries already charged against each search provider's limit.
    search_queries: Dict[str, set[str]] = field(default_factory=dict)
    # Failed searches given back per provider (see release_search).
    search_failures_refunded: Dict[str, int] = field(default_factory=dict)
    # Findings captured as analyze_paper calls complete (the runner reads this
    # for the timeout_partial salvage path).
    findings: List[Finding] = field(default_factory=list)
    # Operational verifier failures are distinct from evidence-based rejection.
    # Finalization returns an error when every candidate was lost to these.
    verification_errors: List[str] = field(default_factory=list)
    # Terminal paper-analysis results make each parsed source idempotent within
    # one run. Per-source locks also coalesce concurrent duplicate tool calls.
    paper_analysis_results: Dict[str, dict] = field(default_factory=dict)
    paper_analysis_locks: Dict[str, asyncio.Lock] = field(
        default_factory=dict, repr=False
    )
    # Invalid structured requests have no usable parsed source, so cache them
    # separately without consuming analyzer or verifier calls.
    invalid_paper_analysis_results: Dict[str, dict] = field(default_factory=dict)
    # source_id -> {"by": "analyzer" | "verifier", "reason": ...} for papers
    # that were analyzed but produced no finding.
    unused_papers: Dict[str, dict] = field(default_factory=dict)
    # Code-checked statements from the abstracts of papers whose full text
    # could not be read (tools/evidence.py). Never findings.
    abstract_evidence: List[dict] = field(default_factory=list)
    # Code-checked estimates computed from cited values (tools/evidence.py).
    # Never findings.
    estimates: List[dict] = field(default_factory=list)
    # Embeddings computed while ranking search hits, by source_id, so a later
    # ranking only embeds new hits.
    hit_embeddings: Dict[str, List[float]] = field(default_factory=dict, repr=False)
    # Papers whose parse was attempted, counted before parsing so a PDF that
    # keeps failing to parse still uses up its slot. This is the paper budget;
    # FinalResult.papers_analyzed reports analyses instead.
    papers_attempted: int = 0
    # Discrete facts written to the knowledge base via store_facts (reported in
    # the FinalResult).
    facts_stored: int = 0
    # The orchestrator's answer once the grader accepted it (tools/answer.py),
    # and how many packages it was written from: findings verified after it
    # make it stale, and the answer falls back to the per-paper rendering.
    accepted_answer: Optional[str] = None
    accepted_answer_papers: int = 0
    # Answers the grader judged so far, accepted or not (at most
    # MAX_ANSWER_ATTEMPTS). Code-check refusals are counted apart, in
    # code_refusals (at most MAX_CODE_REFUSALS), so they leave the revision.
    answer_attempts: int = 0
    code_refusals: int = 0
    # Every submitted answer with what became of it, for the evaluation's
    # transcript: {answer, outcome, gaps}.
    answer_drafts: List[dict] = field(default_factory=list)

    def analysis_packages(self) -> List[dict]:
        """Each verified finding as the package the answer is written from,
        numbered the way the answer cites it (``Paper N``). ``findings`` only
        grows, so a package keeps its number for the whole run; the final
        answer's provenance is built in the same order."""
        packages = []
        for number, finding in enumerate(self.findings, 1):
            hit = self.search_hits.get(finding.source_id, {})
            packages.append(
                {
                    "paper": number,
                    "source_id": finding.source_id,
                    "title": " ".join(str(hit.get("title") or "").split()),
                    "match": finding.match,
                    "answer": finding.answer,
                    "evidence": finding.evidence,
                    "excerpt": finding.excerpt or "",
                }
            )
        return packages

    def unread_hits(self) -> List[Tuple[str, dict]]:
        """Search hits that could still be read, in the order found: not yet
        analyzed, not failed to download or parse, and downloadable (an OSTI
        id, or an allowed PDF link). A paper already downloaded or parsed but
        not analyzed still counts: reading it costs no new download."""
        unread = []
        for source_id, hit in self.search_hits.items():
            if source_id in self.paper_analysis_results:
                continue
            if source_id in self.download_failures or source_id in self.parse_failures:
                continue
            osti = source_id.isdigit() or str(hit.get("origin") or "osti") == "osti"
            if osti or hit.get("oa_pdf_url"):
                unread.append((source_id, hit))
        return unread

    async def ranked_unread_hits(self) -> List[Tuple[str, dict, dict]]:
        """``unread_hits`` ranked against the question, best first, as
        ``(source_id, hit, rank)`` where ``rank`` is ``rerank.rank_hits``'s
        entry (fused score and each signal's rank)."""
        from research_agent.rerank import rank_hits

        unread = self.unread_hits()
        ranks = await rank_hits(
            self.question, unread, self.embed_batch, self.hit_embeddings
        )
        hits = dict(unread)
        return [(r["source_id"], hits[r["source_id"]], r) for r in ranks]

    def openalex_key_kwargs(self) -> Dict[str, str]:
        """``{"api_key": ...}`` for the OpenAlex calls when a key is
        configured, else ``{}``, so keyless calls look as they did before."""
        key = self.config.openalex_api_key
        return {"api_key": key} if key else {}

    def can_download(self, url: str) -> bool:
        """``url`` is on the allowlist and its host hasn't refused us this run."""
        from research_agent.download_policy import host_of, url_allowed

        return url_allowed(url, self.config.download_allowed_domains) and (
            host_of(url) not in self.refused_hosts
        )

    def seconds_left(self) -> float:
        return self.deadline - time.monotonic()

    def budget_reason(self) -> Optional[str]:
        """Why a new expensive tool call should refuse, or None if it may run."""
        if self.papers_attempted >= self.config.max_papers_analyzed:
            return (
                f"paper budget reached ({self.papers_attempted}/"
                f"{self.config.max_papers_analyzed} papers)"
            )
        if self.seconds_left() < BUDGET_FLOOR_S:
            return f"time budget nearly exhausted ({self.seconds_left():.0f}s left)"
        return None

    def reserve_search(self, provider: str, query: str, limit: int) -> Optional[str]:
        """Reserve one unique provider query, or explain why it is refused."""
        normalized = " ".join(query.casefold().split())
        seen = self.search_queries.setdefault(provider, set())
        if normalized in seen:
            return f"duplicate {provider} query"
        if len(seen) >= limit:
            return f"{provider} search limit reached ({limit})"
        seen.add(normalized)
        return None

    def release_search(self, provider: str, query: str) -> bool:
        """Give back a reservation whose search failed (an API error, not zero
        hits), so the failure costs no budget and the query may be retried.

        At most ``MAX_REFUNDED_SEARCH_FAILURES`` per provider per run: past
        that, a source that keeps failing is charged as before, so a model
        cannot loop on a source that is down. Returns whether it was given
        back."""
        refunded = self.search_failures_refunded.get(provider, 0)
        if refunded >= MAX_REFUNDED_SEARCH_FAILURES:
            return False
        self.search_failures_refunded[provider] = refunded + 1
        normalized = " ".join(query.casefold().split())
        self.search_queries.get(provider, set()).discard(normalized)
        return True


def search_failed(ctx: RunContext, provider: str, query: str, error: str) -> dict:
    """The tool result for a search the API failed: give the reservation back
    when allowed, and say so, so the model neither reads it as zero hits nor
    counts it as a spent search."""
    refunded = ctx.release_search(provider, query)
    progress.emit(
        f"{provider} search failed ({error})"
        + ("; it did not use up a search" if refunded else ""),
        {"provider": provider, "refunded": refunded},
    )
    return {
        "results": [],
        "error": f"{provider} search failed: {error}",
        "search_failed": True,
        "search_refunded": refunded,
        "instruction": (
            "The search service failed; this is not a sign that no papers "
            "exist. This search did not use up the budget: retry it once, or "
            "use another search tool."
            if refunded
            else "The search service keeps failing and this search was "
            "counted. Use another search tool or the results you already have."
        ),
    }
