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
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from a2a.types import AgentCard

from prometheus_api.agent import PrometheusAgent
from prometheus_api.agent.registry import AgentRegistryClient


class FakeRegistry:
    """A /v1/agents endpoint held in memory, keyed by agent name like the backend.

    Tests can clear it, take it down, or wrap its listing. ``calls`` records every
    request by method, including those answered while the registry is down;
    ``posts`` counts only the registrations it accepted. With ``litellm`` set it
    behaves like a LiteLLM proxy: a POST for a name it has is refused with 400, and
    entries have their own ``agent_id``.
    """

    def __init__(self):
        self.entries = {}
        self.down = False
        self.status = 503
        self.wrap = None
        self.litellm = False
        self.calls = []
        self.posts = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.method)
        if self.down:
            return httpx.Response(self.status)
        if request.method == "GET":
            listing = [{"agent_id": self._id(n), "agent_name": n} for n in sorted(self.entries)]
            return httpx.Response(200, json={self.wrap: listing} if self.wrap else listing)
        if request.method == "POST":
            body = json.loads(request.content)
            name = body["agent_name"]
            if self.litellm and name in self.entries:
                return httpx.Response(
                    400, json={"detail": f"Agent with name {name} already exists"}
                )
            self.entries[name] = body
            self.posts += 1
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            agent_id = request.url.path.rsplit("/", 1)[-1]
            name = next((n for n in self.entries if self._id(n) == agent_id), None)
            if name is None:
                return httpx.Response(404)
            del self.entries[name]
            return httpx.Response(200, json={})
        return httpx.Response(405)

    def _id(self, name):
        return f"id-{name}" if self.litellm else name


@pytest.fixture
def registry(monkeypatch):
    fake = FakeRegistry()
    real_async_client = httpx.AsyncClient
    real_client = httpx.Client

    def async_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_async_client(*args, transport=httpx.MockTransport(fake.handler), **kwargs)

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(fake.handler), **kwargs)

    monkeypatch.setattr("prometheus_api.agent.registry.httpx.AsyncClient", async_client)
    monkeypatch.setattr("prometheus_api.agent.registry.httpx.Client", client)
    monkeypatch.setattr(AgentRegistryClient, "MIN_CHECK_INTERVAL", 0.001)
    return fake


def _card() -> AgentCard:
    return AgentCard(name="Test Agent", description="test", version="1.0.0")


async def _until(condition, timeout=5.0):
    """Wait until ``condition()`` holds, polling, instead of a fixed sleep."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.001)


async def _stop(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_is_registered_reads_the_registry_listing(registry):
    client = AgentRegistryClient("http://registry")
    name = client.agent_name(_card())
    assert asyncio.run(client.is_registered_async(_card())) is False
    registry.entries[name] = {}
    assert asyncio.run(client.is_registered_async(_card())) is True


@pytest.mark.parametrize("key", ["data", "agents"])
def test_is_registered_unwraps_a_wrapped_listing(registry, key):
    client = AgentRegistryClient("http://registry")
    registry.entries[client.agent_name(_card())] = {}
    registry.wrap = key
    assert asyncio.run(client.is_registered_async(_card())) is True


def test_is_registered_raises_on_an_unexpected_listing(registry, monkeypatch):
    """An odd body is a failed check, not "no agents", or every check would re-register."""
    registry.wrap = "results"
    with pytest.raises(ValueError, match="unexpected registry listing"):
        asyncio.run(AgentRegistryClient("http://registry").is_registered_async(_card()))


def test_is_registered_raises_when_the_registry_is_down(registry):
    registry.down = True
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(AgentRegistryClient("http://registry").is_registered_async(_card()))


def _register_once(client, mode):
    if mode == "sync":
        client.register_once(_card())
    else:
        asyncio.run(client.register_once_async(_card()))


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_register_once_overwrites_without_deleting(registry, mode):
    """The backend overwrites by name; a delete first would open a gap in the listing."""
    client = AgentRegistryClient("http://registry")
    _register_once(client, mode)
    _register_once(client, mode)
    assert registry.calls == ["POST", "POST"]
    assert list(registry.entries) == [client.agent_name(_card())]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_register_once_replaces_an_entry_litellm_refuses(registry, mode):
    """LiteLLM answers 400 "already exists": delete that entry by agent_id, post again."""
    registry.litellm = True
    client = AgentRegistryClient("http://registry")
    _register_once(client, mode)
    assert registry.calls == ["POST"]
    _register_once(client, mode)
    assert registry.calls == ["POST", "POST", "GET", "DELETE", "POST"]
    assert registry.posts == 2
    assert list(registry.entries) == [client.agent_name(_card())]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_register_once_raises_on_another_400(registry, mode):
    """Only "already exists" leads to a delete; any other refusal is an error."""
    registry.down, registry.status = True, 400
    with pytest.raises(httpx.HTTPStatusError):
        _register_once(AgentRegistryClient("http://registry"), mode)
    assert registry.calls == ["POST"]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_register_once_raises_when_litellm_refuses_a_name_it_does_not_list(registry, mode):
    """A 400 "already exists" for a name missing from the listing is an error: no DELETE
    of a guessed id, and no second POST."""
    registry.litellm = True
    client = AgentRegistryClient("http://registry")
    registry.entries[client.agent_name(_card())] = {}
    real_handler = registry.handler

    def hide_the_entry(request):
        if request.method == "GET":
            registry.calls.append("GET")
            return httpx.Response(200, json=[])
        return real_handler(request)

    registry.handler = hide_the_entry
    with pytest.raises(LookupError, match="does not list it"):
        _register_once(client, mode)
    assert registry.calls == ["POST", "GET"]


def test_unparseable_registry_url_is_not_logged():
    """A REGISTRY_URL urlsplit rejects is logged as a placeholder, never as written."""
    client = AgentRegistryClient("http://SENTINEL-user:SENTINEL-pass@[::1")
    assert client.safe_registry_url == "<unparseable registry URL>"


def test_agent_with_a_blank_registry_url_registers_and_checks_nothing(monkeypatch, registry):
    """A REGISTRY_URL of only spaces turns registration off, and the checks with it."""
    monkeypatch.setenv("REGISTRY_URL", "   ")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0.001")
    agent = PrometheusAgent(agent_name="MyAgent")
    asyncio.run(asyncio.wait_for(agent.keep_registered_async(_card()), timeout=5))
    assert registry.calls == []


def test_keep_registered_re_registers_after_the_registry_is_cleared(registry):
    client = AgentRegistryClient("http://registry")

    async def scenario():
        await client.register_once_async(_card())
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.001))
        await _until(lambda: registry.calls.count("GET") >= 3)
        assert registry.posts == 1  # still listed: no re-registration
        registry.entries.clear()  # e.g. `make up` cleared the registry
        await _until(lambda: registry.posts == 2)
        await _stop(loop)

    asyncio.run(scenario())
    assert list(registry.entries) == [client.agent_name(_card())]


def test_keep_registered_treats_an_outage_as_a_failed_check_not_missing(registry, caplog):
    """Checks made during an outage never POST; once the registry is back and still
    lists the agent, nothing is posted either."""
    client = AgentRegistryClient("http://registry")

    async def scenario():
        await client.register_once_async(_card())
        registry.down = True
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.001))
        await _until(lambda: registry.calls.count("GET") >= 3)
        assert not loop.done()  # an outage is logged and retried, not fatal
        registry.down = False
        before = len(registry.calls)
        await _until(lambda: registry.calls[before:].count("GET") >= 3)
        await _stop(loop)

    with caplog.at_level(logging.WARNING):
        asyncio.run(scenario())
    assert registry.posts == 1  # only the startup registration
    assert registry.calls.count("POST") == 1  # no POST was even attempted during the outage
    assert "HTTPStatusError 503" in caplog.text  # type and status, never an empty message


def test_keep_registered_warns_once_per_outage(registry, caplog):
    """A registry that stays down (or a rejected token) warns once, not every check;
    repeats go to DEBUG, and the recovery is logged at INFO."""
    client = AgentRegistryClient("http://registry")
    registry.down, registry.status = True, 401

    async def scenario():
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.001))
        await _until(lambda: registry.calls.count("GET") >= 5)
        registry.down = False
        await _until(lambda: registry.posts == 1)
        await _until(lambda: "succeeded again" in caplog.text)
        await _stop(loop)

    with caplog.at_level(logging.DEBUG, logger="prometheus_api.agent.registry"):
        asyncio.run(scenario())
    failed = [r for r in caplog.records if "check failed" in r.getMessage()]
    assert len(failed) >= 4
    assert failed[0].levelno == logging.WARNING
    assert all(r.levelno == logging.DEBUG for r in failed[1:])
    assert "HTTPStatusError 401" in failed[0].getMessage()
    recovered = [r for r in caplog.records if "succeeded again" in r.getMessage()]
    assert [r.levelno for r in recovered] == [logging.INFO]


def test_registry_logs_never_contain_credentials(registry, caplog):
    """Credentials in REGISTRY_URL userinfo, the agent secret and the master key never
    reach the log, on the startup retries, the checks or a registration."""
    userinfo = "SENTINEL-user" + ":" + "SENTINEL-pass"
    client = AgentRegistryClient(
        f"http://{userinfo}@registry", master_key="SENTINEL-master", agent_secret="SENTINEL-secret"
    )
    registry.down = True

    async def scenario():
        await client.register_with_retries_async(_card(), max_retries=1, initial_delay=0.001)
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.001))
        await _until(lambda: registry.calls.count("GET") >= 3)
        registry.down = False
        await _until(lambda: registry.posts == 1)
        await _stop(loop)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())
        client.register_once(_card())
    assert "http://registry" in caplog.text
    assert "HTTPStatusError 503" in caplog.text
    assert "SENTINEL" not in caplog.text


def test_httpx_request_lines_are_quiet_only_for_registry_requests(registry, caplog):
    """The periodic GET does not log httpx's INFO request line; other httpx use still does."""
    client = AgentRegistryClient("http://registry")
    with caplog.at_level(logging.INFO, logger="httpx"):
        asyncio.run(client.is_registered_async(_card()))
        assert not [r for r in caplog.records if r.name == "httpx"]
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        with httpx.Client(transport=transport) as other:
            other.get("http://elsewhere/")
    assert [r for r in caplog.records if r.name == "httpx"]


def test_keep_registered_applies_the_real_minimum_interval(monkeypatch):
    """With the real MIN_CHECK_INTERVAL (the fixture lowers it), a tiny interval
    sleeps for the floor."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr("prometheus_api.agent.registry.asyncio.sleep", fake_sleep)
    assert AgentRegistryClient.MIN_CHECK_INTERVAL == 0.1
    client = AgentRegistryClient("http://registry")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.keep_registered_async(_card(), interval=1e-9))
    assert slept == [0.1]


def test_keep_registered_stops_when_cancelled_during_a_check(monkeypatch):
    """Cancellation during a registry call ends the loop instead of being retried."""
    client = AgentRegistryClient("http://registry")
    in_check = asyncio.Event()

    async def hanging_check(card):
        in_check.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(client, "is_registered_async", hanging_check)
    monkeypatch.setattr(AgentRegistryClient, "MIN_CHECK_INTERVAL", 0.001)

    async def scenario():
        loop = asyncio.create_task(client.keep_registered_async(_card(), interval=0.001))
        await in_check.wait()
        await _stop(loop)

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_keep_registered_rejects_an_interval_that_is_not_positive_and_finite(interval):
    with pytest.raises(ValueError, match="interval must be a positive"):
        asyncio.run(
            AgentRegistryClient("http://registry").keep_registered_async(_card(), interval=interval)
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 5.0),
        ("", 5.0),
        ("15", 15.0),
        ("0.5", 0.5),
        ("0", 0.0),
        ("x", 5.0),
        ("-5", 5.0),
        ("nan", 5.0),
        ("inf", 5.0),
        ("1e-9", 1e-9),  # warns; keep_registered_async applies the 0.1 s floor
    ],
)
def test_registry_check_interval_env(monkeypatch, caplog, raw, expected):
    if raw is None:
        monkeypatch.delenv("REGISTRY_CHECK_INTERVAL_SECONDS", raising=False)
    else:
        monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", raw)
    with caplog.at_level(logging.WARNING):
        assert PrometheusAgent.registry_check_interval() == expected
    # Anything other than unset, empty, or a valid value warns.
    assert bool(caplog.records) is (raw in ("x", "-5", "nan", "inf", "1e-9"))


def test_agent_keep_registered_stops_after_startup_when_disabled(monkeypatch, registry):
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0")
    agent = PrometheusAgent(agent_name="MyAgent")
    asyncio.run(asyncio.wait_for(agent.keep_registered_async(_card()), timeout=5))
    assert registry.posts == 1


def test_agent_keeps_checking_after_startup_registration_gave_up(monkeypatch, registry):
    """A registry that was down at startup is joined once it comes up."""
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_MAX_RETRIES", "0")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0.001")
    agent = PrometheusAgent(agent_name="MyAgent")
    registry.down = True

    async def scenario():
        task = asyncio.create_task(agent.keep_registered_async(_card()))
        await _until(lambda: registry.calls.count("GET") >= 2)  # startup gave up; checks go on
        assert registry.posts == 0 and not registry.entries
        registry.down = False
        await _until(lambda: registry.posts == 1)
        await _stop(task)

    asyncio.run(scenario())


def test_agent_that_overrides_registration_is_not_re_registered(monkeypatch, registry, caplog):
    """An override owns registration (here: opting out); the SDK never posts the default."""
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0.001")
    calls = []

    class OptOutAgent(PrometheusAgent):
        async def register_with_registry_async(self, agent_card, **kwargs):
            calls.append(agent_card.name)

    agent = OptOutAgent(agent_name="MyAgent")
    with caplog.at_level(logging.INFO):
        asyncio.run(asyncio.wait_for(agent.keep_registered_async(_card()), timeout=5))
    assert calls == ["Test Agent"]
    assert registry.calls == []
    warned = [r for r in caplog.records if "overrides register_with_registry_async" in r.message]
    assert [r.levelno for r in warned] == [logging.WARNING]
    assert "super()" in warned[0].message


def test_agent_whose_override_calls_super_is_not_re_registered(monkeypatch, registry):
    """super() registers once, but the override still owns registration: no checks."""
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0.001")

    class SuperAgent(PrometheusAgent):
        async def register_with_registry_async(self, agent_card, **kwargs):
            await super().register_with_registry_async(agent_card, **kwargs)

    agent = SuperAgent(agent_name="MyAgent")
    asyncio.run(asyncio.wait_for(agent.keep_registered_async(_card()), timeout=5))
    assert registry.calls == ["POST"]


class RecipeAgent(PrometheusAgent):
    """The override recipe in sdk/docs/agent/AGENT_MIGRATIONS.md, as written there."""

    async def register_with_registry_async(self, agent_card, **kwargs):
        client = AgentRegistryClient.from_env(self.registry_url())
        await client.register_and_keep_registered_async(
            agent_card,
            raw_agent_card=self.agent_card_dict,
            interval=self.registry_check_interval(),
        )


def test_override_recipe_with_checks_disabled_registers_once(monkeypatch, registry):
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0")
    agent = RecipeAgent(agent_name="MyAgent")
    asyncio.run(asyncio.wait_for(agent.keep_registered_async(_card()), timeout=5))
    assert registry.calls == ["POST"]


def test_override_recipe_joins_a_registry_that_was_down_at_startup(monkeypatch, registry):
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_MAX_RETRIES", "0")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0.001")
    agent = RecipeAgent(agent_name="MyAgent")
    registry.down = True

    async def scenario():
        task = asyncio.create_task(agent.keep_registered_async(_card()))
        await _until(lambda: registry.calls.count("GET") >= 2)
        assert not task.done()  # startup gave up without raising; checks go on
        registry.down = False
        await _until(lambda: registry.posts == 1)
        registry.entries.clear()
        await _until(lambda: registry.posts == 2)
        await _stop(task)

    asyncio.run(scenario())


def test_application_lifespan_runs_the_keep_alive_loop(monkeypatch, registry):
    """The wiring: startup registers, and the lifespan's task keeps the agent listed."""
    monkeypatch.setenv("REGISTRY_URL", "http://registry")
    monkeypatch.setenv("REGISTRY_CHECK_INTERVAL_SECONDS", "0.001")
    monkeypatch.setattr(
        PrometheusAgent, "_validate_deeplynx_configuration", staticmethod(lambda: None)
    )

    class LifespanAgent(PrometheusAgent):
        @asynccontextmanager
        async def lifespan(self, app):
            yield

    agent = LifespanAgent(agent_name="MyAgent")
    agent.agent_card_dict = None
    app = SimpleNamespace(state=SimpleNamespace())

    async def scenario():
        async with agent._application_lifespan(app, _card(), register_on_startup=True):
            await _until(lambda: registry.posts == 1)
            registry.entries.clear()
            await _until(lambda: registry.posts == 2)
        assert app.state.registry_registration_task.cancelled()

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))
