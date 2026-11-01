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

import pytest

from platformctl.actions import deeplynx
from platformctl.system import envfile
from platformctl.system.deeplynx import INTERNAL_URL, ORG_ID, PROJECT_NAME
from tests.unit.conftest import make_context
from tests.unit.system.test_deeplynx import StubDeepLynx

ENV = (
    "OTHER=kept\nLOCAL_DEEPLYNX=true\n"
    "DEEPLYNX_BASE_URL=https://deeplynx.example.com/api/v1\nDEEPLYNX_KEY=\nDEEPLYNX_SECRET=\n"
    "DEEPLYNX_JWT_TOKEN=old-token\nDEEPLYNX_ORG_ID=\nDEEPLYNX_PROJECT_ID=\n"
)
"""A `.env` with DeepLynx settings for another server."""


@pytest.fixture
def stub():
    """A running stub DeepLynx."""
    server = StubDeepLynx()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def ctx_for(platform_root, runner, stub):
    """A context factory whose DeepLynx port is the stub's."""
    (platform_root / ".env").write_text(ENV)

    def factory(env=None, **kw):
        """Build the context."""
        base = {"PATH": "/usr/bin", "DEEPLYNX_SERVER_PORT": str(stub.port), "DEEPLYNX_UI_PORT": "3456"}
        return make_context(platform_root, runner, {**base, **(env or {})}, **kw)

    return factory


def ns(timeout=0.3, no_start=True) -> argparse.Namespace:
    """The parsed arguments of `deeplynx setup`."""
    return argparse.Namespace(timeout=timeout, no_start=no_start)


@pytest.fixture(autouse=True)
def ipv4_localhost(monkeypatch):
    """Reach the IPv4-only stub through 127.0.0.1 even though the action says `localhost`."""
    from platformctl.system import http

    real = http.request_json

    def request_json(method, url, *args, **kwargs):
        """The real call with `localhost` replaced."""
        return real(method, url.replace("://localhost:", "://127.0.0.1:"), *args, **kwargs)

    monkeypatch.setattr(http, "request_json", request_json)


def saved(root) -> dict[str, str]:
    """The values in `.env`."""
    return envfile.read(root / ".env")


def test_setup_creates_a_project_and_key_and_writes_every_setting(ctx_for, stub, platform_root):
    """A fresh DeepLynx: project, key, and all seven settings in `.env`; other lines are kept."""
    ctx, out, err = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 0
    values = saved(platform_root)
    assert values["DEEPLYNX_BASE_URL"] == INTERNAL_URL
    assert (values["DEEPLYNX_KEY"], values["DEEPLYNX_SECRET"]) == ("key1", "secret1")
    assert values["DEEPLYNX_ORG_ID"] == str(ORG_ID) and values["DEEPLYNX_PROJECT_ID"] == "1"
    assert values["DEEPLYNX_JWT_TOKEN"] == "" and values["DEEPLYNX_DATA_SOURCE_ID"] == ""
    assert values["OTHER"] == "kept"
    assert f"Created the DeepLynx project {PROJECT_NAME!r} (ID 1)." in out.getvalue()
    assert "Saved a new DeepLynx API key for project 1 in .env." in out.getvalue()
    assert out.getvalue().rstrip().endswith("DeepLynx UI: http://localhost:3456")
    assert "secret1" not in out.getvalue() + err.getvalue()


def test_setup_json_success_is_one_object_without_the_key(ctx_for, stub):
    """`--json`: the project and the UI, and never the new key or secret."""
    ctx, out, _ = ctx_for(json_mode=True)
    assert deeplynx.run_setup(ctx, ns()) == 0
    body = json.loads(out.getvalue())
    assert body["command"] == "deeplynx setup" and body["ok"] is True
    assert (body["project_id"], body["project_created"], body["already_configured"]) == (1, True, False)
    assert body["ui"] == "http://localhost:3456"
    assert "key1" not in out.getvalue() and "secret1" not in out.getvalue()


def test_setup_json_when_already_set_up_says_so(ctx_for, stub):
    """A second `--json` run reports that nothing was created."""
    ctx, _, _ = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 0
    ctx, out, _ = ctx_for(json_mode=True)
    assert deeplynx.run_setup(ctx, ns()) == 0
    body = json.loads(out.getvalue())
    assert body["already_configured"] is True and body["project_id"] == 1


def test_setup_json_dry_run_says_so(ctx_for):
    """A dry run is reported as one, with no server contacted."""
    ctx, out, _ = ctx_for(json_mode=True, dry_run=True)
    assert deeplynx.run_setup(ctx, ns(no_start=False)) == 0
    assert json.loads(out.getvalue())["dry_run"] is True


def test_setup_keeps_a_working_setup(ctx_for, stub, platform_root):
    """A second run changes nothing, creates no key or project, and still says where the UI is."""
    ctx, _, _ = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 0
    before = (platform_root / ".env").read_text()
    ctx, out, _ = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 0
    assert (platform_root / ".env").read_text() == before
    assert (len(stub.keys), len(stub.projects)) == (1, 1)
    assert "DeepLynx is already set up in .env." in out.getvalue()
    assert "DeepLynx UI: http://localhost:3456" in out.getvalue()


def test_setup_replaces_a_stale_key_after_the_database_is_gone(ctx_for, stub, platform_root):
    """After `make down-v` the key and project are gone: both are created again and saved."""
    ctx, _, _ = ctx_for()
    deeplynx.run_setup(ctx, ns())
    stub.keys.clear()
    stub.projects.clear()
    stub.requests.clear()
    ctx, _, _ = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 0
    assert "POST /oauth/keys" in stub.requests and f"POST /organizations/{ORG_ID}/projects" in stub.requests
    values = saved(platform_root)
    assert stub.keys == {values["DEEPLYNX_KEY"]: values["DEEPLYNX_SECRET"]}


def test_setup_reuses_an_existing_project_without_saying_it_created_one(ctx_for, stub):
    """A project with the right name is reused."""
    stub.projects = [{"id": 5, "name": PROJECT_NAME, "isArchived": False}]
    ctx, out, _ = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 0
    assert "Created the DeepLynx project" not in out.getvalue()
    assert "for project 5" in out.getvalue()


def test_setup_needs_local_deeplynx_and_says_how_to_turn_it_on(ctx_for, platform_root):
    """Without `LOCAL_DEEPLYNX` there is nothing to set up, and nothing is touched."""
    (platform_root / ".env").write_text(ENV.replace("LOCAL_DEEPLYNX=true", "LOCAL_DEEPLYNX=false"))
    ctx, _, err = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 1
    assert "LOCAL_DEEPLYNX is not true" in err.getvalue()
    assert "./platformctl config init --local-deeplynx" in err.getvalue()


def test_setup_without_an_env_file_says_to_run_config_init(platform_root, runner, stub):
    """No `.env` is an error that names the command, and DeepLynx isn't contacted."""
    ctx, _, err = make_context(
        platform_root, runner, {"PATH": "/usr/bin", "LOCAL_DEEPLYNX": "true", "DEEPLYNX_SERVER_PORT": str(stub.port)}
    )
    assert deeplynx.run_setup(ctx, ns()) == 1
    assert "does not exist" in err.getvalue() and "./platformctl config init" in err.getvalue()
    assert stub.requests == []


def test_setup_when_the_server_never_gets_healthy_leaves_env_alone(ctx_for, stub, platform_root):
    """A timeout is reported, not retried forever, and `.env` is untouched."""
    stub.healthy = False
    ctx, _, err = ctx_for()
    assert deeplynx.run_setup(ctx, ns(timeout=0)) == 1
    assert "DeepLynx didn't answer" in err.getvalue()
    assert (platform_root / ".env").read_text() == ENV


def test_setup_on_api_errors_leaves_env_alone_and_names_the_status(ctx_for, stub, platform_root):
    """A refused key request fails with the status only, and `.env` is untouched."""
    stub.fail["POST /oauth/keys"] = 500
    ctx, _, err = ctx_for()
    assert deeplynx.run_setup(ctx, ns()) == 1
    assert "HTTP 500" in err.getvalue()
    assert (platform_root / ".env").read_text() == ENV


def test_setup_starts_only_the_deeplynx_services_first(ctx_for, runner, stub):
    """Unless `--no-start`, Compose starts just the three services from the two files they need."""
    ctx, _, _ = ctx_for({"WAIT_TIMEOUT": "123", "COMPOSE_PROJECT_NAME": "proj"})
    assert deeplynx.run_setup(ctx, ns(no_start=False)) == 0
    up = next(call for call in runner.calls if call[:2] == ["docker", "compose"])
    assert up == [
        "docker", "compose", "-p", "proj", "-f", "docker-compose.yml", "-f", "docker-compose.deeplynx.yml",
        "up", "-d", "--wait", "--wait-timeout", "123",
        "deeplynx-postgres", "deeplynx-server", "deeplynx-ui",
    ]  # fmt: skip


def test_setup_stops_when_the_containers_fail_to_start(ctx_for, runner, stub, platform_root):
    """A failing Compose is `docker_unavailable`, and DeepLynx is not contacted."""
    runner.reply("docker", "compose", code=1)
    ctx, _, err = ctx_for()
    assert deeplynx.run_setup(ctx, ns(no_start=False)) == 1
    assert "Starting DeepLynx failed" in err.getvalue()
    assert stub.requests == []


def test_setup_dry_run_changes_nothing(ctx_for, runner, stub, platform_root):
    """`--dry-run` names what it would do and runs nothing."""
    ctx, out, _ = ctx_for(dry_run=True)
    assert deeplynx.run_setup(ctx, ns(no_start=False)) == 0
    assert "Would start deeplynx-postgres, deeplynx-server, deeplynx-ui" in out.getvalue()
    assert stub.requests == [] and not [c for c in runner.calls if c[:2] == ["docker", "compose"]]
    assert (platform_root / ".env").read_text() == ENV


def test_setup_failure_as_json_is_the_usual_error_object(ctx_for, platform_root):
    """With `--json`, a refusal is one object with a stable code."""
    (platform_root / ".env").write_text(ENV.replace("LOCAL_DEEPLYNX=true", "LOCAL_DEEPLYNX=false"))
    ctx, out, _ = ctx_for(json_mode=True)
    assert deeplynx.run_setup(ctx, ns()) == 1
    body = json.loads(out.getvalue())
    assert body["ok"] is False and body["command"] == "deeplynx setup" and body["error"]["code"] == "config_invalid"


def test_the_group_lists_setup():
    """`deeplynx` offers `setup`."""
    assert [s.NAME for s in deeplynx.SUBCOMMANDS] == ["setup"]
