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
from typing import TYPE_CHECKING, Dict, List, Optional

import redis

from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.core.llm import CompleteFn
from research_agent.memory import ArtifactCache, PdfCache

if TYPE_CHECKING:
    from research_agent.knowledge import KnowledgeStore

# Stop launching new expensive work (downloads, parses) once this little time
# is left, so synthesis + fact storage always get to run. Mirrors the pipeline
# engine's 60 s guard, with extra headroom for a paper still being analyzed.
BUDGET_FLOOR_S = 90.0


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
    # Papers whose parse was attempted, counted before parsing so a PDF that
    # keeps failing to parse still uses up its slot. This is the paper budget;
    # FinalResult.papers_analyzed reports analyses instead.
    papers_attempted: int = 0
    # Discrete facts written to the knowledge base via store_facts (reported in
    # the FinalResult).
    facts_stored: int = 0

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
