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

"""Content of the searched-papers list and the evidence citation cards."""

import json

from research_agent.core import search_artifacts
from research_agent.core.adapter import result_to_a2a_json
from research_agent.core.events import FinalResult, Finding

HITS = {
    "123": {
        "title": "Creep of [Ti] alloys",
        "url": "https://www.osti.gov/biblio/123",
        "description": "OSTI abstract  with\nwhitespace.",
    },
    "10.1_ab": {
        "title": "Open-access creep study",
        "url": "https://doi.org/10.1/ab",
        "origin": "openalex",
        "abstract": "x" * 1000,
        "year": 2021,
    },
    "url_abc": {"title": "", "url": "", "origin": "tavily", "abstract": ""},
}


def _result(**overrides):
    values = {
        "status": "completed",
        "question": "Does Ti creep?",
        "searched_papers": HITS,
        "findings": [
            Finding(source_id="10.1_ab", answer=" creeps above 800 C ", evidence="Fig 2")
        ],
    }
    values.update(overrides)
    return FinalResult(**values)


def test_listing_shows_every_hit_with_source_and_abstract():
    text = search_artifacts.searched_papers_markdown(_result())

    assert "3 paper(s) returned by the searches; 1 used as verified evidence" in text
    assert "## 1. [Creep of (Ti) alloys](https://www.osti.gov/biblio/123)\nOSTI" in text
    assert "OSTI abstract with whitespace." in text
    assert "[Open-access creep study](https://doi.org/10.1/ab) ✓" in text
    assert "OpenAlex · 2021 · `10.1_ab`" in text
    assert "## 3. url_abc\nWeb" in text


def test_listing_truncates_abstracts_and_caps_the_paper_count(monkeypatch):
    monkeypatch.setattr(search_artifacts, "MAX_LISTED_PAPERS", 2)
    text = search_artifacts.searched_papers_markdown(_result())

    assert "x" * search_artifacts.ABSTRACT_CHARS not in text
    assert "x" * (search_artifacts.ABSTRACT_CHARS - 1) + "…" in text
    assert "Showing the first 2." in text and "## 3." not in text


def test_no_listing_when_nothing_was_searched():
    assert search_artifacts.searched_papers_markdown(_result(searched_papers={})) is None


def test_one_citation_card_per_finding_source():
    findings = [
        Finding(source_id="10.1_ab", answer="a", evidence="e"),
        Finding(source_id="10.1_ab", answer="b", evidence="e"),
        Finding(source_id="999", answer="unsearched osti", evidence="e"),
    ]
    cards = search_artifacts.evidence_citations(_result(findings=findings))

    assert [c.source_id for c in cards] == ["10.1_ab", "999"]
    assert cards[0].name == "Open-access creep study"
    assert cards[0].uri == "https://doi.org/10.1/ab"
    assert cards[0].source == "OpenAlex · 10.1_ab"
    assert cards[1].uri == "https://www.osti.gov/biblio/999"


def test_searched_papers_stay_off_the_wire():
    payload = json.loads(result_to_a2a_json(_result()))

    assert "searched_papers" not in payload
