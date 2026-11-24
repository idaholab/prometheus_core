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

"""Integration tests for the FastAPI backend container."""

import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def backend_base_url(docker_compose_up, env_test_file):
    """Return the base URL for the backend service."""
    env_vars = {}
    for line in env_test_file.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env_vars[k] = v
    port = env_vars.get("BACKEND_PORT", "18600")
    return f"http://localhost:{port}"


def test_backend_container_running(docker_compose_up, container_id):
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_id("backend")],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "running"


def test_backend_healthz(backend_base_url):
    """The backend should serve its health endpoint."""
    resp = httpx.get(f"{backend_base_url}/healthz", timeout=15, follow_redirects=True)
    assert resp.status_code == 200


def _env(env_test_file) -> dict[str, str]:
    values = {}
    for line in env_test_file.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _session_cookie(env_test_file) -> tuple[str, str]:
    """A short-lived session cookie for a test user, signed with the stack's
    BACKEND_JWT_SECRET as the backend signs its own (app/security.py issue_token).

    Minted, not obtained through /api/setup/bootstrap: bootstrap creates the stack's one
    admin and can run only once, so a test must not spend it.
    """
    import jwt

    env = _env(env_test_file)
    secret = env.get("BACKEND_JWT_SECRET")
    if not secret:
        pytest.skip("BACKEND_JWT_SECRET is not in the stack's .env")
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "integration-test",
        "role": "user",
        "provider": "credentials",
        "sid": f"integration-{uuid.uuid4()}",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return env.get("BACKEND_COOKIE_NAME") or "prometheus_session", jwt.encode(claims, secret, algorithm="HS256")


def test_agent_status_lists_every_registered_agent_as_reachable(backend_base_url, env_test_file):
    """GET /api/agents on the real stack: every agent in the registry is listed, and each
    one's real /healthz answers through its real card url. Only the unit tests fake the
    probe, so this is the one check that a card url maps to a live /healthz."""
    agent_secret = _env(env_test_file).get("AGENT_SECRET")
    if not agent_secret:
        pytest.skip("AGENT_SECRET is not in the stack's .env")
    registered = httpx.get(
        f"{backend_base_url}/v1/agents", headers={"Authorization": f"Bearer {agent_secret}"}, timeout=15
    )
    registered.raise_for_status()
    expected = {entry["agent_name"] for entry in registered.json()}
    if not expected:
        pytest.skip("no agent is registered on this stack")
    name, value = _session_cookie(env_test_file)

    resp = httpx.get(f"{backend_base_url}/api/agents", cookies={name: value}, timeout=30)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    rows = {row["agent_name"]: row for row in body["agents"]}
    assert set(rows) == expected
    unreachable = sorted(agent for agent, row in rows.items() if not row["reachable"])
    assert unreachable == [], f"registered but not reachable: {unreachable}"
    assert all(row["registered_at"] for row in rows.values())


def test_agent_status_refuses_a_request_without_a_session(backend_base_url):
    resp = httpx.get(f"{backend_base_url}/api/agents", timeout=15)

    assert resp.status_code == 401
