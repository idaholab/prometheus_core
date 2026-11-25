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

"""Stack test: the backend serves the client-agent's workflow library through /api/workflows.

Talks to the already-running Compose stack through the backend's published host port
(``BACKEND_PORT`` in platform/.env). It never starts or stops a container, so it does not
use ``docker_compose_up`` or ``env_test_file``: with no stack running, those start one and
tear it down with its volumes. It only reads.
"""

import os
import time
from pathlib import Path
from typing import NoReturn

import httpx
import pytest

from .test_integration_backend import _env, _session_cookie


pytestmark = pytest.mark.integration

LOCAL = "comprehensive_material_analysis"
# The library's own host: the client-agent drops its own card from discovery, so the
# workflows its card ships are `local`, not `agent_card`.
LIBRARY_HOST = "client-agent"
# The client-agent compiles agent-card workflows on its discovery refresh, every
# DISCOVERY_REFRESH_SECONDS (default 300, at least 30): a stack that just started lists
# them only after the first refresh. The client-agent publishes no host port, so the
# test cannot trigger a refresh; it polls the list for one interval plus a margin.
CARD_WORKFLOW_WAIT_S = 330


def _unavailable(reason: str) -> NoReturn:
    """Fail under CI, which starts the stack before this suite, so a skip would hide a regression; else skip."""
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture
def stack(project_root: Path) -> tuple[str, dict[str, str], Path]:
    """The running stack's backend URL, its .env values and the .env path."""
    env_path = project_root / ".env"
    if not env_path.is_file():
        _unavailable(f"{env_path} does not exist: no stack was started from this checkout")
    env = _env(env_path)
    url = f"http://localhost:{env.get('BACKEND_PORT') or '8600'}"
    try:
        httpx.get(f"{url}/healthz", timeout=5, follow_redirects=True).raise_for_status()
    except httpx.HTTPError as exc:
        _unavailable(f"Backend stack does not answer at {url}: {type(exc).__name__}")
    for name in ("BACKEND_JWT_SECRET", "AGENT_SECRET"):
        if not env.get(name):
            _unavailable(f"{name} is not in the stack's .env")
    return url, env, env_path


def _cookies(env_path: Path) -> dict[str, str]:
    name, value = _session_cookie(env_path)
    return {name: value}


def _registered(url: str, env: dict[str, str]) -> list[dict]:
    resp = httpx.get(f"{url}/v1/agents", headers={"Authorization": f"Bearer {env['AGENT_SECRET']}"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def test_workflows_served_from_library_list(stack):
    """The list holds the local template with its approval flag and every workflow a registered card ships."""
    url, env, env_path = stack
    expected_from_cards = {
        workflow["id"]
        for entry in _registered(url, env)
        if entry["agent_name"] != LIBRARY_HOST
        for workflow in entry["agent_card_params"].get("workflows") or []
    }

    deadline = time.monotonic() + CARD_WORKFLOW_WAIT_S
    while True:
        resp = httpx.get(f"{url}/api/workflows", cookies=_cookies(env_path), timeout=30)
        listed = {row["workflow_id"] for row in resp.json().get("workflows", [])} if resp.status_code == 200 else set()
        if expected_from_cards <= listed or time.monotonic() >= deadline:
            break
        time.sleep(10)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True, body
    rows = {row["workflow_id"]: row for row in body["workflows"]}
    assert LOCAL in rows, f"{LOCAL} missing from /api/workflows: {sorted(rows)}"
    assert rows[LOCAL]["source"] == "local"
    assert rows[LOCAL]["requires_approval"] is True
    assert all("graph" not in row and "graph_id" not in row for row in body["workflows"])
    missing = sorted(expected_from_cards - set(rows))
    assert missing == [], f"registered agent-card workflows not listed: {missing}"
    not_from_cards = sorted(wid for wid in expected_from_cards if rows[wid]["source"] != "agent_card")
    assert not_from_cards == [], f"agent-card workflows listed with another source: {not_from_cards}"
    ownerless = sorted(wid for wid, row in rows.items() if row["source"] == "agent_card" and not row["owner"])
    assert ownerless == [], f"agent-card workflows without an owner: {ownerless}"


def test_workflows_served_from_library_detail(stack):
    """The detail of the local template is a consistent graph that agrees with its list row."""
    url, env, env_path = stack
    cookies = _cookies(env_path)
    registered = {entry["agent_name"] for entry in _registered(url, env)}

    resp = httpx.get(f"{url}/api/workflows/{LOCAL}", cookies=cookies, timeout=30)

    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["workflow_id"] == LOCAL
    assert detail["requires_approval"] is True
    assert set(detail["inputs"]) == {"required", "optional"}
    graph = detail["graph"]
    assert graph["workflow_id"] == LOCAL
    assert "graph_id" not in detail and "graph_id" not in graph
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    assert nodes and len(nodes) == len(graph["nodes"]), "node ids must be present and unique"
    assert all("graph_id" not in item for item in [*graph["nodes"], *graph["edges"]])

    skill_agents = {node["agent_name"] for node in nodes.values() if node["kind"] == "skill" and node["agent_name"]}
    assert detail["agent_count"] == len(skill_agents)
    assert detail["checkpoint_count"] == sum(1 for node in nodes.values() if node["kind"] == "checkpoint")
    assert skill_agents <= registered, f"nodes name unregistered agents: {sorted(skill_agents - registered)}"

    assert [edge["edge_id"] for edge in graph["edges"]] == [f"{LOCAL}-e{n}" for n in range(1, len(graph["edges"]) + 1)]
    for edge in graph["edges"]:
        assert edge["from_node"] in nodes and edge["to_node"] in nodes, edge
        if edge["kind"] == "data":
            sources = {
                item["port"]: item["source"] for item in nodes[edge["to_node"]]["inputs"] if item["source"] is not None
            }
            assert edge["port"] in sources, edge
            assert sources[edge["port"]].startswith(f"step.{edge['from_node']}."), edge
        else:
            assert edge["kind"] == "order" and edge["port"] is None, edge

    listed = httpx.get(f"{url}/api/workflows", cookies=cookies, timeout=30).json()["workflows"]
    row = next(item for item in listed if item["workflow_id"] == LOCAL)
    assert {key: value for key, value in detail.items() if key not in ("inputs", "graph")} == row


def test_workflows_served_from_library_unknown_id_is_404(stack):
    url, _, env_path = stack

    resp = httpx.get(f"{url}/api/workflows/nope", cookies=_cookies(env_path), timeout=30)

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Workflow not found"


def test_workflows_served_from_library_refuses_a_request_without_a_session(stack):
    url, _, _ = stack
    for path in ("/api/workflows", f"/api/workflows/{LOCAL}"):
        resp = httpx.get(f"{url}{path}", timeout=15)

        assert resp.status_code == 401, f"{path}: {resp.status_code} {resp.text}"
