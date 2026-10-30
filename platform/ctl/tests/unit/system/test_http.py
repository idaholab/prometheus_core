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

from __future__ import annotations

import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from platformctl.system import http


class Handler(BaseHTTPRequestHandler):
    """A server handler that answers 200, or 404 for `/missing`."""

    def do_GET(self):  # noqa: N802
        """Answer a GET."""
        code = 404 if self.path == "/missing" else 200
        self.send_response(code)
        self.end_headers()

    def log_message(self, *_):
        """Stay quiet."""
        pass


@pytest.fixture
def server():
    """A local HTTP server for the test, stopped afterwards."""
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_status(server):
    """`status` returns the HTTP status, including error statuses."""
    assert http.status(server + "/") == 200
    assert http.status(server + "/missing") == 404


def test_status_nothing_listening_and_bad_url():
    """Status nothing listening and bad url."""
    assert http.status("http://127.0.0.1:1/") is None
    assert http.status("not a url") is None


def test_loopback_bypasses_the_proxy(server, monkeypatch):
    """A loopback URL ignores `HTTP_PROXY`."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    assert http.status(server + "/") == 200


def test_non_loopback_uses_the_default_opener(monkeypatch):
    """Non loopback uses the default opener."""
    seen = []

    class Opener:
        def open(self, request, timeout):
            """Record the URL and fail like an unreachable network."""
            seen.append(request.full_url)
            raise urllib.error.URLError("no network")

    monkeypatch.setattr(http.urllib.request, "build_opener", lambda *handlers: Opener() if not handlers else None)
    assert http.status("http://example.invalid/x") is None
    assert seen == ["http://example.invalid/x"]


def test_wait_succeeds_immediately(server):
    """`wait` returns True as soon as the URL answers."""
    assert http.wait(server + "/", 5)


def test_wait_polls_until_the_deadline():
    """Wait polls until the deadline."""
    now = [0.0]
    slept = []

    def clock():
        """The fake clock."""
        return now[0]

    def sleep(seconds):
        """Advance the fake clock instead of sleeping."""
        slept.append(seconds)
        now[0] += seconds

    assert not http.wait("http://127.0.0.1:1/", 3, interval=1, sleep=sleep, clock=clock)
    assert slept == [1, 1, 1]


def test_wait_uses_the_ok_predicate(server):
    """Wait uses the ok predicate."""
    assert not http.wait(server + "/missing", 0, ok=lambda code: code == 200)
    assert http.wait(server + "/missing", 0, ok=lambda code: code == 404)
