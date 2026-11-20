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

import asyncio

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.agent_identity import (
    SPIFFE_INDEX_KEY,
    AgentCaller,
    caller_spiffe_id,
    parse_xfcc_spiffe_id,
    require_agent_caller,
)
from app.config import settings
from app.routers.agent_registry import (
    REGISTRY_KEY,
    AgentRegistration,
    delete_agent,
    register_agent,
    require_agent_secret,
)

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
        # An escaped quote inside a quoted value doesn't end the quote.
        (f'Subject="CN=a\\";URI={DATA_ID};O=\\"";URI={THERMAL_ID}', THERMAL_ID),
        # An unterminated quote makes the hops ambiguous: no identity (fail closed).
        (f'URI={DATA_ID};By="x,URI={THERMAL_ID}', None),
        (f'URI={DATA_ID};X=",By=spiffe://x/sa/b;URI={THERMAL_ID}', None),
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


def test_caller_spiffe_id_ignores_xfcc_outside_istio():
    # Without the mesh the header is client-supplied, so it must never be trusted.
    request = Request({"type": "http", "headers": [(b"x-forwarded-client-cert", f"URI={THERMAL_ID}".encode())]})
    assert caller_spiffe_id(request) is None


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


def test_istio_rename_replaces_the_workloads_old_entry(istio, client, whoami):
    # An agent renamed but keeping its ServiceAccount must not be locked out.
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    renamed = client.post("/v1/agents", json=registration("heat-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    assert renamed.status_code == 200

    names = [e["agent_name"] for e in client.get("/v1/agents", headers=AUTH).json()]
    assert names == ["heat-agent"]
    assert whoami.get("/v1/test-whoami", headers={**AUTH, **xfcc(THERMAL_ID)}).json()["name"] == "heat-agent"


def test_istio_claims_an_unbound_entry(client, whoami, monkeypatch):
    client.post("/v1/agents", json=registration("thermal-agent"), headers=AUTH)  # trusted-name: no binding
    monkeypatch.setattr(settings, "agent_identity_source", "istio")

    claimed = client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    assert claimed.status_code == 200
    assert client.delete("/v1/agents/thermal-agent", headers={**AUTH, **xfcc(DATA_ID)}).status_code == 403


def test_istio_delete_drops_the_index(istio, client, whoami):
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    assert client.delete("/v1/agents/thermal-agent", headers={**AUTH, **xfcc(THERMAL_ID)}).status_code == 200
    assert whoami.get("/v1/test-whoami", headers={**AUTH, **xfcc(THERMAL_ID)}).status_code == 403
    assert client.delete("/v1/agents/thermal-agent", headers={**AUTH, **xfcc(THERMAL_ID)}).status_code == 404


def test_trusted_name_overwrite_drops_the_stale_index(client, fake_redis, monkeypatch):
    monkeypatch.setattr(settings, "agent_identity_source", "istio")
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    monkeypatch.setattr(settings, "agent_identity_source", "trusted-name")
    client.post("/v1/agents", json=registration("thermal-agent"), headers=AUTH)

    assert asyncio.run(fake_redis.hgetall(SPIFFE_INDEX_KEY)) == {}


def _request(spiffe_id: str) -> Request:
    header = (b"x-forwarded-client-cert", f"URI={spiffe_id}".encode())
    return Request({"type": "http", "headers": [header]})


async def _outcomes(calls) -> list[int]:
    results = await asyncio.gather(*calls, return_exceptions=True)
    return sorted(getattr(r, "status_code", 200) for r in results)


async def test_istio_concurrent_claims_of_one_name_admit_one_workload(istio, interleaving_redis):
    body = AgentRegistration(**registration("thermal-agent"))
    calls = [register_agent(body, _request(sid), interleaving_redis) for sid in (THERMAL_ID, DATA_ID)]

    assert await _outcomes(calls) == [200, 403]
    index = await interleaving_redis.hgetall(SPIFFE_INDEX_KEY)
    assert list(index.values()) == ["thermal-agent"]


async def test_istio_concurrent_names_leave_one_entry_per_workload(istio, interleaving_redis):
    calls = [
        register_agent(AgentRegistration(**registration(name)), _request(THERMAL_ID), interleaving_redis)
        for name in ("thermal-agent", "heat-agent")
    ]

    assert await _outcomes(calls) == [200, 200]
    entries = await interleaving_redis.hgetall(REGISTRY_KEY)
    assert len(entries) == 1
    assert await interleaving_redis.hget(SPIFFE_INDEX_KEY, THERMAL_ID) in entries


async def test_istio_delete_races_a_takeover(istio, interleaving_redis):
    await register_agent(AgentRegistration(**registration("thermal-agent")), _request(THERMAL_ID), interleaving_redis)
    calls = [
        delete_agent("thermal-agent", _request(THERMAL_ID), interleaving_redis),
        register_agent(AgentRegistration(**registration("thermal-agent")), _request(DATA_ID), interleaving_redis),
    ]

    assert await _outcomes(calls) == [200, 403]


def test_istio_binding_not_exposed(istio, client):
    client.post("/v1/agents", json=registration("thermal-agent"), headers={**AUTH, **xfcc(THERMAL_ID)})
    assert "spiffe" not in client.get("/v1/agents", headers={**AUTH, **xfcc(THERMAL_ID)}).text


@pytest.mark.parametrize(
    ("env", "config", "expected"),
    [("", {}, "trusted-name"), (" istio ", {}, "istio"), ("", {"agent-identity-source": "istio"}, "istio")],
)
def test_identity_source_env_is_resolved(monkeypatch, env, config, expected):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.Settings.model_fields["data"], "default", config)
    monkeypatch.setenv("AGENT_IDENTITY_SOURCE", env)
    assert config_mod.Settings().agent_identity_source == expected


def test_unknown_identity_source_rejected(monkeypatch):
    from app import config as config_mod

    monkeypatch.setenv("AGENT_IDENTITY_SOURCE", "mtls")
    with pytest.raises(ValueError, match="mtls"):
        config_mod.Settings()
