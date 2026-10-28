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

"""Provenance deduplication and citation linkification for OSTI research answers."""

import re
from typing import Any, Dict, List


def is_memory_answer_sufficient(answer_text: str) -> bool:
    """Heuristic fallback for deciding if a KB-only answer is sufficient."""
    if not isinstance(answer_text, str):
        return False

    text = answer_text.strip()
    if not text:
        return False

    lowered = text.lower()
    explicit_insufficient_markers = [
        "not enough information",
        "insufficient information",
        "insufficient data",
        "cannot answer",
        "can't answer",
        "unable to determine",
        "do not have enough",
        "don't have enough",
        "no relevant information",
        "not enough context",
    ]

    if any(marker in lowered for marker in explicit_insufficient_markers):
        return False

    # Very short responses are usually not actionable final answers.
    if len(text) < 60:
        return False

    return True


def deduplicate_provenance_simple(
    provenance: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Simple deduplication for cached/pre-built provenance lists (no mapping needed)."""
    seen_ids = set()
    deduplicated = []
    for source in provenance:
        source = {key: value for key, value in source.items() if key != "confidence"}
        osti_id = source.get("source", "").replace("OSTI #", "")
        if osti_id and osti_id not in seen_ids:
            seen_ids.add(osti_id)
            deduplicated.append(source)
        elif not osti_id:
            deduplicated.append(source)
    return deduplicated


def deduplicate_provenance_with_mapping(
    answers: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[int, int]]:
    """
    Deduplicate answers by OSTI ID and build a mapping from original paper numbers
    to deduplicated provenance indices.

    Returns:
        - provenance: List of unique sources with 'original_papers' field showing
          which Paper N references map to this source
        - paper_to_provenance: Dict mapping original paper number (1-indexed) to
          provenance index (1-indexed) for linkification

    Example:
        If answers = [Paper A, Paper B, Paper A, Paper C, Paper A]
        Then provenance will have 3 entries:
          1. Paper A with original_papers=[1, 3, 5]
          2. Paper B with original_papers=[2]
          3. Paper C with original_papers=[4]
        And paper_to_provenance = {1: 1, 2: 2, 3: 1, 4: 3, 5: 1}
    """
    seen_ids: Dict[str, int] = {}  # osti_id -> provenance index (0-based)
    provenance = []
    paper_to_provenance: Dict[int, int] = (
        {}
    )  # original paper num -> provenance num (1-indexed)

    for i, ans in enumerate(answers):
        original_paper_num = i + 1  # 1-indexed
        osti_id = ans.get("osti_id", "")

        if osti_id and osti_id in seen_ids:
            # Duplicate - add to existing provenance entry's original_papers list
            prov_idx = seen_ids[osti_id]
            provenance[prov_idx]["original_papers"].append(original_paper_num)
            paper_to_provenance[original_paper_num] = prov_idx + 1  # 1-indexed
        else:
            # New unique paper
            prov_idx = len(provenance)
            if osti_id:
                seen_ids[osti_id] = prov_idx

            provenance.append(
                {
                    "source": f"OSTI #{osti_id}" if osti_id else "Unknown",
                    "title": ans["title"],
                    "url": ans["url"],
                    "excerpt": ans.get("excerpt", "")[:500],
                    "original_papers": [original_paper_num],
                }
            )
            paper_to_provenance[original_paper_num] = prov_idx + 1  # 1-indexed

    return provenance, paper_to_provenance


def linkify_paper_references(
    answer_text: str,
    provenance: List[Dict[str, Any]],
    paper_to_provenance: Dict[int, int] = None,
) -> str:
    """
    Convert 'Paper X' citations to clickable [Paper N](url) links.

    If paper_to_provenance mapping is provided, maps original paper numbers
    to their deduplicated provenance indices. Otherwise falls back to direct
    1:1 mapping.

    Args:
        answer_text: The synthesized answer text with "Paper N" references
        provenance: List of deduplicated sources
        paper_to_provenance: Optional mapping from original paper number to
                            provenance index (both 1-indexed)
    """
    if not provenance:
        return answer_text

    # Build URL map: provenance_index -> url (1-indexed)
    url_map = {i: source.get("url", "") for i, source in enumerate(provenance, 1)}

    def replace_citation(match):
        original_paper_num = int(match.group(1))

        if paper_to_provenance:
            # Map original paper number to deduplicated provenance index
            prov_num = paper_to_provenance.get(original_paper_num)
            if prov_num and prov_num in url_map:
                url = url_map[prov_num]
                if url:
                    return f"[Paper {prov_num}]({url})"
        else:
            # Fallback: direct 1:1 mapping
            url = url_map.get(original_paper_num, "")
            if url:
                return f"[Paper {original_paper_num}]({url})"

        return match.group(0)  # Keep original if no mapping found

    # Match patterns like "Paper 1", "Paper 2", etc.
    result = re.sub(r"Paper\s*(\d+)", replace_citation, answer_text)
    return result
