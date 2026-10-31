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

"""An agent re-registers when the registry forgets it while the agent runs."""

import asyncio
import json

import httpx
import pytest
from a2a.types import AgentCard

from prometheus_api.agent import PrometheusAgent
from prometheus_api.agent.registry import AgentRegistryClient


class FakeRegistry:
    """A /v1/agents endpoint held in memory, which tests can clear or break."""

    def __init__(self):
        self.entries = []
        self.down = False
        self.posts = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503)
        if request.method == "GET":
            return httpx.Response(200, json=self.entries)
        if request.method == "POST":
            self.posts += 1
            body = json.loads(request.content)
            self.entries.append({"agent_id": str(self.posts), "agent_name": body["agent_name"]})
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            agent_id = request.url.path.rsplit("/", 1)[-1]
            self.entries = [e for e in self.entries if e["agent_id"] != agent_id]
            return httpx.Response(200, json={})
        return httpx.Response(405)


@pytest.fixture
def registry(monkeypatch):
    fake = FakeRegistry()
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(fake.handler), **kwargs)

    monkeypatch.setattr("prometheus_api.agent.registry.httpx.AsyncClient", client)
    return fake


def _card() -> AgentCard:
    return AgentCard(name="Test Agent", description="test", version="1.0.0")


def test_is_registered_reads_the_registry_listing(registry):
    client = AgentRegistryClient("http://registry")
    name = client.agent_name(_card())
    assert asyncio.run(client.is_registered_async(_card())) is False
    registry.entries.append({"agent_id": "1", "agent_name": name})
    assert asyncio.run(client.is_registered_async(_card())) is True


def test_is_registered_raises_when_the_registry_is_down(registry):
    registry.down = True
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(AgentRegistryClient("http://registry").is_registered_async(_card()))


def test_keep_registered_re_registers_after_the_registry_is_cleared(registry):
    client = AgentRegistryClient("http://registry")

    async def scenario():
        await client.register_once_async(_card())
        assert registry.posts == 1
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.01))
        await asyncio.sleep(0.05)
        assert registry.posts == 1  # still listed: no re-registration
        registry.entries.clear()  # e.g. `make up` cleared the registry
        await asyncio.sleep(0.05)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop

    asyncio.run(scenario())
    assert registry.posts == 2
    assert [e["agent_name"] for e in registry.entries] == [client.agent_name(_card())]


def test_keep_registered_survives_a_registry_outage(registry):
    client = AgentRegistryClient("http://registry")

    async def scenario():
        registry.down = True
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.01))
        await asyncio.sleep(0.05)
        assert not loop.done()  # an outage is logged and retried, not fatal
        registry.down = False
        await asyncio.sleep(0.05)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop

    asyncio.run(scenario())
    assert registry.posts == 1


def test_keep_registered_stops_when_cancelled_during_a_check(monkeypatch):
    """Cancellation during a registry call ends the loop instead of being retried."""
    client = AgentRegistryClient("http://registry")
    in_check = asyncio.Event()

    async def hanging_check(card):
        in_check.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(client, "is_registered_async", hanging_check)

    async def scenario():
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0))
        await in_check.wait()
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 60.0), ("", 60.0), ("15", 15.0), ("0", 0.0), ("x", 60.0), ("-5", 0.0)],
)
def test_registry_check_interval_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("REGISTRY_CHECK_INTERVAL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", raw)
    assert PrometheusAgent.registry_check_interval() == expected


def test_agent_keep_registered_stops_after_startup_when_disabled(monkeypatch, registry):
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0")
    agent = PrometheusAgent(agent_name="MyAgent")
    asyncio.run(asyncio.wait_for(agent.keep_registered_async(_card()), timeout=5))
    assert registry.posts == 1
