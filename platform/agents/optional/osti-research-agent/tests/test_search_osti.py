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

"""search_osti against a mocked OSTI API: title= first, JSON requested."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location("osti_agent_module_search", AGENT_DIR / "agent.py")
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _record(osti_id: str, title: str = "") -> dict:
    return {"osti_id": osti_id, "title": title or f"Paper {osti_id}", "description": "Abstract"}


def _response(records, status_code: int = 200, text: str | None = None):
    return SimpleNamespace(status_code=status_code, text=json.dumps(records) if text is None else text)


class FakeOSTI:
    """Stands in for requests.get: answers by (field, query, page)."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls = []

    def __call__(self, url, headers=None, timeout=None, verify=None):
        params = parse_qs(urlsplit(url).query)
        (field,) = [key for key in params if key != "page"]
        key = (field, params[field][0], int(params["page"][0]))
        self.calls.append((key, headers))
        return self.pages.get(key, _response([]))


@pytest.fixture
def agent():
    # search_osti uses no instance state
    return object.__new__(_MODULE.OSTIResearchAgent)


def _install(monkeypatch, pages: dict) -> FakeOSTI:
    fake = FakeOSTI(pages)
    monkeypatch.setattr(_MODULE.requests, "get", fake)
    return fake


def test_title_search_comes_first_and_asks_for_json(agent, monkeypatch):
    fake = _install(
        monkeypatch,
        {("title", "lithium thermal conductivity", 0): _response([_record("1"), _record("2")])},
    )

    results = agent.search_osti("lithium thermal conductivity", max_results=2)

    assert [r["osti_id"] for r in results] == ["1", "2"]
    assert results[0]["url"] == "https://www.osti.gov/biblio/1"
    assert fake.calls[0][0] == ("title", "lithium thermal conductivity", 0)
    assert all(headers == {"Accept": "application/json"} for _, headers in fake.calls)
    # Filled by title=, so q= is never asked
    assert not any(key[0] == "q" for key, _ in fake.calls)


def test_numeric_words_are_dropped_for_a_second_title_search(agent, monkeypatch):
    fake = _install(
        monkeypatch,
        {
            ("title", "lithium thermal conductivity", 0): _response([_record("7")]),
            ("q", "lithium thermal conductivity 800K", 0): _response([_record("8")]),
        },
    )

    results = agent.search_osti("lithium thermal conductivity 800K", max_results=5)

    assert [r["osti_id"] for r in results] == ["7", "8"]
    asked = [key for key, _ in fake.calls if key[2] == 0]
    assert asked == [
        ("title", "lithium thermal conductivity 800K", 0),
        ("title", "lithium thermal conductivity", 0),
        ("q", "lithium thermal conductivity 800K", 0),
    ]


def test_q_tops_up_without_duplicates(agent, monkeypatch):
    _install(
        monkeypatch,
        {
            ("title", "sodium fast reactor", 0): _response([_record("1"), _record("2")]),
            ("q", "sodium fast reactor", 0): _response([_record("2"), _record("3"), _record("4")]),
        },
    )

    results = agent.search_osti("sodium fast reactor", max_results=3)

    assert [r["osti_id"] for r in results] == ["1", "2", "3"]


def test_records_without_an_abstract_are_skipped(agent, monkeypatch):
    _install(
        monkeypatch,
        {("title", "molten salt", 0): _response([{"osti_id": "1", "title": "No abstract"}, _record("2")])},
    )

    results = agent.search_osti("molten salt", max_results=5)

    assert [r["osti_id"] for r in results] == ["2"]


def test_a_non_json_answer_falls_through_to_the_next_search(agent, monkeypatch):
    _install(
        monkeypatch,
        {
            ("title", "graphite oxidation", 0): _response(None, text="<?xml version='1.0'?><records/>"),
            ("q", "graphite oxidation", 0): _response([_record("5")]),
        },
    )

    results = agent.search_osti("graphite oxidation", max_results=5)

    assert [r["osti_id"] for r in results] == ["5"]


def test_errors_and_non_200_answers_return_what_was_found(agent, monkeypatch):
    def fake_get(url, headers=None, timeout=None, verify=None):
        if "title=" in url:
            return _response([], status_code=503, text="Service Unavailable")
        raise _MODULE.requests.ConnectionError("down")

    monkeypatch.setattr(_MODULE.requests, "get", fake_get)

    assert agent.search_osti("helium", max_results=5) == []


def test_paging_stops_at_the_page_limit(agent, monkeypatch):
    fake = _install(
        monkeypatch,
        {("title", "fuel", page): _response([_record(f"{page}")]) for page in range(10)},
    )

    results = agent.search_osti("fuel", max_results=50)

    title_pages = [key[2] for key, _ in fake.calls if key[0] == "title"]
    assert title_pages == [0, 1, 2, 3, 4, 5]
    assert [r["osti_id"] for r in results] == ["0", "1", "2", "3", "4", "5"]
