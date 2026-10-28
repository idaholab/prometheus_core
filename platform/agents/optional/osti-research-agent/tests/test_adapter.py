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

import json

from research_agent.core.adapter import result_to_a2a_json
from research_agent.core.events import FinalResult, Finding

# Every status must expose the same public response shape.
EXPECTED_KEYS = {
    "status",
    "question",
    "answer",
    "provenance",
    "findings",
    "search_query",
    "papers_assessed",
    "relevant_papers",
    "papers_analyzed",
    "facts_stored",
    "suggested_queries",
    "progress_log",
    "cached",
    "source",
    "timestamp",
    "agent",
}


def test_result_to_a2a_json_key_set():
    result = FinalResult(status="completed", question="q", answer="a")
    payload = json.loads(result_to_a2a_json(result))

    assert set(payload.keys()) == EXPECTED_KEYS


def test_result_to_a2a_json_preserves_agent_field():
    result = FinalResult(status="completed", question="q", answer="a")
    payload = json.loads(result_to_a2a_json(result))

    assert payload["agent"] == "OSTI Research Agent"


def test_result_to_a2a_json_handles_every_status():
    for status in ("completed", "no_results", "error", "timeout_partial"):
        result = FinalResult(status=status, question="q")
        payload = json.loads(result_to_a2a_json(result))
        assert payload["status"] == status
        assert set(payload.keys()) == EXPECTED_KEYS


def test_result_to_a2a_json_does_not_emit_finding_confidence():
    result = FinalResult(
        status="completed",
        question="q",
        findings=[Finding(source_id="123", answer="verified")],
    )

    payload = json.loads(result_to_a2a_json(result))

    assert "confidence" not in payload["findings"][0]
