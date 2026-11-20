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

"""Agent workload identity (app/agent_identity.py) and its registry binding."""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.agent_identity import AgentCaller, parse_xfcc_spiffe_id, require_agent_caller
from app.config import settings
from app.routers.agent_registry import require_agent_secret

SECRET = "test-agent-secret"
AUTH = {"Authorization": f"Bearer {SECRET}"}
THERMAL_ID = "spiffe://cluster.local/ns/prometheus/sa/thermal-agent"
DATA_ID = "spiffe://cluster.local/ns/prometheus/sa/data-agent"


def xfcc(spiffe_id: str) -> dict[str, str]:
    return {"x-forwarded-client-cert": f"By=spiffe://cluster.local/ns/prometheus/sa/backend;Hash=abc;URI={spiffe_id}"}


def registration(name: str) -> dict:
    return {"agent_name": name, "agent_card_params": {"name": name, "url": f"http://{name}:8000/"}}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"By=spiffe://x/ns/a/sa/b;Hash=abc;URI={THERMAL_ID}", THERMAL_ID),
        (f'Hash=abc;URI="{THERMAL_ID}"', THERMAL_ID),
        # Chained hops: the last element is our direct peer.
        (f"URI={DATA_ID},By=spiffe://x/sa/b;URI={THERMAL_ID}", THERMAL_ID),
        # A quoted Subject may contain the separators.
        (f'Subject="CN=a,O=b;c";URI={THERMAL_ID}', THERMAL_ID),
        ("Hash=abc;URI=https://not-spiffe", None),
        ("Hash=abc", None),
        ("URI=spiffe://", None),
        ("", None),
        (f"URI={THERMAL_ID},Hash=abc", None),
    ],
)
def test_parse_xfcc(header, expected):
    assert parse_xfcc_spiffe_id(header) == expected


@pytest.fixture(autouse=True)
def agent_secret(monkeypatch):
    monkeypatch.setattr(settings, "agent_secret", SECRET)


@pytest.fixture
def istio(monkeypatch):
    monkeypatch.setattr(settings, "agent_identity_source", "istio")


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture
def whoami(fake_redis) -> TestClient:
    """A throwaway route guarded like future /v1 routes, on the real app's Valkey state."""
    router = APIRouter(dependencies=[Depends(require_agent_secret)])

    @router.get("/v1/test-whoami")
    async def whoami_route(caller: AgentCaller = Depends(require_agent_caller)) -> dict:
        return {"name": caller.name, "spiffe_id": caller.spiffe_id}

    app = FastAPI()
    app.state.redis = fake_redis
    app.include_router(router)
    return TestClient(app)


def test_trusted_name_uses_header(whoami):
    resp = whoami.get("/v1/test-whoami", headers={**AUTH, "X-Agent-Name": "thermal-agent"})
    assert resp.json() == {"name": "thermal-agent", "spiffe_id": None}
    assert whoami.get("/v1/test-whoami", headers=AUTH).status_code == 401


def test_trusted_name_ignores_xfcc(whoami):
    resp = whoami.get("/v1/test-whoami", headers={**AUTH, **xfcc(THERMAL_ID)})
    assert resp.status_code == 401


def test_secret_still_required(whoami):
    assert whoami.get("/v1/test-whoami", headers={"X-Agent-Name": "thermal-agent"}).status_code == 401


def test_istio_resolves_name_from_registration(istio, client, whoami):
    assert (
        client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)}).status_code
        == 200
    )

    # The claimed name is ignored; the certificate decides.
    resp = whoami.get("/v1/test-whoami", headers={**AUTH, **xfcc(THERMAL_ID), "X-Agent-Name": "data-agent"})
    assert resp.json() == {"name": "thermal-agent", "spiffe_id": THERMAL_ID}


def test_istio_rejects_missing_or_unregistered_identity(istio, whoami):
    assert whoami.get("/v1/test-whoami", headers={**AUTH, "X-Agent-Name": "thermal-agent"}).status_code == 401
    assert whoami.get("/v1/test-whoami", headers={**AUTH, **xfcc(DATA_ID)}).status_code == 403


def test_istio_registration_needs_identity(istio, client):
    assert client.post("/v1/agents", json=registration("thermal-agent"), headers=AUTH).status_code == 401


def test_istio_registration_cannot_take_over_another_agent(istio, client):
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})

    hijack = client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(DATA_ID)})
    assert hijack.status_code == 403
    assert client.delete("/v1/agents/thermal-agent", headers={**AUTH, **xfcc(DATA_ID)}).status_code == 403

    # The owner can re-register and delete.
    assert (
        client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)}).status_code
        == 200
    )
    assert client.delete("/v1/agents/thermal-agent", headers={**AUTH, **xfcc(THERMAL_ID)}).status_code == 200


def test_istio_one_workload_one_name(istio, client):
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    second = client.post("/v1/agents", json=registration("other-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    assert second.status_code == 409


def test_istio_binding_not_exposed(istio, client):
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    assert "spiffe" not in client.get("/v1/agents", headers={**AUTH, **xfcc(THERMAL_ID)}).text


def test_unknown_identity_source_rejected(monkeypatch):
    from app.config import _agent_identity_source

    monkeypatch.setenv("AGENT_IDENTITY_SOURCE", "mtls")
    with pytest.raises(ValueError):
        _agent_identity_source({})
