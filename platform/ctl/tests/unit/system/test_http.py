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

import json
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


class JsonHandler(BaseHTTPRequestHandler):
    """A server that echoes the request body and headers it was sent, as JSON, or answers oddly by path."""

    def _answer(self):
        """Answer by path: `/empty` has no body, `/text` is not JSON, `/missing` is a 404, else an echo."""
        length = int(self.headers.get("Content-Length") or 0)
        sent = self.rfile.read(length).decode() if length else ""
        if self.path == "/empty":
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/text":
            body = b"not json"
        else:
            body = json.dumps(
                {"method": self.command, "sent": sent, "auth": self.headers.get("Authorization")}
            ).encode()
        self.send_response(404 if self.path == "/missing" else 200)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        """Answer a GET."""
        self._answer()

    def do_POST(self):  # noqa: N802
        """Answer a POST."""
        self._answer()

    def log_message(self, *_):
        """Stay quiet."""


@pytest.fixture
def json_server():
    """A local server for the JSON helper, stopped afterwards."""
    srv = HTTPServer(("127.0.0.1", 0), JsonHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_request_json_sends_the_body_and_headers_and_decodes_the_reply(json_server):
    """The JSON body goes out, the headers go with it, and the reply is decoded."""
    code, body = http.request_json("POST", json_server + "/x", {"a": 1}, headers={"Authorization": "Bearer t"})
    assert code == 200
    assert body == {"method": "POST", "sent": '{"a": 1}', "auth": "Bearer t"}


def test_request_json_with_no_body_sends_none(json_server):
    """A GET has no body."""
    assert http.request_json("GET", json_server + "/x") == (200, {"method": "GET", "sent": "", "auth": None})


def test_request_json_returns_error_statuses_with_their_body(json_server):
    """An HTTP error is a status, not an exception."""
    code, body = http.request_json("GET", json_server + "/missing")
    assert code == 404 and body["method"] == "GET"


def test_request_json_empty_and_non_json_bodies_are_none(json_server):
    """An empty reply and one that isn't JSON both decode to None, keeping the status."""
    assert http.request_json("GET", json_server + "/empty") == (204, None)
    assert http.request_json("GET", json_server + "/text") == (200, None)


def test_request_json_with_nothing_listening_has_no_status():
    """No answer is `(None, None)`, not an exception."""
    assert http.request_json("GET", "http://127.0.0.1:1/") == (None, None)
    assert http.request_json("GET", "not a url") == (None, None)


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
