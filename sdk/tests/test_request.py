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

"""Tests for PrometheusRequest and PrometheusRequestAgent."""

import asyncio
import inspect
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import TaskState

from prometheus_api.agent import (
    PrometheusAgent,
    PrometheusRequest,
    PrometheusRequestAgent,
    RequestClosedError,
)
from prometheus_api.agent.identity import UserIdentity, identity_scope

# Parameters the request fills in from itself.
_BOUND = {"context", "event_queue", "conversation_id"}
# Public agent helpers that take no request argument but are forwarded anyway.
_FORWARDED = {"get_credential", "identity_metadata", "current_user_id", "pending_hint"}


def _context(task_id: str = "task-1", context_id: str = "conv-1") -> MagicMock:
    context = MagicMock(spec=RequestContext)
    context.task_id = task_id
    context.context_id = context_id
    return context


def _wrapped_helpers() -> Dict[str, inspect.Signature]:
    """Public agent helpers that the request must wrap, with their signatures."""
    helpers = {}
    for name, member in inspect.getmembers(PrometheusAgent, inspect.isfunction):
        if name.startswith("_"):
            continue
        signature = inspect.signature(member)
        if _BOUND & signature.parameters.keys() or name in _FORWARDED:
            helpers[name] = signature
    return helpers


def _without(signature: inspect.Signature, names: set) -> list:
    return [
        (p.name, p.kind, p.default)
        for p in signature.parameters.values()
        if p.name not in names and p.name != "self"
    ]


def test_every_request_helper_has_a_wrapper():
    helpers = _wrapped_helpers()
    assert "send_status_update" in helpers and "get_artifact_file_path" in helpers
    for name, agent_signature in helpers.items():
        wrapper = getattr(PrometheusRequest, name, None)
        assert wrapper is not None, f"PrometheusRequest has no wrapper for {name}"
        expected = _without(agent_signature, _BOUND)
        actual = _without(inspect.signature(wrapper), set())
        # Defaults and names must match; kind may relax (positional -> keyword).
        assert [(n, d) for n, _, d in actual] == [(n, d) for n, _, d in expected], name
        assert inspect.iscoroutinefunction(wrapper) == inspect.iscoroutinefunction(
            getattr(PrometheusAgent, name)
        ), name


class _EchoRequest(PrometheusRequest[Any]):
    async def execute(self) -> Dict[str, Any]:
        await self.send_status_update(message="working")
        return {"params": self.params, "task": self.task_id, "conv": self.conversation_id}


class _EchoAgent(PrometheusRequestAgent):
    request_class = _EchoRequest


def test_agent_dispatches_to_a_new_request_per_call():
    agent = _EchoAgent(agent_name="Echo")
    queue = AsyncMock(spec=EventQueue)

    result = asyncio.run(agent._execute({"x": 1}, _context(), queue))

    assert result == {"params": {"x": 1}, "task": "task-1", "conv": "conv-1"}
    queue.enqueue_event.assert_awaited_once()


def test_concurrent_requests_do_not_share_state():
    class SlowRequest(PrometheusRequest[Any]):
        async def execute(self) -> Dict[str, Any]:
            self.value = self.params["v"]
            await asyncio.sleep(0.01)
            return {"value": self.value}

    class SlowAgent(PrometheusRequestAgent):
        request_class = SlowRequest

    agent = SlowAgent(agent_name="Slow")

    async def both():
        return await asyncio.gather(
            agent._execute({"v": 1}, _context("t1"), AsyncMock(spec=EventQueue)),
            agent._execute({"v": 2}, _context("t2"), AsyncMock(spec=EventQueue)),
        )

    assert asyncio.run(both()) == [{"value": 1}, {"value": 2}]


def test_missing_request_class_fails_at_construction():
    class NoRequestAgent(PrometheusRequestAgent):
        pass

    with pytest.raises(TypeError, match="request_class"):
        NoRequestAgent(agent_name="Broken")


def test_request_class_must_be_a_prometheus_request():
    class WrongAgent(PrometheusRequestAgent):
        request_class = dict  # type: ignore[assignment]

    with pytest.raises(TypeError, match="request_class"):
        WrongAgent(agent_name="Broken")


def test_base_execute_raises_not_implemented():
    class EmptyAgent(PrometheusRequestAgent):
        request_class = PrometheusRequest

    agent = EmptyAgent(agent_name="Empty")
    with pytest.raises(NotImplementedError):
        asyncio.run(agent._execute({}, _context(), AsyncMock(spec=EventQueue)))


def test_request_is_closed_after_execute_returns():
    kept: list = []

    class KeepRequest(PrometheusRequest[Any]):
        async def execute(self) -> Dict[str, Any]:
            kept.append(self)
            return {}

    class KeepAgent(PrometheusRequestAgent):
        request_class = KeepRequest

    asyncio.run(KeepAgent(agent_name="Keep")._execute({}, _context(), AsyncMock(spec=EventQueue)))

    with pytest.raises(RequestClosedError):
        asyncio.run(kept[0].send_status_update(message="late"))
    with pytest.raises(RequestClosedError):
        kept[0].resolve_artifact_reference("a-1")


def test_request_is_closed_after_execute_raises():
    kept: list = []

    class FailRequest(PrometheusRequest[Any]):
        async def execute(self) -> Dict[str, Any]:
            kept.append(self)
            raise ValueError("boom")

    class FailAgent(PrometheusRequestAgent):
        request_class = FailRequest

    with pytest.raises(ValueError):
        asyncio.run(
            FailAgent(agent_name="Fail")._execute({}, _context(), AsyncMock(spec=EventQueue))
        )
    with pytest.raises(RequestClosedError):
        kept[0].get_input_sources()


def test_wrappers_fill_in_context_queue_and_conversation():
    agent = PrometheusAgent(agent_name="Plain")
    agent.send_status_update = AsyncMock()  # type: ignore[method-assign]
    agent.send_json_artifact = AsyncMock(return_value="a-1")  # type: ignore[method-assign]
    agent.resolve_artifact_reference = MagicMock(return_value=None)  # type: ignore[method-assign]
    agent.get_artifact_file_path = AsyncMock()  # type: ignore[method-assign]
    context = _context()
    queue = AsyncMock(spec=EventQueue)
    request: PrometheusRequest[Any] = PrometheusRequest(agent, {}, context, queue)

    async def calls():
        await request.send_status_update(TaskState.TASK_STATE_WORKING, message="hi")
        assert await request.send_json_artifact({"k": 1}, name="r") == "a-1"
        request.resolve_artifact_reference("a-9")
        await request.get_artifact_file_path("a-9", force_download=True)

    asyncio.run(calls())

    agent.send_status_update.assert_awaited_once_with(
        context,
        queue,
        state=TaskState.TASK_STATE_WORKING,
        final=False,
        message="hi",
        metadata=None,
    )
    assert agent.send_json_artifact.await_args.args == (context, queue)
    assert agent.send_json_artifact.await_args.kwargs["payload"] == {"k": 1}
    agent.resolve_artifact_reference.assert_called_once_with("conv-1", "a-9")
    assert agent.get_artifact_file_path.await_args.kwargs["context"] is context
    assert agent.get_artifact_file_path.await_args.kwargs["force_download"] is True


def test_identity_and_execution_record_properties():
    agent = PrometheusAgent(agent_name="Plain")
    request: PrometheusRequest[Any] = PrometheusRequest(
        agent, {}, _context(), AsyncMock(spec=EventQueue)
    )
    assert request.identity is None and request.user_id is None
    assert request.execution_record_id is None

    identity = UserIdentity(user_id="u-1", claims={}, raw_token="tok")
    with identity_scope(identity):
        assert request.identity is identity
        assert request.user_id == "u-1"
        assert request.current_user_id() == "u-1"

    token = agent._execution_record_id.set(42)
    try:
        assert request.execution_record_id == 42
    finally:
        agent._execution_record_id.reset(token)


def _call_wrapper(request: PrometheusRequest[Any], name: str) -> tuple:
    """Call wrapper ``name`` with a distinct sentinel per argument.

    Returns the arguments the agent helper should receive (by parameter name)
    and the wrapper's result.
    """
    args: Dict[str, Any] = {}
    expected: Dict[str, Any] = {}
    for param in inspect.signature(getattr(request, name)).parameters.values():
        sentinel = object()
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            args["extra"] = sentinel
            expected[param.name] = {"extra": sentinel}
        else:
            args[param.name] = sentinel
            expected[param.name] = sentinel
    result = getattr(request, name)(**args)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return expected, result


@pytest.mark.parametrize("name", sorted(_wrapped_helpers()))
def test_every_wrapper_forwards_all_arguments(name):
    agent = PrometheusAgent(agent_name="Plain")
    returned = object()
    helper = getattr(PrometheusAgent, name)
    mock = (AsyncMock if inspect.iscoroutinefunction(helper) else MagicMock)(return_value=returned)
    setattr(agent, name, mock)
    context = _context()
    queue = AsyncMock(spec=EventQueue)
    request: PrometheusRequest[Any] = PrometheusRequest(agent, {}, context, queue)

    expected, result = _call_wrapper(request, name)

    returns_none = inspect.signature(helper).return_annotation in (None, "None")
    assert result is (None if returns_none else returned)
    mock.assert_called_once()
    args = mock.call_args.args
    if not isinstance(inspect.getattr_static(PrometheusAgent, name), staticmethod):
        args = (agent, *args)
    received = inspect.signature(helper).bind(*args, **mock.call_args.kwargs).arguments
    received.pop("self", None)
    filled = {"context": context, "event_queue": queue, "conversation_id": "conv-1"}
    for param in _BOUND & received.keys():
        assert received.pop(param) == filled[param], param
    assert received == expected


@pytest.mark.parametrize("name", sorted(_wrapped_helpers()))
def test_every_wrapper_refuses_a_closed_request(name):
    agent = MagicMock(spec=PrometheusAgent)
    request: PrometheusRequest[Any] = PrometheusRequest(
        agent, {}, _context(), AsyncMock(spec=EventQueue)
    )
    request.close()

    with pytest.raises(RequestClosedError):
        _call_wrapper(request, name)
    assert not agent.method_calls
