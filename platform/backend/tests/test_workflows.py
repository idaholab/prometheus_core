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

"""Workflow template API: GET /api/workflows and GET /api/workflows/{workflow_id}.

The routes (app/routers/workflows.py) read the client-agent's ``GET /workflows/templates``
through the ``_get_a2a_client`` seam; the ``library`` fixture installs a fake client whose
``list_workflow_templates`` returns a payload in the producer's wire shape
(agents/client-agent/workflow_library/graph.py) or raises.
"""

from __future__ import annotations

import logging
from typing import Any, Union

import httpx
import pytest
from fastapi.testclient import TestClient

WORKFLOW_KEYS = {
    "workflow_id",
    "name",
    "summary",
    "category",
    "version",
    "source",
    "owner",
    "complexity",
    "estimated_runtime_seconds",
    "speedup",
    "requires_approval",
    "agent_count",
    "checkpoint_count",
}


def _template(workflow_id: str, name: str, **overrides: Any) -> dict[str, Any]:
    """One template exactly as the client-agent serves it: every key present, graph and inputs included."""
    template: dict[str, Any] = {
        "workflow_id": workflow_id,
        "name": name,
        "summary": f"{name} over a made-up mesh.",
        "category": "Thermal",
        "version": "1.2.0",
        "source": "local",
        "owner": "thermal-team",
        "complexity": "moderate",
        "estimated_runtime_seconds": 180,
        "speedup": 3.5,
        "requires_approval": True,
        "agent_count": 2,
        "checkpoint_count": 1,
        "inputs": {"required": ["mesh_path"], "optional": ["notes"]},
        "graph": {
            "workflow_id": workflow_id,
            "mode": "dag",
            "nodes": [
                {
                    "node_id": "load",
                    "kind": "skill",
                    "skill_id": "load_mesh",
                    "label": "Load mesh",
                    "agent_name": "mesh-agent",
                    "is_final": False,
                    "inputs": [{"port": "path", "source": "input.mesh_path", "optional": False}],
                },
                {
                    "node_id": "check",
                    "kind": "checkpoint",
                    "skill_id": None,
                    "label": "check",
                    "agent_name": None,
                    "is_final": False,
                    "inputs": [{"port": "mesh", "source": "step.load.mesh", "optional": False}],
                },
                {
                    "node_id": "solve",
                    "kind": "skill",
                    "skill_id": "solve_heat",
                    "label": "Solve heat",
                    "agent_name": "thermal-agent",
                    "is_final": True,
                    "inputs": [
                        {"port": "mesh", "source": "step.check.mesh", "optional": False},
                        {"port": "temperature_c", "source": "context.temperature_c", "optional": False},
                        {"port": "notes", "source": None, "optional": True},
                    ],
                },
            ],
            "edges": [
                {
                    "edge_id": f"{workflow_id}-e1",
                    "from_node": "load",
                    "to_node": "check",
                    "kind": "data",
                    "port": "mesh",
                },
                {
                    "edge_id": f"{workflow_id}-e2",
                    "from_node": "check",
                    "to_node": "solve",
                    "kind": "data",
                    "port": "mesh",
                },
                {
                    "edge_id": f"{workflow_id}-e3",
                    "from_node": "load",
                    "to_node": "solve",
                    "kind": "order",
                    "port": None,
                },
            ],
        },
    }
    template.update(overrides)
    return template


def _library(*workflows: Any) -> dict[str, Any]:
    """The ``GET /workflows/templates`` body of an enabled library."""
    return {"enabled": True, "workflows": list(workflows), "errors": []}


class _FakeA2AClient:
    """Stands in for ``A2AClient``: ``list_workflow_templates`` returns ``result`` or raises it."""

    def __init__(self) -> None:
        self.result: Union[dict[str, Any], Exception] = _library()

    async def list_workflow_templates(self) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def library(monkeypatch) -> _FakeA2AClient:
    from app.routers import workflows as workflows_mod

    fake = _FakeA2AClient()
    monkeypatch.setattr(workflows_mod, "_get_a2a_client", lambda: fake)
    return fake


def _client_as(monkeypatch, *, role: str = "user", sid: str = "s-workflows") -> TestClient:
    from app import security
    from app.main import app

    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    token = security.issue_token(security.User(identifier=f"{role}-{sid}", role=role), sid=sid)
    client = TestClient(app)
    client.cookies.set("prometheus_session", token)
    return client


# --------------------------------------------------------------------------- #
# GET /api/workflows
# --------------------------------------------------------------------------- #


def test_workflows_list_from_library(monkeypatch, library):
    # Library order is neither the name order nor the workflow_id order: Zeta first (a dropped sort
    # returns it first), "zz-alpha" sorts after "zeta-check" (a sort by workflow_id alone puts it
    # last), and the two "Alpha Survey" rows come in reverse id order (a dropped workflow_id
    # tiebreak leaves them in library order).
    zeta = _template("zeta-check", "Zeta Check", complexity="complex", source="agent_card")
    late_alpha = _template(
        "zz-alpha",
        "Alpha Survey",
        owner=None,
        complexity=None,
        estimated_runtime_seconds=None,
        speedup=None,
    )
    early_alpha = _template("aa-alpha", "Alpha Survey", requires_approval=False)
    library.result = _library(zeta, late_alpha, early_alpha)
    client = _client_as(monkeypatch)

    resp = client.get("/api/workflows")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"available", "workflows"}
    assert body["available"] is True
    rows = body["workflows"]
    assert [(r["name"], r["workflow_id"]) for r in rows] == [
        ("Alpha Survey", "aa-alpha"),
        ("Alpha Survey", "zz-alpha"),
        ("Zeta Check", "zeta-check"),
    ]
    for row in rows:
        # Exactly the Workflow fields: no graph, no inputs, no graph_id.
        assert set(row) == WORKFLOW_KEYS
    early_row, late_row, zeta_row = rows
    assert zeta_row == {key: zeta[key] for key in WORKFLOW_KEYS}
    assert early_row["requires_approval"] is False
    assert (late_row["owner"], late_row["complexity"], late_row["estimated_runtime_seconds"], late_row["speedup"]) == (
        None,
        None,
        None,
        None,
    )


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://client-agent.local/workflows/templates")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError(f"{code} from the client-agent", request=request, response=response)


# What a degraded library read looks like through the seam: each makes the library unavailable.
_UNAVAILABLE = [
    pytest.param(httpx.ConnectError("connection refused"), id="connect-error"),
    pytest.param(httpx.ReadTimeout("timed out"), id="read-timeout"),
    pytest.param(_status_error(500), id="http-500"),
    pytest.param(ValueError("Workflow templates response is not a JSON object"), id="non-object-body"),
    pytest.param({"enabled": False, "workflows": [], "errors": []}, id="enabled-false"),
]


@pytest.mark.parametrize("result", _UNAVAILABLE)
def test_workflows_list_degrades(monkeypatch, library, result):
    library.result = result
    client = _client_as(monkeypatch)

    resp = client.get("/api/workflows")

    assert resp.status_code == 200
    assert resp.json() == {"available": False, "workflows": []}


@pytest.mark.parametrize("result", _UNAVAILABLE)
def test_workflows_list_degrades_detail_503(monkeypatch, library, result):
    library.result = result
    client = _client_as(monkeypatch)

    resp = client.get("/api/workflows/heat-survey")

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Workflow library is unavailable"}


# --------------------------------------------------------------------------- #
# GET /api/workflows/{workflow_id}
# --------------------------------------------------------------------------- #


def test_workflow_detail_from_library(monkeypatch, library):
    heat = _template("heat-survey", "Heat Survey")
    library.result = _library(_template("other-survey", "Other Survey"), heat)
    client = _client_as(monkeypatch)

    resp = client.get("/api/workflows/heat-survey")

    assert resp.status_code == 200
    body = resp.json()
    # The whole template round-trips: every Workflow field, the inputs and the graph.
    assert body == heat
    assert body["inputs"] == {"required": ["mesh_path"], "optional": ["notes"]}
    edges = {edge["edge_id"]: edge for edge in body["graph"]["edges"]}
    assert (edges["heat-survey-e1"]["kind"], edges["heat-survey-e1"]["port"]) == ("data", "mesh")
    assert (edges["heat-survey-e3"]["kind"], edges["heat-survey-e3"]["port"]) == ("order", None)


def test_workflow_detail_from_library_unknown_id_404(monkeypatch, library):
    library.result = _library(_template("heat-survey", "Heat Survey"))
    client = _client_as(monkeypatch)

    resp = client.get("/api/workflows/nope")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Workflow not found"}


# --------------------------------------------------------------------------- #
# A template that does not validate
# --------------------------------------------------------------------------- #


def test_workflows_drop_malformed_entry(monkeypatch, library, caplog):
    valid = _template("heat-survey", "Heat Survey")
    no_graph = _template("no-graph", "No Graph")
    del no_graph["graph"]
    bad_kind = _template("bad-kind", "Bad Kind")
    bad_kind["graph"]["nodes"][0]["kind"] = "lambda"
    library.result = _library(no_graph, "not-a-template", valid, bad_kind)
    client = _client_as(monkeypatch)
    caplog.set_level(logging.WARNING, logger="app.routers.workflows")

    resp = client.get("/api/workflows")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert [row["workflow_id"] for row in body["workflows"]] == ["heat-survey"]
    # One warning per dropped entry, naming its id (None for an entry that is not an object).
    dropped = [r.getMessage() for r in caplog.records if r.name == "app.routers.workflows"]
    assert dropped == [
        "Dropping malformed workflow template 'no-graph'",
        "Dropping malformed workflow template None",
        "Dropping malformed workflow template 'bad-kind'",
    ]

    for workflow_id in ("no-graph", "bad-kind"):
        detail = client.get(f"/api/workflows/{workflow_id}")
        assert detail.status_code == 404, workflow_id
        assert detail.json() == {"detail": "Workflow not found"}, workflow_id
    assert client.get("/api/workflows/heat-survey").json() == valid


# --------------------------------------------------------------------------- #
# Session requirement on both routes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["/api/workflows", "/api/workflows/x"], ids=["list", "detail"])
def test_workflows_require_session_no_cookie_401(library, path):
    from app.main import app

    # The library holds "x", so a route without ``current_claims`` would answer 200 here, not 401.
    library.result = _library(_template("x", "X"))
    client = TestClient(app)

    resp = client.get(path)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_workflows_require_session_user_role_allowed(monkeypatch, library):
    library.result = _library(_template("x", "X"))
    client = _client_as(monkeypatch, role="user")

    resp = client.get("/api/workflows")

    assert resp.status_code == 200
    assert [row["workflow_id"] for row in resp.json()["workflows"]] == ["x"]


@pytest.mark.parametrize("cookie", ["not-a-jwt", "other-secret"], ids=["not-a-jwt", "other-secret"])
@pytest.mark.parametrize("path", ["/api/workflows", "/api/workflows/x"], ids=["list", "detail"])
def test_workflows_require_session_bad_cookie_401(monkeypatch, library, path, cookie):
    from app import security
    from app.main import app

    library.result = _library(_template("x", "X"))
    if cookie == "other-secret":
        # Signed by a key the app does not hold: a valid JWT with a bad signature.
        monkeypatch.setattr(security.settings, "jwt_secret", "other-secret", raising=False)
        cookie = security.issue_token(security.User(identifier="user-forged", role="user"), sid="s-forged")
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    client = TestClient(app)
    client.cookies.set("prometheus_session", cookie)

    resp = client.get(path)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired session"
