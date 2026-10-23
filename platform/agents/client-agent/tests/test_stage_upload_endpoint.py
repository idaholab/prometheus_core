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

"""Tests for OrchestratorAgent._stage_upload_endpoint's user_token verification.

Regression coverage for a real bug found while rebasing the multi-user work
onto the FastAPI backend: this endpoint is a raw Starlette route
(app.add_route), never routed through PrometheusAgentExecutor.execute(), so
identity_scope() is never active here. current_user_id() (the ContextVar
accessor) always returned None. The fix verifies an explicit user_token
query param instead of relying on that ambient context -- these tests would
have caught the original bug (staged_user_id always "" regardless of who
called it).

Builds a tiny standalone Starlette app around the unbound endpoint function
directly (it makes no use of `self`), rather than constructing a full
OrchestratorAgent (agent card loading, registry registration, etc.) -- see
test_execution_path.py for the heavier alternative used elsewhere in this suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

CLIENT_AGENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_AGENT_DIR))

# Other test modules in this suite (e.g. test_execution_path.py) stub
# prometheus_api.agent as a bare types.ModuleType in sys.modules to avoid the
# heavy a2a-sdk/litellm runtime -- a real package (with __file__ set), unlike
# that stub. sys.modules is process-global, so whichever test module runs
# first in a given pytest process wins; we need the *real* package (for
# .identity, a real submodule), so evict a detected stub and force a fresh
# import regardless of collection order.
if not getattr(sys.modules.get("prometheus_api.agent"), "__file__", None):
    for name in list(sys.modules):
        if name == "prometheus_api.agent" or name.startswith("prometheus_api.agent."):
            del sys.modules[name]

from orchestrator.service import OrchestratorAgent  # noqa: E402
from prometheus_api.agent.identity import mint_user_token  # noqa: E402

BASE_URL = "http://testserver"

# The endpoint body never reads `self`, so we can bind it directly without
# constructing a full OrchestratorAgent (which loads an agent card, etc.).
_stage_upload_endpoint = OrchestratorAgent._stage_upload_endpoint


async def _route(request):
    return await _stage_upload_endpoint(None, request)


def _build_app() -> Starlette:
    return Starlette(routes=[Route("/uploads/stage", _route, methods=["POST"])])


@pytest.fixture(scope="module")
def rsa_keypair():
    from prometheus_api.agent.identity_keygen import generate_keypair

    return generate_keypair(key_size=2048)


@pytest.fixture(autouse=True)
def identity_env(monkeypatch, tmp_path, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", private_pem)
    monkeypatch.setenv("USER_IDENTITY_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("USER_IDENTITY_ISS", "prometheus-platform")
    monkeypatch.setenv("USER_IDENTITY_AUD", "prometheus-agents")
    # Isolate staged uploads to a scratch dir so tests don't collide/leak.
    monkeypatch.setenv("PROMETHEUS_STAGED_UPLOAD_DIR", str(tmp_path))


async def _post_upload(*, query: dict, body: bytes = b"file-bytes") -> httpx.Response:
    transport = httpx.ASGITransport(app=_build_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        return await client.post("/uploads/stage", params=query, content=body)


@pytest.mark.asyncio
async def test_valid_user_token_stamps_verified_user_id():
    token = mint_user_token("alice")
    resp = await _post_upload(
        query={"name": "part.step", "conversation_id": "conv-1", "user_token": token}
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "alice"


@pytest.mark.asyncio
async def test_missing_user_token_stamps_empty_user_id():
    resp = await _post_upload(query={"name": "part.step", "conversation_id": "conv-1"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == ""


@pytest.mark.asyncio
async def test_invalid_user_token_stamps_empty_user_id_not_error():
    """An unverifiable token must degrade to an empty user_id, never raise."""
    resp = await _post_upload(
        query={"name": "part.step", "conversation_id": "conv-1", "user_token": "not-a-real-token"}
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == ""


@pytest.mark.asyncio
async def test_expired_user_token_stamps_empty_user_id():
    token = mint_user_token("alice", ttl_seconds=-1)
    resp = await _post_upload(
        query={"name": "part.step", "conversation_id": "conv-1", "user_token": token}
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == ""


@pytest.mark.asyncio
async def test_different_users_get_distinct_stamped_ids():
    token_a = mint_user_token("alice")
    token_b = mint_user_token("bob")

    resp_a = await _post_upload(query={"name": "a.txt", "conversation_id": "c1", "user_token": token_a})
    resp_b = await _post_upload(query={"name": "b.txt", "conversation_id": "c1", "user_token": token_b})

    assert resp_a.json()["user_id"] == "alice"
    assert resp_b.json()["user_id"] == "bob"
