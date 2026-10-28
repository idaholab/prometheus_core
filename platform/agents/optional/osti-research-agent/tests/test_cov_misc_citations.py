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
"""Edge cases of the KB-answer heuristic, provenance dedup and citation links."""

from research_agent.citations import (
    deduplicate_provenance_simple,
    is_memory_answer_sufficient,
    linkify_paper_references,
)

LONG = "Titanium alloys creep measurably above 800 C under moderate stress levels."


def test_non_string_answer_is_not_sufficient():
    assert is_memory_answer_sufficient(None) is False
    assert is_memory_answer_sufficient(42) is False


def test_blank_answer_is_not_sufficient():
    assert is_memory_answer_sufficient("   \n ") is False


def test_short_answer_is_not_sufficient_but_a_long_one_is():
    assert is_memory_answer_sufficient("Titanium creeps.") is False
    assert is_memory_answer_sufficient(LONG) is True


def test_simple_dedup_drops_repeats_and_confidence_but_keeps_unsourced():
    provenance = [
        {"source": "OSTI #1", "title": "A", "confidence": 0.9},
        {"source": "OSTI #1", "title": "A again"},
        {"title": "no source"},
        {"source": "", "title": "empty source"},
        {"source": "OSTI #2", "title": "B"},
    ]

    out = deduplicate_provenance_simple(provenance)

    assert [p["title"] for p in out] == ["A", "no source", "empty source", "B"]
    assert all("confidence" not in p for p in out)
    assert "confidence" in provenance[0]  # the input is not mutated


def test_linkify_keeps_a_citation_that_has_no_mapping_or_url():
    provenance = [{"url": "https://www.osti.gov/biblio/1"}, {"url": ""}]
    mapping = {1: 1, 2: 2}

    out = linkify_paper_references("See Paper 1, Paper 2 and Paper 7.", provenance, mapping)

    assert out == "See [Paper 1](https://www.osti.gov/biblio/1), Paper 2 and Paper 7."


def test_linkify_without_mapping_keeps_a_citation_with_no_url():
    out = linkify_paper_references("Paper 1 and Paper 3", [{"url": "https://a/1"}])

    assert out == "[Paper 1](https://a/1) and Paper 3"
