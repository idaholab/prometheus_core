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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from platformctl.system.deeplynx import INTERNAL_URL, ORG_ID, PROJECT_NAME, DeepLynx, DeepLynxError

API = "/api/v1"
"""The path prefix of the API."""


class StubDeepLynx(ThreadingHTTPServer):
    """The parts of the DeepLynx API the adapter uses, with an in-memory state."""

    def __init__(self):
        """Start healthy, with no projects or keys."""
        super().__init__(("127.0.0.1", 0), StubHandler)
        self.port = self.server_address[1]
        self.healthy = True
        self.projects: list[dict] = []
        self.keys: dict[str, str] = {}
        self.fail: dict[str, int] = {}
        """Status to answer instead, by "METHOD path"."""
        self.requests: list[str] = []
        """Every "METHOD path" received, in order."""

    @property
    def api(self) -> str:
        """The API base URL, as the adapter is given it."""
        return f"http://127.0.0.1:{self.port}{API}"


class StubHandler(BaseHTTPRequestHandler):
    """Answers the stub's routes from its state."""

    server: StubDeepLynx
    """The stub whose state this handler serves."""

    def _reply(self, status: int, body: object = None):
        """Send `body` as JSON with `status`."""
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def _route(self, method: str):
        """Dispatch a request to the matching route, or 404."""
        stub = self.server
        path = self.path.removeprefix(API)
        stub.requests.append(f"{method} {path}")
        # Read the body before any reply, or a forced failure resets the connection mid-send.
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        if status := stub.fail.get(f"{method} {path}"):
            return self._reply(status)
        projects = f"/organizations/{ORG_ID}/projects"

        if method == "GET" and path == "/health":
            return self._reply(200, {"status": "healthy"}) if stub.healthy else self._reply(503)
        if method == "GET" and path == projects:
            return self._reply(200, stub.projects)
        if method == "POST" and path == projects:
            project = {"id": len(stub.projects) + 1, "name": body["name"], "isArchived": False}
            stub.projects.append(project)
            return self._reply(200, project)
        if method == "GET" and path.startswith(f"{projects}/"):
            pid = path.rsplit("/", 1)[1]
            if any(str(p["id"]) == pid for p in stub.projects):
                return self._reply(200, {"id": int(pid)})
            return self._reply(400)
        if method == "POST" and path == "/oauth/keys":
            key = f"key{len(stub.keys) + 1}"
            stub.keys[key] = f"secret{len(stub.keys) + 1}"
            return self._reply(200, {"apiKey": key, "apiSecret": stub.keys[key]})
        if method == "POST" and path == "/oauth/tokens":
            if stub.keys.get(body["apiKey"]) == body["apiSecret"]:
                return self._reply(200, "token")
            return self._reply(404)
        return self._reply(404)

    def do_GET(self):  # noqa: N802
        """Handle a GET."""
        self._route("GET")

    def do_POST(self):  # noqa: N802
        """Handle a POST."""
        self._route("POST")

    def log_message(self, *args):
        """Keep request logs out of the test output."""


@pytest.fixture
def stub():
    """A running `StubDeepLynx`."""
    server = StubDeepLynx()
    # A short poll interval keeps shutdown() from waiting the default 0.5s
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def dl(stub) -> DeepLynx:
    """The adapter pointed at the stub."""
    return DeepLynx(stub.api)


def test_the_trailing_slash_of_the_base_url_is_dropped():
    """`http://h/api/v1/` and `http://h/api/v1` are the same API."""
    assert DeepLynx("http://h/api/v1/").api == "http://h/api/v1"


def test_wait_healthy(dl):
    """True once the server reports healthy."""
    assert dl.wait_healthy(1, 0)


def test_wait_healthy_polls_until_the_server_comes_up(stub, dl):
    """Not-yet-healthy answers are retried, sleeping between them."""
    stub.healthy = False
    sleeps = []

    def sleep(seconds):
        """Record the wait, and come up after the second one."""
        sleeps.append(seconds)
        stub.healthy = len(sleeps) >= 2

    assert dl.wait_healthy(60, 2, sleep=sleep)
    assert sleeps == [2, 2]


def test_wait_healthy_times_out(stub, dl):
    """False when the server never reports healthy."""
    stub.healthy = False
    ticks = iter([0.0, 1.0, 5.0])
    assert not dl.wait_healthy(3, 1, sleep=lambda _: None, clock=lambda: next(ticks))


def test_wait_healthy_without_a_server():
    """False when nothing listens, instead of raising."""
    assert not DeepLynx("http://127.0.0.1:9/api/v1").wait_healthy(0, 0)


def test_find_or_create_project_creates_one(stub, dl):
    """With no matching project, one named `PROJECT_NAME` is created."""
    assert dl.find_or_create_project() == (1, True)
    assert stub.projects[0]["name"] == PROJECT_NAME


def test_find_or_create_project_reuses_one(stub, dl):
    """An existing project with the name is reused, skipping archived ones."""
    stub.projects = [
        {"id": 1, "name": "Other", "isArchived": False},
        {"id": 2, "name": PROJECT_NAME, "isArchived": True},
        {"id": 3, "name": PROJECT_NAME, "isArchived": False},
    ]
    assert dl.find_or_create_project() == (3, False)
    assert f"POST /organizations/{ORG_ID}/projects" not in stub.requests


@pytest.mark.parametrize("route", ["GET", "POST"])
def test_find_or_create_project_raises_on_errors(stub, dl, route):
    """A failed list or create raises, naming the status."""
    stub.fail[f"{route} /organizations/{ORG_ID}/projects"] = 500
    with pytest.raises(DeepLynxError, match="HTTP 500"):
        dl.find_or_create_project()


def test_create_key(dl):
    """Returns the new key and secret."""
    assert dl.create_key() == ("key1", "secret1")


def test_create_key_raises_on_errors_without_the_body(stub, dl):
    """A failed request raises, naming the status."""
    stub.fail["POST /oauth/keys"] = 500
    with pytest.raises(DeepLynxError, match="HTTP 500"):
        dl.create_key()


def test_an_unanswered_request_says_so():
    """No answer at all is not `HTTP None`."""
    with pytest.raises(DeepLynxError, match="no answer"):
        DeepLynx("http://127.0.0.1:9/api/v1").create_key()


def configured_env(stub, **overrides) -> dict[str, str]:
    """Settings for a valid key and project on the stub, with `overrides`."""
    stub.projects = [{"id": 1, "name": PROJECT_NAME, "isArchived": False}]
    stub.keys = {"key1": "secret1"}
    env = {
        "DEEPLYNX_BASE_URL": INTERNAL_URL,
        "DEEPLYNX_KEY": "key1",
        "DEEPLYNX_SECRET": "secret1",
        "DEEPLYNX_PROJECT_ID": "1",
    }
    return {**env, **overrides}


def test_configured(stub, dl):
    """True for this server's URL, a key it accepts and a project that exists; a trailing slash is the same URL."""
    assert dl.configured(configured_env(stub))
    assert dl.configured(configured_env(stub, DEEPLYNX_BASE_URL=INTERNAL_URL + "/"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"DEEPLYNX_BASE_URL": "https://deeplynx.example.com/api/v1"},
        {"DEEPLYNX_KEY": ""},
        {"DEEPLYNX_SECRET": "wrong"},
        {"DEEPLYNX_PROJECT_ID": "2"},
    ],
    ids=["other server", "no key", "rejected key", "missing project"],
)
def test_not_configured(stub, dl, overrides):
    """False when any part of the settings doesn't work on this server."""
    assert not dl.configured(configured_env(stub, **overrides))
