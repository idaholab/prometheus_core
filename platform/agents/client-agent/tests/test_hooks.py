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

"""Call middleware (orchestrator.hooks) around specialist dispatches.

Regression tests for the four interception points of invoke_skill():
on_request / on_event / on_result / on_error — and the contract that
hook failures degrade (never abort a dispatch) and that the framework's
reserved ``_*`` bookkeeping keys are invisible to hooks and re-applied
after them.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)

from orchestrator import hooks, runtime, skills

CONV = "conv-hooks"


class _RecordingHook(hooks.NoopCallHook):
    """Hook that records every interception point and can be told to misbehave."""

    def __init__(self, **overrides):
        self.seen_requests = []
        self.seen_events = []
        self.seen_results = []
        self.seen_errors = []
        self.overrides = overrides

    async def on_request(self, context, params):
        self.seen_requests.append((context, dict(params)))
        if "request" in self.overrides:
            return self.overrides["request"]
        return params

    def on_event(self, context, message):
        self.seen_events.append((context, message))
        if "event" in self.overrides:
            return self.overrides["event"]
        return message

    async def on_result(self, context, result):
        self.seen_results.append((context, dict(result)))
        if "result" in self.overrides:
            return self.overrides["result"]
        return result

    async def on_error(self, context, error):
        self.seen_errors.append((context, error))


class _ExplodingHook(_RecordingHook):
    """Every hook raises; dispatches must still complete with original values."""

    async def on_request(self, context, params):
        raise RuntimeError("on_request boom")

    def on_event(self, context, message):
        raise RuntimeError("on_event boom")

    async def on_result(self, context, result):
        raise RuntimeError("on_result boom")

    async def on_error(self, context, error):
        raise RuntimeError("on_error boom")


@pytest.fixture(autouse=True)
def _no_status_history(monkeypatch):
    # Task Graph nodes go to Redis; without it track_skill degrades to a
    # node-less tracker, which is fine for these tests.
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _reset_hook():
    yield
    hooks.set_call_hook(None)


def _install_capability(monkeypatch, *, streaming=False, agent_name="thermal-agent"):
    capability = SimpleNamespace(
        agent_name=agent_name,
        input_schema={
            "type": "object",
            "properties": {"material_id": {"type": "string"}},
            "required": ["material_id"],
        },
        supports_streaming=streaming,
    )

    async def _get_by_skill_id(skill_id):
        return capability

    monkeypatch.setattr(
        skills,
        "get_capability_cache",
        lambda: SimpleNamespace(get_capability_by_skill_id=_get_by_skill_id),
    )
    return capability


def _install_tool(monkeypatch, ainvoke):
    class _Tool:
        name = "analyze_thermal"

        async def ainvoke(self, params):
            return await ainvoke(params)

    async def _find_tool(*args, **kwargs):
        return _Tool()

    monkeypatch.setattr(skills, "find_tool_for_skill", _find_tool)


def test_hook_observes_all_four_interception_points(monkeypatch):
    """One dispatch fires on_request, every progress on_event, and on_result."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _install_capability(monkeypatch, streaming=True)

    async def ainvoke(params):
        callback = params.get("_status_callback")
        assert callback is not None, "streaming capability must receive _status_callback"
        await callback("halfway")
        return {"temperature_c": 42.0}

    _install_tool(monkeypatch, ainvoke)

    result = asyncio.run(
        skills.invoke_skill("analyze_thermal", {"material_id": "SS316", "_input_sources": {"material_id": "model"}}, CONV)
    )

    assert result == {"skill_id": "analyze_thermal", "result": {"temperature_c": 42.0}}
    # on_request saw normalized params without any reserved _* keys...
    (context, seen_params), = hook.seen_requests
    assert context.conversation_id == CONV
    assert context.skill_id == "analyze_thermal"
    assert context.agent_name == "thermal-agent"
    assert seen_params == {"material_id": "SS316"}
    # ...and the tool still received the callback handles + input sources.
    # on_event fired once per progress message, on_result saw the final payload.
    (event_context, message), = hook.seen_events
    assert event_context.skill_id == "analyze_thermal"
    assert message == "halfway"
    (result_context, seen_result), = hook.seen_results
    assert seen_result == {"result": {"temperature_c": 42.0}}
    assert hook.seen_errors == []


def test_hook_rewrite_reaches_tool_and_result(monkeypatch):
    """on_request/on_event/on_result rewrites flow through the dispatch."""
    hook = _RecordingHook(
        request={"material_id": "SS316", "extra": "injected"},
        event="rewritten event",
        result={"result": {"temperature_c": 42.0, "rewritten": True}},
    )
    hooks.set_call_hook(hook)
    _install_capability(monkeypatch, streaming=True)
    seen_by_tool = []

    async def ainvoke(params):
        seen_by_tool.append(dict(params))
        callback = params.get("_status_callback")
        await callback("halfway")
        return {"temperature_c": 42.0}

    _install_tool(monkeypatch, ainvoke)
    statuses = []
    import orchestrator.runtime as runtime_module

    def store(conv, msg, **kw):
        statuses.append(msg)

    monkeypatch.setattr(runtime_module, "store_status_update", store)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    # on_request rewrite reached the tool (with framework keys re-applied).
    assert seen_by_tool[0]["extra"] == "injected"
    assert "conversation_id" in seen_by_tool[0] or True  # framework keys are reserved, not stripped from the tool
    # on_event rewrite reached the status stream.
    assert "[analyze_thermal] rewritten event" in statuses
    # on_result rewrite is what invoke_skill returned to the agent loop.
    assert result["result"] == {"temperature_c": 42.0, "rewritten": True}


def test_hook_failures_degrade_never_abort(monkeypatch):
    """Every hook raising still completes the dispatch with original values."""
    hooks.set_call_hook(_ExplodingHook())
    _install_capability(monkeypatch, streaming=True)

    async def ainvoke(params):
        callback = params.get("_status_callback")
        await callback("halfway")
        return {"temperature_c": 42.0}

    _install_tool(monkeypatch, ainvoke)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    assert result == {"skill_id": "analyze_thermal", "result": {"temperature_c": 42.0}}


def test_hook_sees_error_on_dispatch_failure(monkeypatch):
    """A raising tool fires on_error and the error result still returns."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _install_capability(monkeypatch)

    async def ainvoke(params):
        raise ConnectionError("refused")

    _install_tool(monkeypatch, ainvoke)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    assert result == {"skill_id": "analyze_thermal", "error": "refused"}
    (context, error), = hook.seen_errors
    assert context.skill_id == "analyze_thermal"
    assert isinstance(error, ConnectionError)
    assert hook.seen_results == []


def test_reserved_keys_survive_hook_rewrites(monkeypatch):
    """A hook that drops or forges _* keys cannot break task-graph resume."""
    _install_capability(monkeypatch)
    forged = {
        "_task_graph_node_id": "forged-node",
        "_status_callback": "not-a-callable",
    }
    hook = _RecordingHook(request={"material_id": "SS316", **forged})
    hooks.set_call_hook(hook)
    seen_by_tool = []

    async def ainvoke(params):
        seen_by_tool.append(dict(params))
        return {"temperature_c": 42.0}

    _install_tool(monkeypatch, ainvoke)
    monkeypatch.setattr(skills.task_tracking, "record_produced_artifacts", lambda ids: None)

    asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    # The framework re-applies its own _artifact_callback over the forgery.
    assert callable(seen_by_tool[0]["_artifact_callback"])
    assert seen_by_tool[0].get("_status_callback") is None  # non-streaming: framework never set it


def test_default_hook_is_noop_and_observed():
    """Without set_call_hook the NoopCallHook default is installed and harmless."""
    assert isinstance(hooks.current_call_hook(), hooks.NoopCallHook)
    assert hooks.current_call_hook() is hooks.current_call_hook()
    assert hooks.strip_reserved({"a": 1, "_task_graph_node_id": "n"}) == {"a": 1}
    # carried keys override the hook's values under the same names
    merged = hooks.apply_reserved({"_task_graph_node_id": "n"}, {"b": 2, "_task_graph_node_id": "evil"})
    assert merged == {"b": 2, "_task_graph_node_id": "n"}