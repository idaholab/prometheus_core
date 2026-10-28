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

from research_agent.citations import (
    deduplicate_provenance_with_mapping,
    is_memory_answer_sufficient,
    linkify_paper_references,
)


def test_linkify_uses_mapping_for_deduplicated_papers():
    answers = [
        {
            "osti_id": "111",
            "title": "A",
            "url": "https://osti.gov/biblio/111",
            "confidence": 0.9,
        },
        {"osti_id": "222", "title": "B", "url": "https://osti.gov/biblio/222"},
        {
            "osti_id": "111",
            "title": "A duplicate",
            "url": "https://osti.gov/biblio/111",
        },
        {"osti_id": "333", "title": "C", "url": "https://osti.gov/biblio/333"},
    ]
    provenance, paper_to_provenance = deduplicate_provenance_with_mapping(answers)

    text = "Evidence from Paper 1, Paper 3, and Paper 4 supports the conclusion."
    linked = linkify_paper_references(text, provenance, paper_to_provenance)

    assert "[Paper 1](https://osti.gov/biblio/111)" in linked
    assert "[Paper 3](https://osti.gov/biblio/333)" in linked
    assert linked.count("[Paper 1](https://osti.gov/biblio/111)") == 2
    assert "Paper 4" not in linked
    assert all("confidence" not in source for source in provenance)


def test_linkify_without_mapping_uses_direct_index():
    provenance = [
        {"source": "OSTI #10", "url": "https://osti.gov/biblio/10"},
        {"source": "OSTI #20", "url": "https://osti.gov/biblio/20"},
    ]
    text = "See Paper 2 for details."
    linked = linkify_paper_references(text, provenance)

    assert linked == "See [Paper 2](https://osti.gov/biblio/20) for details."
    assert "[[2]]" not in linked


def test_memory_answer_sufficient_heuristic_rejects_insufficient_language():
    text = "There is not enough information in the knowledge base to answer this question reliably."
    assert is_memory_answer_sufficient(text) is False


def test_memory_answer_sufficient_heuristic_accepts_substantive_answer():
    text = (
        "Based on Fact 1 and Fact 2, SS316 shows improved corrosion resistance between "
        "280C and 320C in high-purity water, with degradation accelerating above 350C."
    )
    assert is_memory_answer_sufficient(text) is True
