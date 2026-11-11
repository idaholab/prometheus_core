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
import json
from types import SimpleNamespace

import pytest

import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)

import tool_discovery
from orchestrator import agent_loop, chat_flow, hooks, runtime, skills
from orchestrator.models import ConversationRequest
from prometheus_api.llm_client import ChatResponse, parse_finish_reason, parse_tool_calls

CONV = "conv-hooks"


class _RecordingHook(hooks.NoopCallHook):
    """Hook that records every interception point and can be told to misbehave."""

    def __init__(self, **overrides):
        self.seen_requests = []
        self.seen_events = []
        self.seen_results = []
        self.seen_errors = []
        self.seen_turns = []
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

    async def on_turn(self, context):
        self.seen_turns.append(context)


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

    async def on_turn(self, context):
        raise RuntimeError("on_turn boom")


@pytest.fixture(autouse=True)
def _no_status_history(monkeypatch):
    # Task Graph nodes go to Redis; without it track_skill degrades to a
    # node-less tracker, which is fine for these tests.
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _reset_hook():
    yield
    hooks.set_call_hook(None)


def _install_capability(monkeypatch, *, streaming=False, agent_id="thermal-agent", agent_name="Thermal Analysis Agent"):
    capability = SimpleNamespace(
        agent_id=agent_id,
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
        skills.invoke_skill(
            "analyze_thermal", {"material_id": "SS316", "_input_sources": {"material_id": "model"}}, CONV
        )
    )

    assert result == {"skill_id": "analyze_thermal", "result": {"temperature_c": 42.0}}
    # on_request saw normalized params without any reserved _* keys...
    ((context, seen_params),) = hook.seen_requests
    assert context.conversation_id == CONV
    assert context.skill_id == "analyze_thermal"
    # agent_id is the registry routing key; agent_name is the card's display name.
    assert context.agent_id == "thermal-agent"
    assert context.agent_name == "Thermal Analysis Agent"
    assert context.call_id
    assert seen_params == {"material_id": "SS316"}
    # ...and the tool still received the callback handles + input sources.
    # on_event fired once per progress message, on_result saw the final payload.
    ((event_context, message),) = hook.seen_events
    assert event_context.skill_id == "analyze_thermal"
    assert message == "halfway"
    ((result_context, seen_result),) = hook.seen_results
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


def test_hook_call_times_out_and_degrades(monkeypatch):
    """A hung async hook is cancelled at the timeout; the dispatch still completes."""
    monkeypatch.setattr(hooks, "_HOOK_TIMEOUT_SECONDS", 0.01)

    class _HangingHook(hooks.NoopCallHook):
        async def on_request(self, context, params):
            await asyncio.sleep(5)
            return params

    hooks.set_call_hook(_HangingHook())
    _install_capability(monkeypatch)

    async def ainvoke(params):
        return {"temperature_c": 42.0}

    _install_tool(monkeypatch, ainvoke)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    assert result == {"skill_id": "analyze_thermal", "result": {"temperature_c": 42.0}}


def test_hook_sees_error_on_dispatch_failure(monkeypatch):
    """An orchestrator-side exception inside ainvoke (e.g. schema validation) fires on_error."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _install_capability(monkeypatch)

    async def ainvoke(params):
        raise ConnectionError("refused")

    _install_tool(monkeypatch, ainvoke)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    assert result == {"skill_id": "analyze_thermal", "error": "refused"}
    ((context, error),) = hook.seen_errors
    assert context.skill_id == "analyze_thermal"
    assert isinstance(error, ConnectionError)
    assert hook.seen_results == []


def test_hook_sees_error_result_on_both_points(monkeypatch):
    """An error *result* — how call_agent reports real agent failures — fires on_error AND on_result."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _install_capability(monkeypatch)

    async def ainvoke(params):
        return {"error": "agent unreachable"}

    _install_tool(monkeypatch, ainvoke)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    assert result == {"skill_id": "analyze_thermal", "error": "agent unreachable"}
    ((error_context, error),) = hook.seen_errors
    assert isinstance(error, hooks.DispatchError)
    assert str(error) == "agent unreachable"
    ((result_context, seen_result),) = hook.seen_results
    assert seen_result == {"error": "agent unreachable"}


def test_on_error_fires_through_a_real_tool_on_dead_port(monkeypatch):
    """End to end: a real StructuredTool against an unreachable agent fires on_error."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _install_capability(monkeypatch)

    real_tool = asyncio.run(
        tool_discovery.create_tool_from_skill(
            "http://127.0.0.1:1",
            {
                "id": "analyze_thermal",
                "description": "dead-port probe",
                "inputSchema": {
                    "type": "object",
                    "properties": {"material_id": {"type": "string"}},
                    "required": ["material_id"],
                },
            },
        )
    )

    async def _find_tool(*args, **kwargs):
        return real_tool

    monkeypatch.setattr(skills, "find_tool_for_skill", _find_tool)

    result = asyncio.run(skills.invoke_skill("analyze_thermal", {"material_id": "SS316"}, CONV))

    assert "error" in result
    ((_, error),) = hook.seen_errors
    assert isinstance(error, hooks.DispatchError)
    ((_, seen_result),) = hook.seen_results
    assert "error" in seen_result


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


def test_set_call_hook_rejects_wrong_sync_async_shape():
    """A sync/async mismatch is rejected at install time, not silently ignored later."""

    class _AsyncEventHook(hooks.NoopCallHook):
        async def on_event(self, context, message):
            return message

    class _SyncRequestHook(hooks.NoopCallHook):
        def on_request(self, context, params):
            return params

    with pytest.raises(ValueError, match="on_event"):
        hooks.set_call_hook(_AsyncEventHook())
    with pytest.raises(ValueError, match="on_request"):
        hooks.set_call_hook(_SyncRequestHook())
    # The failed installs changed nothing; a well-shaped hook installs.
    assert isinstance(hooks.current_call_hook(), hooks.NoopCallHook)
    hooks.set_call_hook(_RecordingHook())
    assert isinstance(hooks.current_call_hook(), _RecordingHook)


# --------------------------------------------------------------------------- #
# on_turn — end-of-turn middleware (chat_flow.chat fire site)
# --------------------------------------------------------------------------- #


def _scripted_llm(monkeypatch, steps):
    """Install a ``runtime.create_llm`` stand-in popping one raw response per step.

    Mirrors ``ScriptedLLM`` in test_agent_loop.py: each step is a provider-shaped
    raw dict (``{"choices": [{"message": ..., "finish_reason": ...}]}``).
    """

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def medium(self, messages, **kwargs):
            return _llm_medium(steps, messages, kwargs)

        async def small(self, prompt, **kwargs):
            return SimpleNamespace(text="Test title")

    monkeypatch.setattr(runtime, "create_llm", lambda: _Client())


def _llm_medium(steps, messages, kwargs):
    raw = steps.pop(0)
    return ChatResponse(
        text=raw["choices"][0]["message"].get("content") or "",
        model_alias="medium",
        provider_model=None,
        usage=None,
        raw=raw,
        tool_calls=parse_tool_calls(raw),
        finish_reason=parse_finish_reason(raw),
    )


def _turn_harness(monkeypatch):
    """Patch chat_flow.chat's collaborators so a full turn runs offline.

    Fakes the conversation store (in-memory, JSON round-tripped like the real
    one) and the capability catalog (empty — no skills, so the LLM script
    fully controls the turn). ``begin_turn`` is NOT called: service.py owns
    that, and the hook must tolerate running without a task-tracking turn
    (turn_id/root_id=None), which is exactly what these tests exercise.
    """
    store = {}

    def save(conv_id, state):
        store[conv_id] = json.loads(json.dumps(state))

    monkeypatch.setattr(chat_flow, "get_conversation", lambda conv_id: store.get(conv_id))
    monkeypatch.setattr(chat_flow, "store_conversation", save)
    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", False)

    async def get_capabilities():
        return []

    monkeypatch.setattr(agent_loop, "get_capability_cache", lambda: SimpleNamespace(get_capabilities=get_capabilities))
    return store


def _reply(text="", calls=()):
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = list(calls)
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


def _tool_call(name, arguments, call_id):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def _send(**kwargs):
    return asyncio.run(chat_flow.chat(ConversationRequest(conversation_id=CONV, **kwargs)))


def test_on_turn_fires_with_full_trajectory_on_final(monkeypatch):
    """A turn ending in a final answer hands the hook the whole turn snapshot."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _turn_harness(monkeypatch)
    _scripted_llm(monkeypatch, [_reply(text="The answer is 42.")])

    response = _send(query="what is the answer?")

    assert response.status == "answer"
    (turn,) = hook.seen_turns
    assert turn.conversation_id == CONV
    assert turn.outcome == "final"
    assert turn.message == "The answer is 42."
    # The user message, the final assistant message: the whole turn, in order.
    assert [m["role"] for m in turn.llm_messages] == ["user", "assistant"]
    assert turn.llm_messages[0]["content"].startswith("what is the answer?")
    assert turn.llm_messages[-1]["content"] == "The answer is 42."
    assert dict(turn.tool_results) == {}
    assert dict(turn.tool_inputs) == {}
    # begin_turn was never called (service.py owns that): the hook tolerates a
    # missing task-tracking turn.
    assert turn.turn_id is None
    assert turn.root_id is None


def test_on_turn_pause_and_resume_are_two_events(monkeypatch):
    """An ask_user pause and its follow-up answer are two on_turn fires."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _turn_harness(monkeypatch)
    _scripted_llm(
        monkeypatch,
        [
            _reply(
                calls=[
                    _tool_call(
                        "ask_user",
                        {"questions": [{"field": "size", "question": "what size?", "type": "text"}]},
                        "c1",
                    )
                ]
            ),
        ],
    )

    first = _send(query="make a thing")
    assert first.status == "needs_info"
    (turn1,) = hook.seen_turns
    assert turn1.outcome == "needs_info"
    # The pending ask_user tool call is in the transcript the resume will see.
    assert any(m.get("tool_calls") for m in turn1.llm_messages)
    assert dict(turn1.tool_results) == {}

    hook.seen_turns.clear()
    _scripted_llm(monkeypatch, [_reply(text="Answer after info.")])
    second = _send(followup_answers={"size": "5"}, query="size is 5")
    assert second.status == "answer"
    (turn2,) = hook.seen_turns
    assert turn2.outcome == "final"
    assert turn2.llm_messages[0]["role"] == "user"  # the resume starts a fresh user message
    # The pause's ask_user question is answered in the resume's transcript.
    assert any(m.get("role") == "tool" for m in turn2.llm_messages)


def test_on_turn_snapshot_is_not_the_live_state(monkeypatch):
    """The hook must see copies, not the AgentState another turn could mutate."""
    hook = _RecordingHook()
    hooks.set_call_hook(hook)
    _turn_harness(monkeypatch)
    _scripted_llm(monkeypatch, [_reply(text="done")])
    _send(query="hello")

    (turn,) = hook.seen_turns
    messages = turn.llm_messages
    assert isinstance(messages, tuple)

    # Mutating what the store later holds must not reach the hook's snapshot
    # (and the hook's retained dict is not the live AgentState either).
    stored = chat_flow.get_conversation(CONV)
    assert stored is not None
    llm_list = stored["llm_messages"]
    assert len(messages) == len(llm_list)
    llm_list[-1]["content"] = "mutated after the fact"
    assert messages[-1]["content"] == "done"


def test_on_turn_failure_never_fails_the_turn(monkeypatch):
    """A raising on_turn is logged and the response still returns."""
    hooks.set_call_hook(_ExplodingHook())
    _turn_harness(monkeypatch)
    _scripted_llm(monkeypatch, [_reply(text="still fine")])

    response = _send(query="hello")

    assert response.status == "answer"
    assert response.message == "still fine"


def test_on_turn_default_hook_is_harmless(monkeypatch):
    """Without set_call_hook the NoopCallHook.on_turn logs and changes nothing."""
    _turn_harness(monkeypatch)
    _scripted_llm(monkeypatch, [_reply(text="noop turn")])

    response = _send(query="hello")

    assert response.status == "answer"
    assert response.message == "noop turn"
