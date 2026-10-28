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

"""The generalized URL downloader accepts real PDFs and rejects
HTML error pages, oversized bodies, and failed requests - without raising."""

from unittest.mock import MagicMock, patch

from research_agent import osti_client

_PDF_BYTES = b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n... body ..."


def _session(status_code=200, headers=None, content=b"", raises=None):
    """A fake requests.Session whose .get returns a canned response (or raises)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.content = content

    session = MagicMock()
    if raises is not None:
        session.get.side_effect = raises
    else:
        session.get.return_value = resp
    return session


def _patch_session(session):
    # download_pdf_from_url calls requests.Session().get(...)
    return patch.object(osti_client.requests, "Session", return_value=session)


def test_accepts_pdf_by_content_type(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(headers={"Content-Type": "application/pdf"}, content=_PDF_BYTES)
    with _patch_session(session):
        out = osti_client.download_pdf_from_url("https://x/p.pdf", dest)
    assert out == dest
    assert (tmp_path / "p.pdf").read_bytes() == _PDF_BYTES


def test_accepts_pdf_by_magic_bytes_when_content_type_missing(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(
        headers={"Content-Type": "application/octet-stream"}, content=_PDF_BYTES
    )
    with _patch_session(session):
        out = osti_client.download_pdf_from_url("https://x/p", dest)
    assert out == dest


def test_rejects_html_page(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(
        headers={"Content-Type": "text/html"}, content=b"<html>nope</html>"
    )
    with _patch_session(session):
        out = osti_client.download_pdf_from_url("https://x/notpdf", dest)
    assert out is None
    assert not (tmp_path / "p.pdf").exists()


def test_rejects_oversized_by_content_length(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(
        headers={
            "Content-Type": "application/pdf",
            "Content-Length": str(100 * 1024 * 1024),
        },
        content=_PDF_BYTES,
    )
    with _patch_session(session):
        out = osti_client.download_pdf_from_url(
            "https://x/big.pdf", dest, max_bytes=50 * 1024 * 1024
        )
    assert out is None


def test_rejects_oversized_by_body_length(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(
        headers={"Content-Type": "application/pdf"}, content=b"%PDF" + b"x" * 5000
    )
    with _patch_session(session):
        out = osti_client.download_pdf_from_url(
            "https://x/big.pdf", dest, max_bytes=1000
        )
    assert out is None


def test_non_200_returns_none(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(
        status_code=404, headers={"Content-Type": "application/pdf"}, content=_PDF_BYTES
    )
    with _patch_session(session):
        out = osti_client.download_pdf_from_url("https://x/missing.pdf", dest)
    assert out is None


def test_request_exception_returns_none(tmp_path):
    dest = str(tmp_path / "p.pdf")
    session = _session(raises=OSError("connection reset"))
    with _patch_session(session):
        out = osti_client.download_pdf_from_url("https://x/p.pdf", dest)
    assert out is None


class _FakePdfCache:
    def __init__(self, blobs=None, fail=False):
        self.blobs = dict(blobs or {})
        self.fail = fail
        self.puts = []

    def get_pdf(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.blobs.get(key)

    def put_pdf(self, key, data, ttl_s):
        if self.fail:
            raise ConnectionError("redis down")
        self.puts.append((key, ttl_s))
        self.blobs[key] = data


def test_fetched_pdf_is_cached_by_url(tmp_path):
    cache = _FakePdfCache()
    session = _session(headers={"Content-Type": "application/pdf"}, content=_PDF_BYTES)
    with _patch_session(session):
        out = osti_client.download_pdf_from_url(
            "https://x/p.pdf", str(tmp_path / "p.pdf"), cache=cache
        )

    key = osti_client.url_cache_key("https://x/p.pdf")
    assert out and cache.blobs[key] == _PDF_BYTES
    assert key.startswith("url:") and cache.puts[0][1] == 30 * 24 * 3600


def test_cached_pdf_is_served_without_a_request(tmp_path):
    key = osti_client.url_cache_key("https://x/p.pdf")
    cache = _FakePdfCache({key: _PDF_BYTES})
    dest = tmp_path / "p.pdf"
    session = _session(raises=AssertionError("must not fetch"))
    with _patch_session(session):
        out = osti_client.download_pdf_from_url("https://x/p.pdf", str(dest), cache=cache)

    assert out == str(dest) and dest.read_bytes() == _PDF_BYTES
    session.get.assert_not_called()


def test_different_urls_never_share_a_cache_entry():
    assert osti_client.url_cache_key("https://a/p.pdf") != osti_client.url_cache_key(
        "https://b/p.pdf"
    )


def test_rejected_download_is_not_cached(tmp_path):
    cache = _FakePdfCache()
    session = _session(headers={"Content-Type": "text/html"}, content=b"<html>")
    with _patch_session(session):
        out = osti_client.download_pdf_from_url(
            "https://x/notpdf", str(tmp_path / "p.pdf"), cache=cache
        )

    assert out is None and cache.blobs == {}


def test_cache_outage_still_downloads(tmp_path):
    session = _session(headers={"Content-Type": "application/pdf"}, content=_PDF_BYTES)
    with _patch_session(session):
        out = osti_client.download_pdf_from_url(
            "https://x/p.pdf", str(tmp_path / "p.pdf"), cache=_FakePdfCache(fail=True)
        )

    assert out is not None
