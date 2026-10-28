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

"""The automatic evaluation metrics are pure and offline, so they are
tested directly here (evals/run.py, which needs live services, is not)."""

from evals import scoring

# --- citation_link_rate ---------------------------------------------------


def test_citation_link_rate_all_linked():
    answer = "Creep dominates [Paper 1](http://a) and [Paper 2](http://b)."
    assert scoring.citation_link_rate(answer) == 1.0


def test_citation_link_rate_some_bare():
    # One linked, one bare -> 0.5
    answer = "See [Paper 1](http://a) but Paper 2 was not linkified."
    assert scoring.citation_link_rate(answer) == 0.5


def test_citation_link_rate_no_citations_is_one():
    assert scoring.citation_link_rate("No citations here.") == 1.0
    assert scoring.citation_link_rate("") == 1.0


# --- expected_source_hit_rate ---------------------------------------------


def test_source_hit_rate_matches_osti_id_and_doi_slug():
    provenance = [
        {"source": "OSTI #12345", "url": "https://osti.gov/biblio/12345"},
        {"source": "10.1234_abc", "url": "https://doi.org/10.1234/abc"},
    ]
    assert scoring.expected_source_hit_rate(provenance, ["12345", "10.1234_abc"]) == 1.0
    assert scoring.expected_source_hit_rate(provenance, ["12345", "99999"]) == 0.5


def test_source_hit_rate_empty_expectation_is_one():
    assert scoring.expected_source_hit_rate([], None) == 1.0
    assert scoring.expected_source_hit_rate([], []) == 1.0


# --- expected_fact_match --------------------------------------------------


def test_fact_match_case_insensitive_substring():
    answer = "The creep rate of SS316 is about 1e-8 per hour."
    assert scoring.expected_fact_match(answer, ["ss316", "1e-8"]) == 1.0
    assert scoring.expected_fact_match(answer, ["ss316", "titanium"]) == 0.5


def test_fact_match_empty_expectation_is_one():
    assert scoring.expected_fact_match("anything", None) == 1.0


# --- provenance_ok / status_match -----------------------------------------


def test_provenance_ok_requires_sources_only_for_completed():
    assert (
        scoring.provenance_ok({"status": "completed", "provenance": [{"x": 1}]}) is True
    )
    assert scoring.provenance_ok({"status": "completed", "provenance": []}) is False
    # no_results legitimately cites nothing; error/timeout aren't held to it
    assert scoring.provenance_ok({"status": "no_results", "provenance": []}) is True
    assert scoring.provenance_ok({"status": "error", "provenance": []}) is True


def test_status_match():
    assert scoring.status_match({"status": "completed"}, "completed") is True
    assert scoring.status_match({"status": "no_results"}, "completed") is False
    assert scoring.status_match({"status": "completed"}, None) is True


# --- score_result / aggregate ---------------------------------------------


def test_score_result_shape():
    result = {
        "_engine": "deepagent",
        "_wall_s": 42.0,
        "status": "completed",
        "answer": "SS316 creeps; see [Paper 1](http://a).",
        "provenance": [{"source": "OSTI #12345"}],
        "papers_analyzed": 2,
        "facts_stored": 5,
    }
    spec = {
        "id": "q1",
        "expected_source_ids": ["12345"],
        "expected_facts": ["ss316"],
        "expect_status": "completed",
    }
    rec = scoring.score_result(result, spec)
    assert rec["id"] == "q1"
    assert rec["engine"] == "deepagent"
    assert rec["status_match"] is True
    assert rec["provenance_ok"] is True
    assert rec["citation_link_rate"] == 1.0
    assert rec["source_hit_rate"] == 1.0
    assert rec["fact_match"] == 1.0
    assert rec["wall_s"] == 42.0


def test_aggregate_medians_and_counts():
    records = [
        {
            "engine": "deepagent",
            "status_match": True,
            "provenance_ok": True,
            "citation_link_rate": 1.0,
            "source_hit_rate": 1.0,
            "fact_match": 1.0,
            "wall_s": 10.0,
        },
        {
            "engine": "deepagent",
            "status_match": False,
            "provenance_ok": True,
            "citation_link_rate": 0.5,
            "source_hit_rate": 0.0,
            "fact_match": 0.5,
            "wall_s": 30.0,
        },
        {
            "engine": "pipeline",
            "status_match": True,
            "provenance_ok": False,
            "citation_link_rate": 1.0,
            "source_hit_rate": 1.0,
            "fact_match": 0.0,
            "wall_s": 20.0,
        },
    ]
    agg = scoring.aggregate(records)
    assert agg["deepagent"]["n"] == 2
    assert agg["deepagent"]["status_match"] == 1
    assert agg["deepagent"]["median_citation_link_rate"] == 0.75
    assert agg["deepagent"]["median_wall_s"] == 20.0
    assert agg["pipeline"]["n"] == 1
    assert agg["pipeline"]["provenance_ok"] == 0
