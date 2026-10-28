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

"""OSTI tools for the deep-agent orchestrator: search, download, parse.

Thin ``@tool`` wrappers over ``osti_client`` and the structured parse ladder.
Returns are compact JSON strings - large content (paper.md, tables, figures)
lands on the filesystem backend under ``/papers/{id}/`` and is read there by
the analyzer/verifier, never echoed into the transcript.

``download_paper`` and ``parse_paper`` enforce the hard budget: once the paper
limit is hit or the deadline is within ``BUDGET_FLOOR_S``, they return an
explanatory string instead of doing the work (they never raise).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List, Optional

from langchain_core.tools import BaseTool, tool

from research_agent import download_policy, osti_client, scholarly
from research_agent.parsing import pipeline as parse_pipeline
from research_agent.parsing.artifacts import ParsedPaper, _safe_source_id
from research_agent.tools import progress
from research_agent.tools.context import RunContext

logger = logging.getLogger(__name__)

_ABSTRACT_TRUNCATE = 600
_MAX_OSTI_RESULTS = 8


def _agent_path(safe_id: str, relpath: str) -> str:
    """The path the subagent sees for an artifact: the on-disk paper dir is
    ``run_workdir/papers/{safe_id}/{relpath}`` and the ``/papers/`` filesystem
    route strips its prefix, so the virtual path is ``/papers/{safe_id}/...``."""
    return f"/papers/{safe_id}/{relpath}".rstrip("/")


def _parse_summary(parsed: ParsedPaper, safe_id: str) -> dict:
    return {
        "ok": True,
        "source_id": parsed.source_id,
        "dir": f"/papers/{safe_id}",
        "method": parsed.method,
        "page_count": parsed.page_count,
        "title": parsed.title,
        "tables": [
            {
                "index": t.index,
                "caption": t.caption,
                "n_rows": t.n_rows,
                "n_cols": t.n_cols,
                "md_path": _agent_path(safe_id, t.md_path),
                "csv_path": _agent_path(safe_id, t.csv_path),
            }
            for t in parsed.tables
        ],
        "figures": [
            {
                "index": f.index,
                "caption": f.caption,
                "analyzed": f.analyzed,
                "png_path": _agent_path(safe_id, f.png_path),
                "json_path": _agent_path(safe_id, f.json_path) if f.json_path else None,
            }
            for f in parsed.figures
        ],
        "warnings": parsed.warnings,
    }


async def _download_url(ctx: RunContext, source_id: str, url: str) -> Optional[str]:
    # Inside the run workdir so concurrent runs never share a file and the
    # download is removed with the rest of the run.
    downloads = ctx.run_workdir / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    dest = str(downloads / f"{_safe_source_id(source_id)}.pdf")
    return await asyncio.to_thread(
        osti_client.download_pdf_from_url,
        url,
        dest,
        max_bytes=ctx.config.max_pdf_mb * 1024 * 1024,
        cache=ctx.pdf_cache,
        on_status=lambda status: _note_refusal(ctx, url, status),
    )


async def _open_access_copy(ctx: RunContext, source_id: str, doi: str) -> Optional[str]:
    """OSTI has a record but no full text: try the open-access copy OpenAlex
    lists for the record's DOI, if its host is on the download allowlist."""
    url = await scholarly.openalex_oa_pdf_url(doi, mailto=ctx.config.openalex_mailto)
    if not url:
        progress.emit(
            f"OSTI #{source_id} has no full text and no open-access copy of DOI {doi}",
            {"source_id": source_id, "doi": doi},
        )
        return None
    if not ctx.can_download(url):
        progress.emit(
            f"OSTI #{source_id}: open-access copy {url} is not on the download allowlist",
            {"source_id": source_id, "doi": doi, "host": download_policy.host_of(url)},
        )
        return None
    progress.emit(
        f"OSTI #{source_id} has no full text; downloading the open-access copy {url}",
        {"source_id": source_id, "doi": doi},
    )
    return await _download_url(ctx, source_id, url)


def _note_refusal(ctx: RunContext, url: str, status: int) -> None:
    """A host that answers 401/403 refuses scripted downloads: skip it for the
    rest of the run (only this run - the refusal may be temporary)."""
    if status in (401, 403):
        host = download_policy.host_of(url)
        if host and host not in ctx.refused_hosts:
            ctx.refused_hosts.add(host)
            progress.emit(
                f"{host} refused the download (HTTP {status}); "
                "skipping it for the rest of this run",
                {"host": host, "status": status},
            )


def _download_failed(source_id: str, ctx: RunContext) -> dict:
    # Publishers often refuse scripted downloads (403). A failed download uses
    # no paper budget, so say so: the run should move on, not finish.
    return {
        "ok": False,
        "source_id": source_id,
        "error": ctx.download_failures[source_id],
        "instruction": (
            "This paper did not use up the paper budget; try the next most "
            "promising search result instead."
        ),
    }


def build_osti_tools(ctx: RunContext) -> List[BaseTool]:
    """Build the search/download/parse tools bound to one run's context."""

    @tool
    async def search_osti(query: str, max_results: int = 15) -> str:
        """Search the OSTI scientific database with a short keyword query (the
        API is bag-of-words - prefer 3-8 keywords over full sentences).
        Returns a JSON list of {osti_id, title, abstract, journal, url}."""
        reason = ctx.reserve_search("OSTI", query, ctx.config.max_osti_searches)
        if reason:
            exhausted = "limit reached" in reason
            return json.dumps(
                {
                    "results": [],
                    "error": f"skipped: {reason}",
                    "search_budget_exhausted": exhausted,
                    "instruction": (
                        "This search tool is used up for this run. Do not call it "
                        "again: download and analyze the most promising unread "
                        "results you already have, or use another search tool. "
                        "Emit the final JSON only when no promising result is "
                        "left or the paper or time budget is reached."
                        if exhausted
                        else "Use the earlier results instead of repeating this query."
                    ),
                }
            )

        progress.emit(f"Searching OSTI for: {query}")
        hits = await asyncio.to_thread(
            osti_client.search_osti,
            query,
            min(max_results, _MAX_OSTI_RESULTS),
        )
        out = []
        for h in hits:
            osti_id = str(h.get("osti_id", ""))
            if not osti_id or osti_id in ctx.search_hits:
                continue
            ctx.search_hits[osti_id] = h
            abstract = (h.get("description") or "")[:_ABSTRACT_TRUNCATE]
            out.append(
                {
                    "osti_id": osti_id,
                    "title": h.get("title", ""),
                    "abstract": abstract,
                    "journal": h.get("journal_name", ""),
                    "url": h.get("url", ""),
                }
            )
        progress.emit(f"Found {len(out)} papers in OSTI")
        return json.dumps(out)

    @tool
    async def download_paper(source_id: str, url: Optional[str] = None) -> str:
        """Download a paper's PDF. For OSTI results, pass just the osti_id. For a
        scholarly/web result, pass ``url`` set to its ``oa_pdf_url`` (or the direct
        PDF URL a search tool returned) - never invent one. Returns JSON
        {ok, source_id, pdf_path} on success or {ok: false, error} otherwise.
        Download only the most promising papers - the budget is limited."""
        source_id = str(source_id)
        if source_id in ctx.pdf_paths:
            return json.dumps(
                {
                    "ok": True,
                    "source_id": source_id,
                    "pdf_path": ctx.pdf_paths[source_id],
                }
            )
        if source_id in ctx.download_failures:
            return json.dumps(_download_failed(source_id, ctx))

        reason = ctx.budget_reason()
        if reason:
            return json.dumps(
                {"ok": False, "source_id": source_id, "error": f"skipped: {reason}"}
            )

        # A direct URL (explicit, or the oa_pdf_url recorded when the paper was
        # found) routes to the general downloader; otherwise use the OSTI purl.
        hit = ctx.search_hits.get(source_id, {})
        if url:
            allowed_urls = {hit.get("oa_pdf_url")}
            if hit.get("origin") == "web":
                allowed_urls.add(hit.get("url"))
            if url not in allowed_urls:
                return json.dumps(
                    {
                        "ok": False,
                        "source_id": source_id,
                        "error": (
                            "rejected: URL was not returned as a downloadable "
                            "PDF by a search tool"
                        ),
                    }
                )
        direct_url = url or hit.get("oa_pdf_url")

        if direct_url and not ctx.can_download(direct_url):
            host = download_policy.host_of(direct_url) or direct_url
            refused = host in ctx.refused_hosts
            ctx.download_failures[source_id] = (
                f"{host} refused a download earlier in this run"
                if refused
                else f"{host} is not on the download allowlist"
            )
            progress.emit(
                f"Skipping {source_id}: {ctx.download_failures[source_id]}",
                {"source_id": source_id, "host": host},
            )
            return json.dumps(_download_failed(source_id, ctx))

        if direct_url:
            progress.emit(f"Downloading {source_id} from {direct_url}")
            pdf_path = await _download_url(ctx, source_id, direct_url)
        else:
            progress.emit(f"Downloading OSTI #{source_id}")
            pdf_path = await asyncio.to_thread(
                osti_client.download_paper, source_id, ctx.pdf_cache
            )
            if not pdf_path and hit.get("doi"):
                pdf_path = await _open_access_copy(ctx, source_id, hit["doi"])

        if not pdf_path:
            ctx.download_failures[source_id] = "PDF not available for download"
            return json.dumps(_download_failed(source_id, ctx))
        ctx.pdf_paths[source_id] = pdf_path
        return json.dumps({"ok": True, "source_id": source_id, "pdf_path": pdf_path})

    @tool
    async def parse_paper(source_id: str) -> str:
        """Parse a downloaded PDF into /papers/{source_id}/ (paper.md, tables/,
        figures/) and return a JSON summary: method, page_count, the tables
        (with captions + shape) and figures (with captions + whether each was
        VLM-analyzed), and the directory path. Download the paper first. Call
        once per paper, then call analyze_paper with this source_id."""
        source_id = str(source_id)
        if source_id in ctx.parsed_papers:
            return json.dumps(ctx.parsed_papers[source_id])
        if source_id in ctx.parse_failures:
            return json.dumps(
                {"ok": False, "source_id": source_id, "error": ctx.parse_failures[source_id]}
            )

        pdf_path = ctx.pdf_paths.get(source_id)
        if not pdf_path:
            return json.dumps(
                {
                    "ok": False,
                    "source_id": source_id,
                    "error": "no downloaded PDF for this source_id; call download_paper first",
                }
            )
        reason = ctx.budget_reason()
        if reason:
            return json.dumps(
                {"ok": False, "source_id": source_id, "error": f"skipped: {reason}"}
            )

        # Parse into the per-run workdir so the artifacts land under the real
        # directory the /papers/ filesystem route points at.
        run_config = ctx.config.model_copy(update={"workdir": ctx.run_workdir})
        progress.emit(f"Parsing OSTI #{source_id} (tables + figures)")

        async def _forward(message: str, **detail) -> None:
            progress.emit(message, detail or None)

        # Count the attempt before parsing so a paper that hangs the parser
        # still uses a slot; an outright failure gives it back (below) so a bad
        # PDF doesn't cost the run a paper. Failures are remembered, so the
        # same PDF can't loop.
        ctx.papers_attempted += 1
        try:
            parsed = await parse_pipeline.parse_paper_pipeline(
                pdf_path,
                source_id,
                run_config,
                ctx.caches,
                emit=_forward,
                deadline=ctx.deadline,
            )
        except Exception as e:  # keep the tool contract: return a string, don't raise
            logger.warning("parse_paper failed for %s: %s", source_id, e)
            ctx.papers_attempted -= 1
            ctx.parse_failures[source_id] = f"parse failed: {e}"
            return json.dumps(
                {
                    "ok": False,
                    "source_id": source_id,
                    "error": ctx.parse_failures[source_id],
                    "instruction": (
                        "This paper did not use up the paper budget; try the next "
                        "most promising search result instead."
                    ),
                }
            )
        safe_id = _safe_source_id(source_id)
        summary = _parse_summary(parsed, safe_id)
        ctx.parsed_papers[source_id] = summary
        progress.emit(
            f"Parsed OSTI #{source_id}: {len(parsed.tables)} table(s), "
            f"{len(parsed.figures)} figure(s)",
            detail={"source_id": source_id, "method": parsed.method},
        )
        return json.dumps(summary)

    return [search_osti, download_paper, parse_paper]
