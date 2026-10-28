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
from unittest.mock import MagicMock, patch

from research_agent import osti_client


def _response(status_code=200, text="[]"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def test_pagination_stops_after_page_limit():
    """No page ever satisfies max_results, so the safety limit (page > 5) stops the loop."""
    page_payload = json.dumps(
        [{"osti_id": "1", "title": "T", "description": "D", "journal_name": "J"}]
    )

    with patch.object(
        osti_client.requests, "get", return_value=_response(text=page_payload)
    ) as mock_get:
        results = osti_client.search_osti("creep rate", max_results=100)

    # Pages 0-5 inclusive = 6 requests before the "page > 5" safety limit breaks the loop.
    assert mock_get.call_count == 6
    assert len(results) == 6


def test_records_missing_description_or_osti_id_are_skipped():
    payload = json.dumps(
        [
            {
                "osti_id": "1",
                "title": "Has both",
                "description": "D",
                "journal_name": "J",
            },
            {"osti_id": "2", "title": "Missing description", "journal_name": "J"},
            {"title": "Missing osti_id", "description": "D", "journal_name": "J"},
        ]
    )

    responses = [_response(text=payload), _response(text="[]")]
    with patch.object(osti_client.requests, "get", side_effect=responses):
        results = osti_client.search_osti("creep rate", max_results=15)

    assert len(results) == 1
    assert results[0]["osti_id"] == "1"


def test_non_200_response_breaks_the_loop():
    with patch.object(
        osti_client.requests, "get", return_value=_response(status_code=500)
    ) as mock_get:
        results = osti_client.search_osti("creep rate", max_results=15)

    assert results == []
    mock_get.assert_called_once()


def test_json_repair_handles_escaped_apostrophe():
    # OSTI sometimes returns backslash-escaped apostrophes that aren't valid JSON escapes.
    payload = r"""[{"osti_id": "999", "title": "Bob\'s Paper", "description": "d", "journal_name": "j"}]"""

    responses = [_response(text=payload), _response(text="[]")]
    with patch.object(osti_client.requests, "get", side_effect=responses):
        results = osti_client.search_osti("creep rate", max_results=15)

    assert len(results) == 1
    assert results[0]["title"] == "Bob's Paper"


def test_search_asks_the_api_for_json():
    with patch.object(osti_client.requests, "get", return_value=_response()) as mock_get:
        osti_client.search_osti("creep rate", max_results=15)

    assert mock_get.call_args.kwargs["headers"] == {"Accept": "application/json"}


def test_xml_response_is_one_short_warning_and_keeps_earlier_results(caplog):
    page_one = json.dumps([{"osti_id": "1", "title": "T", "description": "D"}])
    xml = _response(text='<?xml version="1.0" encoding="UTF-8"?>\n<records>' + "x" * 5000)
    xml.headers = {"Content-Type": "application/xml"}

    with patch.object(osti_client.requests, "get", side_effect=[_response(text=page_one), xml]):
        with caplog.at_level("INFO", logger="research_agent.osti_client"):
            results = osti_client.search_osti("creep rate", max_results=15)

    assert [r["osti_id"] for r in results] == ["1"]
    problems = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert len(problems) == 1 and problems[0].levelname == "WARNING"
    message = problems[0].getMessage()
    assert "not JSON" in message and "application/xml" in message
    assert len(message) < 400  # no 1000-character dump of the response
