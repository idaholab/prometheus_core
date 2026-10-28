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

"""Automatic scoring for the parity evaluation.

Pure functions over a ``FinalResult`` dict and a question spec - no network, no
LLM, no Redis - so they're unit-tested offline in ``tests/test_eval_scoring.py``
and reused by ``evals/run.py`` after each live run. The LLM-judged rubric
(groundedness/completeness) and the manual transcript spot-check described in
the plan live in ``run.py`` / are done by hand; only the mechanical metrics are
here.
"""

from __future__ import annotations

import json
import re
import statistics
from typing import Any, Dict, List, Optional

# "Paper N" citation convention (mirrors citations.linkify_paper_references).
_ANY_PAPER_RE = re.compile(r"Paper\s*\d+")
# A linkified reference: [Paper N](some-url).
_LINKED_PAPER_RE = re.compile(r"\[Paper\s*\d+\]\([^)]+\)")


def citation_link_rate(answer: str) -> float:
    """Fraction of ``Paper N`` mentions that are markdown links. 1.0 when the
    answer cites nothing (nothing to linkify). ``_ANY_PAPER_RE`` also matches the
    text inside a ``[Paper N](url)`` link, so linked/total is the linkified
    share directly."""
    total = len(_ANY_PAPER_RE.findall(answer or ""))
    if total == 0:
        return 1.0
    linked = len(_LINKED_PAPER_RE.findall(answer or ""))
    return linked / total


def _provenance_blobs(provenance: List[Dict[str, Any]]) -> List[str]:
    return [json.dumps(p, default=str).lower() for p in provenance or []]


def expected_source_hit_rate(
    provenance: List[Dict[str, Any]], expected_ids: Optional[List[str]]
) -> float:
    """Fraction of expected source ids (OSTI ids or DOI slugs) that appear
    anywhere in a provenance entry. 1.0 when nothing is expected."""
    if not expected_ids:
        return 1.0
    blobs = _provenance_blobs(provenance)
    hits = sum(1 for sid in expected_ids if any(str(sid).lower() in b for b in blobs))
    return hits / len(expected_ids)


def expected_fact_match(answer: str, expected_facts: Optional[List[str]]) -> float:
    """Fraction of expected fact strings present (case-insensitive substring) in
    the answer. Numeric facts are matched as their string form (e.g. "316",
    "10^-8"). 1.0 when nothing is expected."""
    if not expected_facts:
        return 1.0
    low = (answer or "").lower()
    hits = sum(1 for f in expected_facts if str(f).lower() in low)
    return hits / len(expected_facts)


def provenance_ok(result: Dict[str, Any]) -> bool:
    """A completed answer must cite something; no_results legitimately cites
    nothing; error/timeout_partial aren't held to it."""
    status = result.get("status")
    if status == "completed":
        return bool(result.get("provenance"))
    return True


def status_match(result: Dict[str, Any], expected_status: Optional[str]) -> bool:
    """True when no specific status was expected, else exact match."""
    if not expected_status:
        return True
    return result.get("status") == expected_status


def score_result(result: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Automatic per-question score record for one engine's ``FinalResult``."""
    answer = result.get("answer", "")
    provenance = result.get("provenance", [])
    return {
        "id": spec.get("id"),
        "engine": result.get("_engine"),
        "status": result.get("status"),
        "status_match": status_match(result, spec.get("expect_status")),
        "provenance_ok": provenance_ok(result),
        "citation_link_rate": round(citation_link_rate(answer), 4),
        "source_hit_rate": round(
            expected_source_hit_rate(provenance, spec.get("expected_source_ids")), 4
        ),
        "fact_match": round(expected_fact_match(answer, spec.get("expected_facts")), 4),
        "papers_analyzed": result.get("papers_analyzed", 0),
        "facts_stored": result.get("facts_stored", 0),
        "cached": result.get("cached", False),
        "wall_s": result.get("_wall_s"),
        # What was expected and what was missed, so the report can explain a
        # failure without the question file.
        "expect_status": spec.get("expect_status"),
        "missing_facts": [
            f for f in spec.get("expected_facts") or []
            if str(f).lower() not in (answer or "").lower()
        ],
        "missing_sources": [
            s for s in spec.get("expected_source_ids") or []
            if not any(str(s).lower() in b for b in _provenance_blobs(provenance))
        ],
    }


def _median(values: List[float]) -> Optional[float]:
    clean = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(clean), 4) if clean else None


def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll per-question records up per engine: medians of the rate metrics and
    the pass counts the acceptance bar is read against."""
    out: Dict[str, Any] = {}
    engines = sorted({r.get("engine") for r in records if r.get("engine")})
    for engine in engines:
        rs = [r for r in records if r.get("engine") == engine]
        n = len(rs)
        out[engine] = {
            "n": n,
            "status_match": sum(1 for r in rs if r["status_match"]),
            "provenance_ok": sum(1 for r in rs if r["provenance_ok"]),
            "median_citation_link_rate": _median([r["citation_link_rate"] for r in rs]),
            "median_source_hit_rate": _median([r["source_hit_rate"] for r in rs]),
            "median_fact_match": _median([r["fact_match"] for r in rs]),
            "median_wall_s": _median([r["wall_s"] for r in rs]),
            "p90_wall_s": _p90([r["wall_s"] for r in rs]),
        }
    return out


def _p90(values: List[float]) -> Optional[float]:
    clean = sorted(v for v in values if isinstance(v, (int, float)))
    if not clean:
        return None
    # Nearest-rank p90.
    idx = max(0, min(len(clean) - 1, int(round(0.9 * (len(clean) - 1)))))
    return round(clean[idx], 4)
