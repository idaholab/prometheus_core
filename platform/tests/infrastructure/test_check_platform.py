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

"""Unit tests for scripts/check_platform.py against a local stub HTTP server."""

import importlib.util
import json
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load_check_platform():
    """Import scripts/check_platform.py as a module."""
    # The script imports init_env by name, as running it from scripts/ allows
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("check_platform", SCRIPTS / "check_platform.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cp = _load_check_platform()


@pytest.fixture
def server():
    """A stub server; set ``routes[path] = (status, body)``. Unknown paths answer 404."""
    routes: dict[str, tuple[int, bytes]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            """Answer with the route's status and body, or 404."""
            status, body = routes.get(self.path, (404, b""))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            """Keep request logs out of the test output."""

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # A short poll interval keeps shutdown() from waiting the default 0.5s
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    httpd.routes = routes
    httpd.port = httpd.server_address[1]
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _agents(*names):
    """Return a /v1/agents route listing ``names``."""
    return 200, json.dumps([{"agent_name": n} for n in names]).encode()


def _agent_dir(tmp_path, name):
    """Create an agent directory whose agent_card.json has ``name``."""
    d = tmp_path / name.lower().replace(" ", "_")
    d.mkdir()
    (d / "agent_card.json").write_text(json.dumps({"name": name}))
    return d


def _run_main(monkeypatch, *args):
    """Run main() with ``args`` and no wait between polls; return its exit code."""
    monkeypatch.setattr(sys, "argv", ["check_platform.py", "--interval", "0", *args])
    return cp.main()


def test_registry_name_matches_the_sdk(tmp_path):
    """The card name is lowercased with spaces as hyphens, as the SDK does."""
    assert cp.registry_name(_agent_dir(tmp_path, "Thermal Analysis Agent")) == "thermal-analysis-agent"


def test_env_value_prefers_environment_then_env_file(tmp_path, monkeypatch):
    """The environment wins over .env, and a blank value falls through to the default."""
    env = tmp_path / ".env"
    env.write_text("FROM_FILE=file\nBOTH=file\nBLANK=\n")
    monkeypatch.setattr(cp, "ENV", env)
    monkeypatch.setenv("BOTH", "environ")
    monkeypatch.delenv("FROM_FILE", raising=False)
    monkeypatch.delenv("BLANK", raising=False)
    assert cp.env_value("BOTH") == "environ"
    assert cp.env_value("FROM_FILE") == "file"
    assert cp.env_value("BLANK", "default") == "default"
    assert cp.env_value("MISSING") is None


def test_env_value_without_env_file(tmp_path, monkeypatch):
    """With no .env, an unset variable returns the default."""
    monkeypatch.setattr(cp, "ENV", tmp_path / "missing.env")
    monkeypatch.delenv("MISSING", raising=False)
    assert cp.env_value("MISSING", "default") == "default"


def test_registered_skips_malformed_entries(server):
    """Entries that aren't objects with a string agent_name are ignored."""
    server.routes["/v1/agents"] = (200, json.dumps([{"agent_name": "a"}, {"agent_name": None}, {}, 1, "b"]).encode())
    assert cp.registered(f"http://127.0.0.1:{server.port}/v1/agents", "key") == {"a"}


def test_registered_rejects_a_non_list_body(server):
    """A body that isn't a JSON list raises ValueError, so it is retried."""
    server.routes["/v1/agents"] = (200, b'{"detail": "x"}')
    with pytest.raises(ValueError, match="dict"):
        cp.registered(f"http://127.0.0.1:{server.port}/v1/agents", "key")


@pytest.mark.parametrize("status", [401, 403])
def test_registered_raises_auth_error_on_a_rejected_key(server, status):
    """A 401 or 403 raises AuthError instead of being retried."""
    server.routes["/v1/agents"] = (status, b"")
    with pytest.raises(cp.AuthError):
        cp.registered(f"http://127.0.0.1:{server.port}/v1/agents", "key")


def test_registered_raises_http_error_on_other_statuses(server):
    """Other error statuses raise HTTPError, so they are retried."""
    server.routes["/v1/agents"] = (500, b"")
    with pytest.raises(urllib.error.HTTPError):
        cp.registered(f"http://127.0.0.1:{server.port}/v1/agents", "key")


def test_agents_check_reports_missing_agents(server):
    """The check names the missing agents, then passes once all are listed; extra agents are fine."""
    server.routes["/v1/agents"] = _agents("a")
    check = cp.agents_check(f"http://127.0.0.1:{server.port}/v1/agents", "key", {"a", "b", "c"})
    assert check() == "not registered: b, c"
    server.routes["/v1/agents"] = _agents("a", "b", "c", "extra")
    assert check() is None


def test_http_check_passes_on_2xx_and_raises_otherwise(server):
    """The check passes on a 200 and raises on a 404."""
    server.routes["/ok"] = (200, b"ok")
    assert cp.http_check(f"http://127.0.0.1:{server.port}/ok")() is None
    with pytest.raises(urllib.error.HTTPError):
        cp.http_check(f"http://127.0.0.1:{server.port}/missing")()


def test_main_passes_when_everything_is_up(server, tmp_path, monkeypatch, capsys):
    """Exits 0 once the backend, frontend, proxy and agents all pass."""
    monkeypatch.setenv("AGENT_SECRET", "key")
    server.routes.update(
        {
            "/healthz": (200, b"ok"),
            "/": (200, b"<html>"),
            "/api/setup/status": (200, b"{}"),
            "/v1/agents": _agents("client-agent"),
        }
    )
    port = str(server.port)
    rc = _run_main(
        monkeypatch,
        "--backend-port", port, "--frontend-port", port,
        str(_agent_dir(tmp_path, "Client Agent")),
    )  # fmt: skip
    assert rc == 0
    assert "The platform is up." in capsys.readouterr().out


def test_main_skips_the_frontend_and_agents_when_not_given(server, monkeypatch):
    """Without --frontend-port or agents, only the backend is checked and no agent secret is needed."""
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    server.routes["/healthz"] = (200, b"ok")
    port = str(server.port)
    assert _run_main(monkeypatch, "--backend-port", port) == 0


def test_main_times_out_and_names_what_failed(server, tmp_path, monkeypatch, capsys):
    """On a timeout, exits 1 and lists only the checks that never passed."""
    monkeypatch.setenv("AGENT_SECRET", "key")
    server.routes.update({"/": (200, b"<html>"), "/api/setup/status": (502, b""), "/v1/agents": _agents()})
    port = str(server.port)
    rc = _run_main(
        monkeypatch,
        "--timeout", "0",
        "--backend-port", port, "--frontend-port", port,
        str(_agent_dir(tmp_path, "Client Agent")),
    )  # fmt: skip
    assert rc == 1
    err = capsys.readouterr().err
    assert "backend: HTTP Error 404" in err
    assert "frontend /api proxy: HTTP Error 502" in err
    assert "not registered: client-agent" in err
    assert "  frontend:" not in err


def test_main_fails_fast_on_a_rejected_agent_secret(server, tmp_path, monkeypatch, capsys):
    """A rejected key exits 1 on the first poll, not at the timeout."""
    monkeypatch.setenv("AGENT_SECRET", "wrong")
    server.routes.update({"/healthz": (200, b"ok"), "/v1/agents": (401, b"")})
    port = str(server.port)
    start = time.monotonic()
    rc = _run_main(
        monkeypatch,
        "--timeout", "5",
        "--backend-port", port,
        str(_agent_dir(tmp_path, "Client Agent")),
    )  # fmt: skip
    assert rc == 1
    assert "rejected AGENT_SECRET" in capsys.readouterr().err
    assert time.monotonic() - start < 5, "should exit on the first poll, not wait out the timeout"


def test_main_requires_the_agent_secret_for_agents(tmp_path, monkeypatch, capsys):
    """With agents to check and no AGENT_SECRET, exits 1 at once."""
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    monkeypatch.setattr(cp, "ENV", tmp_path / "missing.env")
    rc = _run_main(monkeypatch, "--backend-port", "1", str(_agent_dir(tmp_path, "Client Agent")))
    assert rc == 1
    assert "AGENT_SECRET is not set" in capsys.readouterr().err
