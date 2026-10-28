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

"""ResearchRunner: the event-stream boundary between the deep-agent engine
and callers such as the A2A executor, the CLI and the evaluation.

Runs ``core.deep_runner.run_deep`` as a task, forwards its AgentEvents, and
enforces the overall time budget as an outer safety net: the tools stop new
work near the deadline first, and this cancels the run if something hangs,
salvaging a ``timeout_partial`` from the findings verified so far.
"""

import asyncio
import logging
import time
from typing import AsyncIterator, Dict, List, Optional

import redis

from research_agent.core.config import AgentConfig
from research_agent.core.events import AgentEvent, FinalResult, Finding
from research_agent.core.llm import CompleteFn, LiteLLMClient
from research_agent.memory import PdfCache, RedisCaches

logger = logging.getLogger(__name__)


class ResearchRunner:
    """Runs one research question and streams its progress as AgentEvents."""

    def __init__(
        self,
        config: AgentConfig,
        complete: Optional[CompleteFn] = None,
        redis_client: Optional[redis.Redis] = None,
        pdf_cache: Optional[PdfCache] = None,
    ):
        self.config = config
        route = config.model_route("orchestrator")
        self._complete = (
            complete
            or LiteLLMClient(
                route.base_url,
                route.api_key,
                route.model,
            ).complete
        )

        # Only build a RedisCaches when the caller didn't already hand us one
        # (the A2A executor reuses its own) and config actually has a Redis URL
        # (the CLI's --no-redis mode leaves this None -> the caches and the
        # knowledge base degrade to no-ops).
        caches = (
            RedisCaches(config.redis_url, config.redis_password)
            if config.redis_url
            else None
        )
        self._redis_client = (
            redis_client
            if redis_client is not None
            else (caches.client if caches else None)
        )
        self._pdf_cache = pdf_cache if pdf_cache is not None else caches

    async def run(self, question: str, *, run_id: str) -> AsyncIterator[AgentEvent]:
        async for event in self._run_deep(question, run_id=run_id):
            yield event

    async def _run_deep(
        self, question: str, *, run_id: str
    ) -> AsyncIterator[AgentEvent]:
        # Imported lazily so importing the runner (and research_agent's light
        # modules) doesn't pull in langchain/deepagents.
        from research_agent.core.deep_runner import run_deep

        q: asyncio.Queue = asyncio.Queue()
        findings: List[Finding] = []
        search_hits: Dict[str, dict] = {}
        deadline = time.monotonic() + max(self.config.total_budget_s - 30, 0)

        async def _job() -> None:
            try:
                async for event in run_deep(
                    question,
                    self.config,
                    run_id,
                    complete=self._complete,
                    redis_client=self._redis_client,
                    caches=self._pdf_cache,
                    pdf_cache=self._pdf_cache,
                    findings=findings,
                    search_hits=search_hits,
                    deadline=deadline,
                ):
                    await q.put(event)
            except Exception as e:
                logger.error(f"[{run_id}] Deep agent failed: {e}", exc_info=True)
                await q.put(
                    FinalResult(status="error", question=question, answer=str(e))
                )
            finally:
                await q.put(None)

        async for event in self._drain(
            q, _job, run_id, lambda: _deep_timeout_result(question, findings, search_hits)
        ):
            yield event

    async def _drain(
        self,
        q: asyncio.Queue,
        job,
        run_id: str,
        on_timeout,
    ) -> AsyncIterator[AgentEvent]:
        """Run ``job`` as a task, forwarding events off ``q`` until it signals
        completion with ``None``, and enforce the outer time budget - on
        exhaustion, cancel the task and yield ``on_timeout()`` (the salvaged
        partial)."""
        task = asyncio.create_task(job())
        deadline = time.monotonic() + max(self.config.total_budget_s - 30, 0)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning(f"[{run_id}] Budget exhausted, cancelling job")
                    task.cancel()
                    yield on_timeout()
                    return
                try:
                    event = await asyncio.wait_for(q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    logger.warning(f"[{run_id}] Budget exhausted, cancelling job")
                    task.cancel()
                    yield on_timeout()
                    return

                if event is None:
                    return
                yield event
        finally:
            if not task.done():
                task.cancel()


def _deep_timeout_result(
    question: str, findings: List[Finding], search_hits: Dict[str, dict]
) -> FinalResult:
    """Salvage a partial result for the deep engine from the Findings captured
    off the stream so far, with titles/urls from the search hits recorded
    during the run - the same provenance the completed path builds."""
    from research_agent import citations
    from research_agent.core.deep_runner import _findings_to_answers

    if findings:
        answer = (
            f"Research timed out after reaching the time budget. Found partial "
            f"information from {len(findings)} paper(s) before timing out."
        )
    else:
        answer = "Research timed out after reaching the time budget before finding any results."

    provenance, _ = citations.deduplicate_provenance_with_mapping(
        _findings_to_answers(findings, search_hits)
    )

    return FinalResult(
        status="timeout_partial",
        question=question,
        answer=answer,
        provenance=provenance,
        findings=list(findings),
        papers_analyzed=len(findings),
        searched_papers=dict(search_hits),
    )
