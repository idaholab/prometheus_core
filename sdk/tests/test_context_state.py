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

"""load_context_state / save_context_state through the backend agent-state API."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from prometheus_api.agent import AgentStateConflict, AgentStateError, PrometheusAgent
from prometheus_api.agent.agent_state import AgentStateClient
from prometheus_api.agent.identity import UserIdentity, identity_scope

from .test_agent_state_client import FakeBackend

BASE = "http://backend:8000"
IDENTITY = UserIdentity(user_id="alice", claims={"sub": "alice"}, raw_token="user-jwt")


@pytest.fixture
def backend(monkeypatch) -> FakeBackend:
    fake = FakeBackend()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        AgentStateClient, "_client", lambda self: httpx.AsyncClient(transport=transport)
    )
    monkeypatch.setenv("REGISTRY_URL", BASE)
    monkeypatch.setenv("AGENT_SECRET", "s3cret")
    return fake


@pytest.fixture
def agent() -> PrometheusAgent:
    return PrometheusAgent(agent_name="Thermal Agent")


async def test_round_trip_across_requests(backend, agent):
    async def first():
        with identity_scope(IDENTITY):
            assert await agent.load_context_state("conv-1") == {}
            await agent.save_context_state("conv-1", {"phase": "awaiting_sizing"})

    async def second():
        with identity_scope(IDENTITY):
            state = await agent.load_context_state("conv-1")
            state["phase"] = "done"
            await agent.save_context_state("conv-1", state)
            return await agent.load_context_state("conv-1")

    await asyncio.create_task(first())
    assert await asyncio.create_task(second()) == {"phase": "done"}

    put = next(r for r in backend.requests if r.method == "PUT")
    assert put.url == f"{BASE}/v1/agent-state/conversations/conv-1"
    assert put.headers["x-agent-name"] == "thermal-agent"
    assert put.headers["x-user-token"] == "user-jwt"


async def test_concurrent_request_save_is_a_conflict(backend, agent):
    """Two requests load the same version; the later save must not overwrite the earlier."""
    both_loaded = asyncio.Barrier(2)
    first_saved = asyncio.Event()

    async def request(value: int, *, go_second: bool):
        with identity_scope(IDENTITY):
            await agent.load_context_state("conv-1")
            await both_loaded.wait()
            if go_second:
                await first_saved.wait()
            await agent.save_context_state("conv-1", {"n": value})
            first_saved.set()

    async def seed():
        with identity_scope(IDENTITY):
            await agent.save_context_state("conv-1", {"n": 0})

    await asyncio.create_task(seed())
    results = await asyncio.gather(
        request(1, go_second=False), request(2, go_second=True), return_exceptions=True
    )
    assert results[0] is None
    assert isinstance(results[1], AgentStateConflict)

    async def read():
        with identity_scope(IDENTITY):
            return await agent.load_context_state("conv-1")

    assert await asyncio.create_task(read()) == {"n": 1}


async def test_save_without_load_overwrites(backend, agent):
    async def write(n: int):
        with identity_scope(IDENTITY):
            await agent.save_context_state("conv-1", {"n": n})

    await asyncio.create_task(write(1))
    await asyncio.create_task(write(2))

    async def read():
        with identity_scope(IDENTITY):
            return await agent.load_context_state("conv-1")

    assert await asyncio.create_task(read()) == {"n": 2}


async def test_no_identity_raises(backend, agent):
    with pytest.raises(AgentStateError, match="identity"):
        await agent.load_context_state("conv-1")
    assert backend.requests == []


async def test_backend_failure_raises_instead_of_empty_state(backend, agent):
    backend.force_status = 503
    with identity_scope(IDENTITY), pytest.raises(AgentStateError):
        await agent.load_context_state("conv-1")
