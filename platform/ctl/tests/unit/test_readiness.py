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

from platformctl import readiness


@pytest.fixture
def server():
    """A stub server; set `routes[path] = (status, body)`. Unknown paths answer 404."""
    routes: dict[str, tuple[int, bytes]] = {}

    class Handler(BaseHTTPRequestHandler):
        """Answers from `routes`."""

        def do_GET(self):  # noqa: N802
            """Answer with the route's status and body, or 404."""
            status, body = routes.get(self.path, (404, b""))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            """Keep request logs out of the test output."""

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    httpd.routes = routes
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def agents_body(*names) -> tuple[int, bytes]:
    """A `/v1/agents` route listing `names`."""
    return 200, json.dumps([{"agent_name": n} for n in names]).encode()


def agent_dir(tmp_path, name):
    """An agent directory whose `agent_card.json` has `name`."""
    folder = tmp_path / name.lower().replace(" ", "_")
    folder.mkdir()
    (folder / "agent_card.json").write_text(json.dumps({"name": name}))
    return folder


class Clock:
    """A fake clock whose `sleep` advances it, so a poll takes no real time."""

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0
        self.sleeps: list[float] = []
        """Every wait, in order."""

    def sleep(self, seconds: float) -> None:
        """Advance the clock instead of waiting."""
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        """The current fake time."""
        return self.now


def item(name, *answers):
    """A `Readiness` whose check gives these answers in turn, repeating the last."""
    given = list(answers)
    return readiness.Readiness(name, lambda: given.pop(0) if len(given) > 1 else given[0], doctor_check="docker")


def test_poll_drops_what_passes_and_stops_when_all_have():
    """Each item is tried until it passes; the run ends as soon as none is pending."""
    clock, passed = Clock(), []
    items = [item("a", "no", readiness.OK), item("b", readiness.OK)]
    failures = readiness.poll(items, 60, 5, on_ok=lambda i: passed.append(i.name), sleep=clock.sleep, clock=clock)
    assert failures == {} and passed == ["b", "a"] and clock.sleeps == [5]


def test_poll_returns_the_reason_each_item_last_gave_at_the_timeout():
    """Only what never passed is left, with its latest reason."""
    clock = Clock()
    items = [item("a", "first", "latest"), item("b", readiness.OK)]
    assert readiness.poll(items, 10, 5, sleep=clock.sleep, clock=clock) == {"a": "latest"}
    assert clock.sleeps == [5, 5]


def test_poll_tries_every_item_once_even_with_no_time():
    """A timeout of 0 is a single pass: `status` without `--wait`."""
    clock = Clock()
    assert readiness.poll([item("a", "down")], 0, 5, sleep=clock.sleep, clock=clock) == {"a": "down"}
    assert clock.sleeps == []


def test_poll_lets_a_rejected_secret_end_the_run():
    """`AuthError` is not retried."""

    def reject():
        """Fail like a registry that refuses the secret."""
        raise readiness.AuthError("rejected")

    with pytest.raises(readiness.AuthError):
        readiness.poll([readiness.Readiness("agents", reject)], 60, 5, sleep=lambda s: None)


def test_registry_name_matches_the_sdk(tmp_path):
    """The card name is lowercased with spaces as hyphens, as the SDK does."""
    assert readiness.registry_name(agent_dir(tmp_path, "Thermal Analysis Agent")) == "thermal-analysis-agent"


def test_registered_skips_malformed_entries(server):
    """Entries that aren't objects with a string `agent_name` are ignored."""
    server.routes["/v1/agents"] = (200, json.dumps([{"agent_name": "a"}, {"agent_name": None}, {}, 1, "b"]).encode())
    assert readiness.registered(server.url + "/v1/agents", "key") == {"a"}


def test_registered_rejects_a_body_that_is_not_a_list(server):
    """A body that isn't a JSON list raises `ValueError`, so it is retried."""
    server.routes["/v1/agents"] = (200, b'{"detail": "x"}')
    with pytest.raises(ValueError, match="dict"):
        readiness.registered(server.url + "/v1/agents", "key")


@pytest.mark.parametrize("status", [401, 403])
def test_registered_raises_auth_error_on_a_rejected_key(server, status):
    """A 401 or 403 raises `AuthError` instead of being retried, and the message holds no secret."""
    server.routes["/v1/agents"] = (status, b"")
    with pytest.raises(readiness.AuthError) as info:
        readiness.registered(server.url + "/v1/agents", "the-secret-key-123")
    assert "the-secret-key-123" not in str(info.value)


@pytest.mark.parametrize(("status", "text"), [(500, "HTTP 500"), (None, "backend is not answering yet")])
def test_registered_raises_value_error_on_other_failures(server, status, text):
    """Another status, or no answer at all, raises `ValueError` so it is retried."""
    url = server.url + "/v1/agents" if status else "http://127.0.0.1:1/v1/agents"
    if status:
        server.routes["/v1/agents"] = (status, b"")
    with pytest.raises(ValueError, match=text):
        readiness.registered(url, "key")


def test_agents_registered_names_the_missing_agents_then_passes(server):
    """The check names what is missing, then passes once all are listed; extra agents are fine."""
    server.routes["/v1/agents"] = agents_body("a")
    check = readiness.agents_registered(server.url + "/v1/agents", "key", {"a", "b", "c"})
    assert check() == "not registered: b, c"
    server.routes["/v1/agents"] = agents_body("a", "b", "c", "extra")
    assert check() == readiness.OK


def test_agents_registered_reports_a_failed_lookup_instead_of_raising(server):
    """A bad answer is a reason to keep waiting; a rejected key still raises."""
    server.routes["/v1/agents"] = (200, b"{}")
    check = readiness.agents_registered(server.url + "/v1/agents", "key", {"a"})
    assert "unexpected /v1/agents response" in check()
    server.routes["/v1/agents"] = (401, b"")
    with pytest.raises(readiness.AuthError):
        check()


def test_http_ok_passes_on_2xx_and_says_what_else_it_saw(server):
    """200 passes, 404 says `HTTP 404`, and nothing listening says `no answer`."""
    server.routes["/ok"] = (200, b"ok")
    assert readiness.http_ok(server.url + "/ok")() == readiness.OK
    assert readiness.http_ok(server.url + "/missing")() == "HTTP 404"
    assert readiness.http_ok("http://127.0.0.1:1/")() == "no answer"
