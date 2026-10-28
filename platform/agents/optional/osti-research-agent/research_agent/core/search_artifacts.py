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

"""Plain-data content for the artifacts that show a run's literature search.

Two kinds, built here without any platform import so they stay testable; the
A2A layer (agent.py) registers and sends them:

- one Markdown list of every paper the run's searches returned, with its
  abstract (rendered by the platform's report viewer), and
- one citation card per paper that produced a verified finding (rendered by
  the reference viewer), so users can tell what was used from what was seen.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from research_agent.core.events import FinalResult

MAX_LISTED_PAPERS = 40
ABSTRACT_CHARS = 600

_ORIGIN_LABELS = {
    "osti": "OSTI",
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "tavily": "Web",
    "searxng": "Web",
    "web": "Web",
}


class CitationCard(BaseModel):
    source_id: str
    name: str
    description: str
    uri: Optional[str] = None
    source: str


def _origin(hit: Dict[str, Any]) -> str:
    return _ORIGIN_LABELS.get(str(hit.get("origin") or "osti").lower(), "Web")


def _abstract(hit: Dict[str, Any]) -> str:
    # OSTI hits keep the raw API record, whose abstract is "description".
    text = hit.get("abstract") or hit.get("description") or ""
    text = " ".join(str(text).split())
    if len(text) > ABSTRACT_CHARS:
        text = text[: ABSTRACT_CHARS - 1].rstrip() + "…"
    return text


def _markdown_text(value: Any) -> str:
    """Keep untrusted titles from breaking the Markdown link syntax."""
    return " ".join(str(value or "").split()).replace("[", "(").replace("]", ")")


def searched_papers_markdown(result: FinalResult) -> Optional[str]:
    """A Markdown list of the run's search hits, or None when there were none."""
    hits = result.searched_papers
    if not hits:
        return None
    used = {f.source_id for f in result.findings}
    listed = list(hits.items())[:MAX_LISTED_PAPERS]

    lines = [f"# Papers searched for: {_markdown_text(result.question)}", ""]
    lines.append(
        f"{len(hits)} paper(s) returned by the searches; "
        f"{len(used & set(hits))} used as verified evidence (marked ✓)."
    )
    if len(hits) > len(listed):
        lines.append(f"Showing the first {len(listed)}.")
    for index, (source_id, hit) in enumerate(listed, 1):
        title = _markdown_text(hit.get("title")) or source_id
        url = hit.get("url") or ""
        heading = f"[{title}]({url})" if url else title
        marker = " ✓" if source_id in used else ""
        details = [_origin(hit)]
        if hit.get("year"):
            details.append(str(hit["year"]))
        details.append(f"`{source_id}`")
        lines.extend(["", f"## {index}. {heading}{marker}", " · ".join(details)])
        abstract = _abstract(hit)
        if abstract:
            lines.extend(["", abstract])
    return "\n".join(lines) + "\n"


def evidence_citations(result: FinalResult) -> List[CitationCard]:
    """One card per verified finding, in the order the answer cites them."""
    cards: List[CitationCard] = []
    seen = set()
    for finding in result.findings:
        if finding.source_id in seen:
            continue
        seen.add(finding.source_id)
        hit = result.searched_papers.get(finding.source_id, {})
        url = hit.get("url") or None
        if not url and finding.source_id.isdigit():
            url = f"https://www.osti.gov/biblio/{finding.source_id}"
        cards.append(
            CitationCard(
                source_id=finding.source_id,
                name=_markdown_text(hit.get("title")) or finding.source_id,
                description=finding.answer.strip(),
                uri=url,
                source=f"{_origin(hit)} · {finding.source_id}",
            )
        )
    return cards
