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
"""Failure-path tests for the OSTI search, URL downloader and paper download."""

import json
from unittest.mock import MagicMock, patch

from research_agent import osti_client

_PDF = b"%PDF-1.5\nbody"


def _resp(status_code=200, headers=None, content=b"", text="[]"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.content = content
    resp.text = text
    return resp


def _session(resp=None, raises=None):
    session = MagicMock()
    if raises is not None:
        session.get.side_effect = raises
    else:
        session.get.return_value = resp
    return session


class FakePdfCache:
    def __init__(self, data=None, fail_get=False, fail_put=False):
        self.data = dict(data or {})
        self.fail_get = fail_get
        self.fail_put = fail_put
        self.puts = []

    def get_pdf(self, key):
        if self.fail_get:
            raise ConnectionError("cache down")
        return self.data.get(key)

    def put_pdf(self, key, data, ttl_s):
        if self.fail_put:
            raise ConnectionError("cache down")
        self.puts.append((key, data, ttl_s))
        self.data[key] = data


# --- download_pdf_from_url -----------------------------------------------------


def test_cached_pdf_that_cannot_be_written_returns_none(tmp_path):
    url = "https://x/p.pdf"
    cache = FakePdfCache({osti_client.url_cache_key(url): _PDF})
    dest = str(tmp_path / "missing_dir" / "p.pdf")

    with patch.object(osti_client.requests, "Session") as session_cls:
        out = osti_client.download_pdf_from_url(url, dest, cache=cache)

    assert out is None
    session_cls.assert_not_called()  # the cache hit never reaches the network


def test_fetched_pdf_that_cannot_be_written_returns_none(tmp_path):
    dest = str(tmp_path / "missing_dir" / "p.pdf")
    resp = _resp(headers={"Content-Type": "application/pdf"}, content=_PDF)
    cache = FakePdfCache()

    with patch.object(osti_client.requests, "Session", return_value=_session(resp)):
        out = osti_client.download_pdf_from_url("https://x/p.pdf", dest, cache=cache)

    assert out is None
    assert cache.puts == []  # nothing is cached for a failed write


# --- search_osti ---------------------------------------------------------------


def test_search_stops_once_max_results_reached_within_a_page():
    records = [
        {"osti_id": str(i), "title": f"T{i}", "description": "D", "doi": "10.1/x"}
        for i in range(5)
    ]
    with patch.object(
        osti_client.requests, "get", return_value=_resp(text=json.dumps(records))
    ) as get:
        results = osti_client.search_osti("q", max_results=2)

    assert get.call_count == 1
    assert [r["osti_id"] for r in results] == ["0", "1"]
    assert results[0]["doi"] == "10.1/x"
    assert results[0]["url"] == "https://www.osti.gov/biblio/0"


def test_search_keeps_results_found_before_a_request_error():
    page = json.dumps([{"osti_id": "1", "title": "T", "description": "D"}])
    side_effect = [_resp(text=page), RuntimeError("connection reset")]
    with patch.object(osti_client.requests, "get", side_effect=side_effect):
        results = osti_client.search_osti("q", max_results=10)

    assert [r["osti_id"] for r in results] == ["1"]


# --- download_paper ------------------------------------------------------------


def _tmp_paths(monkeypatch, tmp_path):
    """Redirect download_paper's /tmp/osti_{id}.pdf path into tmp_path."""
    real_open = open
    real_exists = osti_client.os.path.exists

    def redirect(path):
        if isinstance(path, str) and path.startswith("/tmp/osti_"):
            return str(tmp_path / path.rsplit("/", 1)[1])
        return path

    monkeypatch.setattr(osti_client.os.path, "exists", lambda p: real_exists(redirect(p)))
    monkeypatch.setattr(
        "builtins.open", lambda p, *a, **k: real_open(redirect(p), *a, **k)
    )


def test_download_paper_returns_existing_local_file(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    (tmp_path / "osti_11.pdf").write_bytes(_PDF)

    with patch.object(osti_client.requests, "Session") as session_cls:
        out = osti_client.download_paper("11")

    assert out == "/tmp/osti_11.pdf"
    session_cls.assert_not_called()


def test_download_paper_served_from_cache(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    cache = FakePdfCache({"12": _PDF})

    with patch.object(osti_client.requests, "Session") as session_cls:
        out = osti_client.download_paper("12", cache=cache)

    assert out == "/tmp/osti_12.pdf"
    assert (tmp_path / "osti_12.pdf").read_bytes() == _PDF
    session_cls.assert_not_called()


def test_download_paper_fetches_and_caches_when_cache_misses(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    cache = FakePdfCache()
    resp = _resp(headers={"Content-Type": "application/pdf"}, content=_PDF)
    session = _session(resp)

    with patch.object(osti_client.requests, "Session", return_value=session):
        out = osti_client.download_paper("13", cache=cache)

    assert out == "/tmp/osti_13.pdf"
    assert (tmp_path / "osti_13.pdf").read_bytes() == _PDF
    assert cache.puts == [("13", _PDF, 30 * 24 * 3600)]
    assert session.get.call_args.args[0] == "https://www.osti.gov/servlets/purl/13"


def test_download_paper_survives_cache_read_and_write_failures(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    cache = FakePdfCache(fail_get=True, fail_put=True)
    resp = _resp(headers={"Content-Type": "application/pdf"}, content=_PDF)

    with patch.object(osti_client.requests, "Session", return_value=_session(resp)):
        out = osti_client.download_paper("14", cache=cache)

    assert out == "/tmp/osti_14.pdf"
    assert (tmp_path / "osti_14.pdf").read_bytes() == _PDF


def test_download_paper_without_cache_writes_file(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    resp = _resp(headers={"Content-Type": "application/pdf"}, content=_PDF)

    with patch.object(osti_client.requests, "Session", return_value=_session(resp)):
        out = osti_client.download_paper("15")

    assert out == "/tmp/osti_15.pdf"
    assert (tmp_path / "osti_15.pdf").read_bytes() == _PDF


def test_download_paper_rejects_non_pdf_response(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    resp = _resp(headers={"Content-Type": "text/html"}, content=b"<html>")

    with patch.object(osti_client.requests, "Session", return_value=_session(resp)):
        out = osti_client.download_paper("16")

    assert out is None
    assert not (tmp_path / "osti_16.pdf").exists()


def test_download_paper_returns_none_on_request_error(tmp_path, monkeypatch):
    _tmp_paths(monkeypatch, tmp_path)
    session = _session(raises=RuntimeError("timeout"))

    with patch.object(osti_client.requests, "Session", return_value=session):
        assert osti_client.download_paper("17") is None
