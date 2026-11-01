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

import argparse
import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from platformctl.actions import status
from tests.unit.conftest import assert_golden, make_context
from tests.unit.test_readiness import Clock

SECRET = "agent-secret-value-123"
"""The `AGENT_SECRET` the tests use."""


@pytest.fixture
def server():
    """A stub platform; set `routes[path] = (status, body)`. Unknown paths answer 404."""
    routes: dict[str, tuple[int, bytes]] = {}

    class Handler(BaseHTTPRequestHandler):
        """Answers from `routes`."""

        def do_GET(self):  # noqa: N802
            """Answer with the route's status and body, or 404."""
            code, body = routes.get(self.path, (404, b""))
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            """Keep request logs out of the test output."""

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    httpd.routes = routes
    httpd.port = httpd.server_address[1]
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def agents(*names) -> tuple[int, bytes]:
    """A `/v1/agents` route listing `names`."""
    return 200, json.dumps([{"agent_name": n} for n in names]).encode()


@pytest.fixture
def ctx_for(platform_root, runner, server):
    """A context factory for a platform whose ports all point at the stub, with a client agent card."""
    (platform_root / "agents" / "client-agent" / "agent_card.json").write_text(json.dumps({"name": "Client Agent"}))
    (platform_root / ".env").write_text(f"AGENT_SECRET={SECRET}\n")
    port = str(server.port)

    def factory(env=None, **kw):
        """Build the context; `PROFILE` defaults to none, so only the backend and registry are checked."""
        base = {"PATH": "/usr/bin", "BACKEND_PORT": port, "FRONTEND_DEV_PORT": port, "FRONTEND_PROD_PORT": port}
        return make_context(platform_root, runner, {**base, "PROFILE": "", **(env or {})}, **kw)

    return factory


def ns(wait=False, timeout=None) -> argparse.Namespace:
    """The parsed arguments of `status`."""
    return argparse.Namespace(wait=wait, timeout=timeout)


def healthy(server, *registered):
    """Make the stub answer like a healthy platform with these agents registered."""
    server.routes.update(
        {
            "/healthz": (200, b"ok"),
            "/": (200, b"<html>"),
            "/api/setup/status": (200, b"{}"),
            "/v1/agents": agents(*registered),
        }
    )


def test_status_passes_once_when_everything_is_up(ctx_for, server):
    """One check, no waiting: the lines `make check` printed, then success."""
    healthy(server, "client-agent")
    ctx, out, err = ctx_for()
    assert status.run(ctx, ns()) == 0
    assert out.getvalue().splitlines() == [
        "  [OK] backend",
        "  [OK] 1 agent(s) registered",
        "The platform is up.",
    ]
    assert SECRET not in out.getvalue() + err.getvalue()


def test_wait_says_what_it_waits_for_before_it_starts(ctx_for, server):
    """`--wait` lists the checks and the time allowed first."""
    healthy(server, "client-agent")
    ctx, out, _ = ctx_for({"PROFILE": "dev"})
    assert status.run(ctx, ns(wait=True, timeout=30)) == 0
    assert out.getvalue().splitlines()[:4] == [
        "Waiting up to 30s for the platform:",
        "  backend",
        "  frontend",
        "  frontend /api proxy",
    ]


@pytest.mark.parametrize(("profile", "checked"), [("dev", True), ("prod", True), ("", False)])
def test_the_frontend_is_checked_only_when_a_profile_selects_one(ctx_for, server, profile, checked):
    """`PROFILE=dev|prod` adds the frontend and its proxy; no profile checks the backend only."""
    healthy(server, "client-agent")
    ctx, out, _ = ctx_for({"PROFILE": profile})
    assert status.run(ctx, ns()) == 0
    assert ("[OK] frontend /api proxy" in out.getvalue()) is checked


def test_wait_polls_until_the_agents_register(ctx_for, server):
    """Not-yet-registered agents are waited for, and the wait is bounded by the timeout."""
    healthy(server, "client-agent")
    registered = [agents("client-agent"), agents("client-agent", "corrosion-agent")]
    ctx, out, _ = ctx_for()
    (ctx.paths.root / "docker-compose.agents.yml").write_text(
        "include:\n  - agents/corrosion-agent/docker-compose.yml\n"
    )
    (ctx.paths.root / "agents" / "corrosion-agent").mkdir()
    (ctx.paths.root / "agents" / "corrosion-agent" / "agent_card.json").write_text(
        json.dumps({"name": "Corrosion Agent"})
    )
    clock = Clock()

    def sleep(seconds):
        """Register the second agent during the first wait."""
        server.routes["/v1/agents"] = registered[1]
        clock.sleep(seconds)

    server.routes["/v1/agents"] = registered[0]
    assert status.run(ctx, ns(wait=True, timeout=60), sleep=sleep, clock=clock) == 0
    assert "[OK] 2 agent(s) registered" in out.getvalue()
    assert clock.sleeps == [5]


def test_timeout_names_what_is_missing_and_the_doctor_check_for_it(ctx_for, server):
    """After the timeout: each reason, and the `doctor` checks that explain them."""
    server.routes["/v1/agents"] = agents()
    ctx, out, err = ctx_for()
    clock = Clock()
    assert status.run(ctx, ns(wait=True, timeout=10), sleep=clock.sleep, clock=clock) == 1
    text = err.getvalue()
    assert "[ERROR] Not ready after 10s:" in text
    assert "  backend: HTTP 404" in text
    assert "  1 agent(s) registered: not registered: client-agent" in text
    assert "Run: ./platformctl doctor platform-env ports-free" in text
    assert clock.sleeps == [5, 5]


def test_a_failure_says_how_to_see_whether_it_is_running(ctx_for, server):
    """A person who sees "Not ready" is told where to look, in words that don't need to know what a registry is."""
    server.routes["/v1/agents"] = agents()
    ctx, _, err = ctx_for()
    assert status.run(ctx, ns()) == 1
    assert "Is it running? `make ps` lists the services; `make logs` shows what they say." in err.getvalue()


def test_a_failure_without_a_doctor_check_prints_no_run_line(ctx_for, server, monkeypatch):
    """When no failing item has a `doctor` check to suggest, the hint line is left out."""
    server.routes["/v1/agents"] = agents("client-agent")
    ctx, _, err = ctx_for()
    original = status.build_items
    monkeypatch.setattr(status, "build_items", lambda context: [replace(i, doctor_check="") for i in original(context)])
    assert status.run(ctx, ns()) == 1
    assert "HTTP 404" in err.getvalue() and "Run:" not in err.getvalue()


def test_timeout_as_json_is_one_object_with_a_timeout_error(ctx_for, server):
    """A skill gets the same facts as an object, pinned by a golden file."""
    server.routes["/v1/agents"] = agents()
    ctx, out, _ = ctx_for(json_mode=True)
    clock = Clock()
    assert status.run(ctx, ns(wait=True, timeout=0), sleep=clock.sleep, clock=clock) == 1
    body = json.loads(out.getvalue())
    assert body["ok"] is False and body["error"]["code"] == "timeout"
    assert [w["name"] for w in body["waiting_for"]] == ["backend", "1 agent(s) registered"]
    assert_golden("status_timeout", body, ctx.paths.root)


def test_one_check_that_fails_is_not_a_timeout(ctx_for, server):
    """Without `--wait` nothing waited, so the error is `check_failed` and the text doesn't say "after 0s"."""
    server.routes["/v1/agents"] = agents()
    ctx, out, _ = ctx_for(json_mode=True)
    assert status.run(ctx, ns()) == 1
    body = json.loads(out.getvalue())
    assert body["error"]["code"] == "check_failed"
    assert body["error"]["message"].startswith("Not ready: ")
    assert "after 0s" not in out.getvalue()
    ctx, _, err = ctx_for()
    assert status.run(ctx, ns()) == 1
    assert "[ERROR] Not ready:" in err.getvalue() and "after 0s" not in err.getvalue()


def test_ready_as_json(ctx_for, server):
    """A ready platform is `ready: true` with the checks that passed."""
    healthy(server, "client-agent")
    ctx, out, _ = ctx_for(json_mode=True)
    assert status.run(ctx, ns()) == 0
    body = json.loads(out.getvalue())
    assert body["ok"] is True and body["ready"] is True and body["checks"] == ["backend", "1 agent(s) registered"]
    assert_golden("status_ready", body, ctx.paths.root)


def test_a_rejected_agent_secret_ends_the_run_at_once(ctx_for, server):
    """A 401 is not retried until the timeout, and the message never carries the secret."""
    server.routes.update({"/healthz": (200, b"ok"), "/v1/agents": (401, b"")})
    ctx, _, err = ctx_for()
    clock = Clock()
    assert status.run(ctx, ns(wait=True, timeout=300), sleep=clock.sleep, clock=clock) == 1
    assert "rejected AGENT_SECRET" in err.getvalue() and SECRET not in err.getvalue()
    assert clock.sleeps == []


def test_a_rejected_agent_secret_as_json(ctx_for, server):
    """The same failure as an object with a stable code."""
    server.routes.update({"/healthz": (200, b"ok"), "/v1/agents": (403, b"")})
    ctx, out, _ = ctx_for(json_mode=True)
    assert status.run(ctx, ns()) == 1
    assert json.loads(out.getvalue())["error"]["code"] == "check_failed"


def test_without_an_agent_secret_it_says_to_run_config_init(platform_root, runner):
    """The registry can't be asked without `AGENT_SECRET`."""
    ctx, _, err = make_context(platform_root, runner, {"PATH": "/usr/bin", "PROFILE": ""})
    assert status.run(ctx, ns()) == 1
    assert "AGENT_SECRET is not set in the environment or" in err.getvalue()
    assert "./platformctl config init" in err.getvalue()


def test_the_default_timeout_is_check_timeout(ctx_for, server):
    """`--wait` without `--timeout` waits `CHECK_TIMEOUT` seconds."""
    healthy(server, "client-agent")
    ctx, out, _ = ctx_for({"CHECK_TIMEOUT": "42"})
    assert status.run(ctx, ns(wait=True)) == 0
    assert out.getvalue().startswith("Waiting up to 42s for the platform:")


def test_waiting_reports_the_time_left_in_verbose_mode(ctx_for, server):
    """Between polls, `--verbose` shows how long is left."""
    server.routes["/healthz"] = (200, b"ok")
    server.routes["/v1/agents"] = agents()
    ctx, _, err = ctx_for()
    ctx.output.verbose = True
    clock = Clock()
    status.run(ctx, ns(wait=True, timeout=10), sleep=clock.sleep, clock=clock)
    assert "waiting, 10s left" in err.getvalue()


def test_a_client_agent_without_a_card_is_not_expected(platform_root, runner, server):
    """A folder with no `agent_card.json` has no registry name, so it is skipped rather than crashing."""
    (platform_root / ".env").write_text(f"AGENT_SECRET={SECRET}\n")
    server.routes.update({"/healthz": (200, b"ok"), "/v1/agents": agents()})
    env = {"PATH": "/usr/bin", "PROFILE": "", "BACKEND_PORT": str(server.port)}
    ctx, out, _ = make_context(platform_root, runner, env)
    assert status.run(ctx, ns()) == 0
    assert "[OK] 0 agent(s) registered" in out.getvalue()
