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

"""The chat turn as one ADK run of the client agent: skill dispatch and the approval pause.

The run uses in-memory ADK services (``AdkRun(test=True)``) and a stub model that calls the
catalog's tools by name, so no real LLM is involved. Dispatch is ``call_a2a_agent``, patched.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role, SendMessageRequest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.protobuf.json_format import MessageToDict

import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)
from prometheus_api.adk.plugins.provenance import PARENT_EXECUTION_RECORD_METADATA_KEY
from prometheus_api.adk.runner import _in_memory_services
from prometheus_api.agent.events import normalize_producer_agent_id
from prometheus_api.agent import ownership
from prometheus_api.agent.base import DelegatingPrometheusAgentExecutor
from prometheus_api.agent.identity import UserIdentity, identity_scope
from prometheus_api.storage_client.connection import ConnectionConfig

import file_upload_handler
import task_graph
import tool_discovery
from orchestrator import adk_tools, agent_loop, chat_flow, debug_commands, runtime, service, task_tracking
from orchestrator.models import ConversationRequest
from workflow_library.compiler import compile_workflow
from tests.test_task_graph import _FakeRedis
from workflow_library.naming import workflow_tool_name

CONV = "conv1"
PLAIN = "plain_skill"
APPROVAL = "approval_skill"
AGENT_URL = "http://litellm:4000/a2a/test-agent"


def _schema(required: str) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {required: {"type": "string"}},
        "required": [required],
    }


def _skill(name: str, required: str, *, requires_approval: bool = False) -> agent_loop.ToolSpec:
    return agent_loop.ToolSpec(
        name=name,
        kind="skill",
        target=name,
        label=name,
        agent_name="Test Agent",
        description=f"{name} skill",
        parameters=_schema(required),
        input_schema=_schema(required),
        runtime_required=(required,),
        requires_approval=requires_approval,
    )


CATALOG = {
    PLAIN: _skill(PLAIN, "word"),
    APPROVAL: _skill(APPROVAL, "title", requires_approval=True),
    agent_loop.ASK_USER_TOOL: agent_loop.ASK_USER_SPEC,
}


# The first response of a paused call (an approval, an ask_user form, a specialist's question):
# the call is not answered yet.
PAUSED = {"pending_approval", "pending", "input_required"}


def _responses(llm_request: LlmRequest, *, since_request: bool = False) -> Dict[str, Dict[str, Any]]:
    """The final function responses in the request, by tool name (a pause is not final).

    With *since_request*, only those after the latest user text: the results of this request.
    """
    found: Dict[str, Dict[str, Any]] = {}
    # A hidden specialist_input call re-runs a paused skill call; its result answers that skill.
    reruns: Dict[str, str] = {}
    for content in llm_request.contents:
        if since_request and content.role == "user" and any(part.text for part in content.parts or []):
            found = {}
        for part in content.parts or []:
            call = part.function_call
            if call and call.name == adk_tools.SPECIALIST_INPUT_TOOL:
                reruns[str(call.id)] = str((call.args or {}).get("tool") or "")
            response = part.function_response
            if response and dict(response.response or {}).get("status") not in PAUSED:
                found[str(response.name)] = dict(response.response or {})
                if str(response.id) in reruns:
                    found[reruns[str(response.id)]] = found[str(response.name)]
    return found


class _StubLlm(BaseLlm):
    """Calls each scripted tool in order, one per model turn, then answers with text."""

    model: str = "stub"
    calls: List[Dict[str, Any]] = []
    # The text of the user messages the model saw, newest last.
    seen: List[str] = []
    # A fixed call id per tool name (default: call-<index>).
    ids: Dict[str, str] = {}
    # Count a scripted call as done only by a result of this request, not of an earlier turn.
    this_request_only: bool = False
    # The system instruction of each model call, in order.
    instructions: List[str] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.instructions.append(str(llm_request.config.system_instruction))
        self.seen.extend(
            part.text
            for content in llm_request.contents
            if content.role == "user"
            for part in content.parts or []
            if part.text and part.text not in self.seen
        )
        done = _responses(llm_request, since_request=self.this_request_only)
        for index, call in enumerate(self.calls):
            if call["name"] not in done:
                call_id = self.ids.get(call["name"], f"call-{index}")
                function_call = types.FunctionCall(id=call_id, name=call["name"], args=dict(call["args"]))
                parts = [types.Part(function_call=function_call)]
                break
        else:
            recent = _responses(llm_request, since_request=True)
            parts = [types.Part(text="done: " + json.dumps(recent, sort_keys=True, default=str))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


@pytest.fixture
def harness(monkeypatch):
    store: Dict[str, Any] = {}
    dispatched: List[tuple] = []
    catalog: Dict[str, agent_loop.ToolSpec] = dict(CATALOG)
    # A skill's A2A reply, by skill id; the default is a plain success.
    replies: Dict[str, Any] = {}

    async def build_tool_catalog() -> Dict[str, agent_loop.ToolSpec]:
        return dict(catalog)

    async def call_a2a_agent(agent_url: str, skill_id: str, **params: Any) -> Dict[str, Any]:
        dispatched.append((agent_url, skill_id, params))
        reply = replies.get(skill_id)
        if isinstance(reply, list):  # one scripted reply per dispatch
            reply = reply.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply or {"skill_id": skill_id, "result": {"answer": f"{skill_id} ran"}}

    async def get_capability_by_skill_id(skill_id: str) -> SimpleNamespace:
        return SimpleNamespace(agent_url=AGENT_URL, supports_streaming=False)

    async def no_title(state: Any, conv_id: str) -> None:
        return None

    def save(conv_id: str, state: Dict[str, Any]) -> None:
        # Round-trip through JSON: persisted state must be serializable.
        store[conv_id] = json.loads(json.dumps(state, default=str))

    graph = _FakeRedis()
    monkeypatch.setattr(task_graph, "_client", lambda: graph)
    monkeypatch.setattr(agent_loop, "build_tool_catalog", build_tool_catalog)
    monkeypatch.setattr(tool_discovery, "call_a2a_agent", call_a2a_agent)
    monkeypatch.setattr(
        adk_tools,
        "get_capability_cache",
        lambda: SimpleNamespace(get_capability_by_skill_id=get_capability_by_skill_id),
    )
    monkeypatch.setattr(chat_flow, "get_conversation", lambda conv_id: copy.deepcopy(store.get(conv_id)))
    monkeypatch.setattr(chat_flow, "store_conversation", save)
    monkeypatch.setattr(chat_flow, "_maybe_generate_title", no_title)
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

    agent = service.OrchestratorAgent()
    agent.get_raw_agent_card = lambda: {"skills": []}

    def send(model: _StubLlm, *, turn: bool = False, **kwargs: Any):
        """One chat() turn; with *turn*, inside a Task Graph turn, as service._execute runs it."""

        async def run():
            if turn:
                task_tracking.begin_turn(CONV, str(kwargs.get("query") or "request"))
            chat_flow.adk_run.set(
                chat_flow.AdkRun(
                    agent,
                    service._detached_context(CONV),
                    service._DetachedEventQueue(),
                    test=True,
                    model=model,
                )
            )
            response = await chat_flow.chat(ConversationRequest(conversation_id=CONV, **kwargs))
            if turn:
                task_tracking.finish_turn(response.status)
            return response

        return asyncio.run(run())

    return SimpleNamespace(store=store, dispatched=dispatched, catalog=catalog, replies=replies, agent=agent, send=send)


def test_adk_orchestrator_dispatches_skill_and_pauses_for_approval(harness) -> None:
    model = _StubLlm(
        calls=[
            {"name": PLAIN, "args": {"word": "valve"}},
            {"name": APPROVAL, "args": {"title": "SAR"}},
        ]
    )

    first = harness.send(model, query="Make a valve, then review the SAR")

    # The plain skill ran once over A2A with the bound arguments; the approval skill waits.
    assert first.status == "plan_ready", first.message
    assert [(url, skill) for url, skill, _ in harness.dispatched] == [(AGENT_URL, PLAIN)]
    assert harness.dispatched[0][2]["word"] == "valve"
    assert harness.dispatched[0][2]["conversation_id"] == CONV
    assert harness.store[CONV]["awaiting_approval"] is True
    assert first.plan["skills"] == [APPROVAL]

    # approve_pending is gone: chat(plan_approved=True) resumes the paused ADK run.
    second = harness.send(model, plan_approved=True)

    assert second.status == "completed", second.message
    # The devel "completed" shape: the report is the reply, and tool_results carry the turn's calls.
    assert second.report == second.message
    assert set(second.tool_results) == {PLAIN, APPROVAL}
    assert second.tool_results[APPROVAL] == {"skill_id": APPROVAL, "result": {"answer": "approval_skill ran"}}
    assert [skill for _, skill, _ in harness.dispatched] == [PLAIN, APPROVAL]
    assert harness.dispatched[1][2]["title"] == "SAR"
    assert harness.store[CONV]["awaiting_approval"] is False


def test_adk_orchestrator_does_not_dispatch_a_call_missing_a_required_argument(harness) -> None:
    model = _StubLlm(calls=[{"name": PLAIN, "args": {}}])

    response = harness.send(model, query="Make something")

    # _validation_problem answers the call with an error the model sees; nothing is dispatched.
    assert harness.dispatched == []
    assert response.status == "answer", response.message
    assert "Missing required input(s) word" in response.message


# --------------------------------------------------------------------------- #
# Pauses and resumption on the ADK run
# --------------------------------------------------------------------------- #


def test_a_skill_without_approval_runs_without_a_pause(harness) -> None:
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    response = harness.send(model, query="Make a valve")

    assert response.status == "completed", response.message
    assert [skill for _, skill, _ in harness.dispatched] == [PLAIN]
    stored = harness.store[CONV]
    assert (stored["awaiting_approval"], stored["pending_calls"], stored["plan"]) == (False, [], None)


def test_rejected_plan_closes_the_approval_without_dispatching(harness) -> None:
    model = _StubLlm(calls=[{"name": APPROVAL, "args": {"title": "SAR"}}])

    assert harness.send(model, query="Review the SAR").status == "plan_ready"
    response = harness.send(model, plan_rejected=True)

    assert response.status == "answer", response.message
    assert harness.dispatched == []
    stored = harness.store[CONV]
    assert stored["awaiting_approval"] is False
    assert stored["pending_calls"] == []
    assert stored["plan"] is None
    assert stored["conversation_history"][-1]["type"] == "plan_rejected"


def test_free_text_while_awaiting_approval_supersedes_the_call(harness) -> None:
    model = _StubLlm(calls=[{"name": APPROVAL, "args": {"title": "SAR"}}])

    assert harness.send(model, query="Review the SAR").status == "plan_ready"
    response = harness.send(model, query="Never mind, just say hi")

    # The approval is closed unconfirmed and the reply runs as a new request: only its answer shows.
    assert response.status == "answer", response.message
    assert response.message == "done: {}"
    assert "reject" not in response.message.lower()
    assert harness.dispatched == []
    history = harness.store[CONV]["conversation_history"]
    assert [entry.get("type") for entry in history if entry["role"] == "assistant"] == ["plan", "answer"]
    assert "Never mind, just say hi" in model.seen
    assert harness.store[CONV]["awaiting_approval"] is False
    assert harness.store[CONV]["user_query"] == "Never mind, just say hi"


def test_ask_user_pauses_for_a_form_and_the_answers_resume_the_run(harness) -> None:
    questions = [{"field": "word", "question": "Which word?"}]
    model = _StubLlm(
        calls=[
            {"name": agent_loop.ASK_USER_TOOL, "args": {"questions": questions}},
            {"name": PLAIN, "args": {"word": "valve"}},
        ]
    )

    first = harness.send(model, query="Make a word")

    assert first.status == "needs_info", first.message
    assert first.message == "I need some additional information to proceed:"
    assert [(q["field"], q["question"]) for q in first.followup_questions] == [("word", "Which word?")]
    assert harness.store[CONV]["missing_info"] == ["word"]
    assert harness.dispatched == []

    second = harness.send(model, followup_answers={"word": "valve"})

    assert second.status == "completed", second.message
    assert '"answers": {"word": "valve"}' in second.message
    assert [skill for _, skill, _ in harness.dispatched] == [PLAIN]
    assert harness.store[CONV]["conversation_history"][-2]["provided_inputs"] == {"word": "valve"}


def test_ask_user_stops_the_turn_before_a_model_that_keeps_calling_tools(harness) -> None:
    # The stub calls the next tool on every model turn, whatever the last response was.
    questions = [{"field": "word", "question": "Which word?"}]
    model = _StubLlm(
        calls=[
            {"name": agent_loop.ASK_USER_TOOL, "args": {"questions": questions}},
            {"name": PLAIN, "args": {"word": "valve"}},
        ]
    )

    first = harness.send(model, query="Make a word")

    assert first.status == "needs_info", first.message
    assert harness.dispatched == [], "a skill ran while the ask_user form was open"
    assert [call["name"] for call in harness.store[CONV]["pending_calls"]] == [agent_loop.ASK_USER_TOOL]

    second = harness.send(model, followup_answers={"word": "valve"})

    assert second.status == "completed", second.message
    assert [skill for _, skill, _ in harness.dispatched] == [PLAIN]


def test_free_text_answers_a_pending_ask_user(harness) -> None:
    questions = [{"field": "file", "question": "Which file?"}]
    model = _StubLlm(calls=[{"name": agent_loop.ASK_USER_TOOL, "args": {"questions": questions}}])

    assert harness.send(model, query="Analyze my data").status == "needs_info"
    response = harness.send(model, query="the quarterly one")

    assert response.status == "answer", response.message
    assert '"reply": "the quarterly one"' in response.message
    assert "the quarterly one" not in model.seen  # an answer, not a new user message


ROD = {
    "name": "rod_diameter",
    "description": "Rod diameter in mm.",
    "user_prompt": "What is the rod diameter?",
    "type": "number",
    "required": True,
}


def _input_required(*missing: Dict[str, Any]) -> Dict[str, Any]:
    """A call_a2a_agent INPUT_REQUIRED reply of the specialist's task task-7."""
    return {
        "status": "input_required",
        "input_required": {"missing_inputs": list(missing), "hint": "I need the rod diameter."},
        "_a2a_context_id": CONV,
        "_a2a_task_id": "task-7",
    }


def test_specialist_input_required_pauses_for_a_form_and_the_answer_resumes_its_task(harness) -> None:
    harness.replies[PLAIN] = [_input_required(ROD), {"skill_id": PLAIN, "result": {"answer": "made"}}]
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    first = harness.send(model, query="Make a valve")

    assert first.status == "needs_info", first.message
    assert first.message == "I need the rod diameter."
    [question] = first.followup_questions
    assert (question["field"], question["question"], question["type"]) == (
        "rod_diameter",
        "What is the rod diameter?",
        "number",
    )
    assert question["value_type"] == "number"
    assert harness.store[CONV]["awaiting_approval"] is False
    assert harness.store[CONV]["missing_info"] == ["rod_diameter"]

    second = harness.send(model, followup_answers={"rod_diameter": "12"})

    assert second.status == "completed", second.message
    assert len(harness.dispatched) == 2
    resumed = harness.dispatched[1][2]
    assert resumed["provided_inputs"] == {"rod_diameter": 12.0}
    assert resumed["_a2a_task_id"] == "task-7"
    assert resumed["_a2a_context_id"] == CONV
    assert json.loads(second.message.removeprefix("done: "))[PLAIN]["status"] == "succeeded"


def test_request_artifacts_reach_the_dispatch_and_a_specialist_error_reaches_the_model(harness) -> None:
    svg = {
        "artifact_id": "svg-1",
        "name": "valve.svg",
        "mime_type": "image/svg+xml",
        "uri": "deeplynx://organizations/1/projects/1/items/1",
    }
    png = {**svg, "artifact_id": "png-1", "name": "valve.png", "mime_type": "image/png"}
    harness.replies[PLAIN] = {"skill_id": PLAIN, "result": {"message": "converted"}, "artifacts": [png]}
    harness.replies[APPROVAL] = {"error": "agent down"}
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}, {"name": APPROVAL, "args": {"title": "SAR"}}])

    assert harness.send(model, query="Convert it, then review", artifacts=[svg]).status == "plan_ready"
    response = harness.send(model, plan_approved=True, artifacts=[svg])

    # The conversation's artifacts travel with each dispatch; the produced one reaches the model.
    assert [artifact["artifact_id"] for artifact in harness.dispatched[0][2]["artifacts"]] == ["svg-1"]
    results = json.loads(response.message.removeprefix("done: "))
    assert [artifact["artifact_id"] for artifact in results[PLAIN]["artifacts"]] == ["png-1"]
    assert results[APPROVAL] == {"status": "failed", "error": "agent down"}


def test_unavailable_capability_fails_the_call_without_dispatching(harness, monkeypatch) -> None:
    async def missing(skill_id: str) -> None:
        return None

    monkeypatch.setattr(adk_tools, "get_capability_cache", lambda: SimpleNamespace(get_capability_by_skill_id=missing))
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    response = harness.send(model, query="Make a valve")

    assert harness.dispatched == []
    assert "is not currently available" in response.message


def test_approval_without_a_pending_call_is_an_error(harness) -> None:
    response = harness.send(_StubLlm(), plan_approved=True)

    assert response.status == "error"
    assert harness.dispatched == []


def test_a_turn_runs_in_the_adk_session_of_the_verified_user(harness, monkeypatch) -> None:
    users: List[str] = []
    run_turn = agent_loop.run_turn

    async def spy(*args: Any, **kwargs: Any) -> agent_loop.TurnOutcome:
        users.append(kwargs["user_id"])
        return await run_turn(*args, **kwargs)

    monkeypatch.setattr(agent_loop, "run_turn", spy)
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])
    alice = UserIdentity(user_id="alice", claims={"sub": "alice"}, raw_token="unused")

    with identity_scope(alice):
        response = harness.send(model, query="Make a valve")

    assert response.status == "completed", response.message
    assert users == ["alice"]
    sessions = _in_memory_services(harness.agent)[0]
    app_name = normalize_producer_agent_id(harness.agent.agent_name)

    async def session(user_id: str) -> Any:
        return await sessions.get_session(app_name=app_name, user_id=user_id, session_id=CONV)

    assert asyncio.run(session("alice")) is not None
    assert asyncio.run(session("local")) is None


def test_a_turn_outside_an_identity_scope_runs_as_local(harness, monkeypatch) -> None:
    users: List[str] = []
    run_turn = agent_loop.run_turn

    async def spy(*args: Any, **kwargs: Any) -> agent_loop.TurnOutcome:
        users.append(kwargs["user_id"])
        return await run_turn(*args, **kwargs)

    monkeypatch.setattr(agent_loop, "run_turn", spy)

    assert harness.send(_StubLlm(), query="hi").status == "answer"
    assert users == ["local"]


def test_a_skill_turn_records_its_inputs_and_results_for_the_next_turn(harness, monkeypatch) -> None:
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    first = harness.send(model, query="Make a valve")

    stored = harness.store[CONV]
    assert first.status == "completed"
    assert stored["turn_tool_inputs"] == {PLAIN: {"word": "valve"}}
    assert stored["turn_tool_results"] == {PLAIN: {"skill_id": PLAIN, "result": {"answer": "plain_skill ran"}}}
    report = stored["conversation_history"][-1]
    assert (report["type"], report["tool_inputs"]) == ("final_report", stored["turn_tool_inputs"])

    # The next turn's prompt lists the newest inputs; the first turn's prompt did not.
    digest = 'plain_skill: {"word": "valve"}'
    assert model.instructions and not any(digest in text for text in model.instructions)
    later = _StubLlm()
    second = harness.send(later, query="Thanks")

    assert second.status == "answer"
    assert later.instructions and all(digest in text for text in later.instructions)
    # The digest is temp state: neither stored in the session nor in any event's state delta.
    session = _session(harness.agent)
    key = adk_tools.RECENT_SKILL_INPUTS_KEY
    assert key == "temp:recent_skill_inputs"
    assert key not in session.state
    assert all(key not in (event.actions.state_delta or {}) for event in session.events)
    # A new user turn starts its records empty.
    assert harness.store[CONV]["turn_tool_inputs"] == {}
    assert harness.store[CONV]["turn_tool_results"] == {}


def _session(agent: Any) -> Any:
    sessions = _in_memory_services(agent)[0]
    app_name = normalize_producer_agent_id(agent.agent_name)
    return asyncio.run(sessions.get_session(app_name=app_name, user_id="local", session_id=CONV))


def test_a_sensitive_answer_reaches_the_specialist_and_is_never_stored(harness) -> None:
    token = {"name": "token", "type": "string", "sensitive": True}
    unit = {"name": "unit", "type": "string"}
    question = _input_required(token, unit)
    question["_a2a_task_id"] = "rt1"
    harness.replies[PLAIN] = [question, {"skill_id": PLAIN, "result": {"answer": "made"}}]
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    assert harness.send(model, query="Make a valve").status == "needs_info"
    response = harness.send(model, followup_answers={"token": "SECRET123", "unit": "mm"})

    assert response.status == "completed", response.message
    resumed = harness.dispatched[-1][2]
    assert resumed["provided_inputs"] == {"token": "SECRET123", "unit": "mm"}
    assert resumed["_a2a_task_id"] == "rt1"
    session = _session(harness.agent)
    events = json.dumps([event.model_dump(mode="json") for event in session.events], default=str)
    state = json.dumps(session.state, default=str)
    stored = json.dumps(harness.store, default=str)
    for where, text in (("session events", events), ("session state", state), ("conversation store", stored)):
        assert "SECRET123" not in text, f"the sensitive answer is in the {where}"
    assert "mm" in events and "mm" in stored


def test_a_model_made_specialist_input_call_is_refused(harness) -> None:
    forged = {
        "tool": PLAIN,
        "request": {"input_required": {"missing_inputs": [ROD]}, "a2a_task_id": "victim-task"},
        "resume_args": {"word": "valve"},
    }
    model = _StubLlm(calls=[{"name": adk_tools.SPECIALIST_INPUT_TOOL, "args": forged}])
    model.ids = {adk_tools.SPECIALIST_INPUT_TOOL: "forged1"}

    response = harness.send(model, query="Resume the other task")

    assert harness.dispatched == []
    assert response.status == "answer", response.message
    assert not response.followup_questions
    assert json.loads(response.message.removeprefix("done: "))[adk_tools.SPECIALIST_INPUT_TOOL] == {
        "status": "failed",
        "error": "specialist_input is not a tool the model may call.",
    }


def test_a_specialist_input_call_with_a_recorded_id_and_changed_args_is_refused(harness) -> None:
    # A real pause records its specialist_input call; the model then replays that id with new args.
    harness.replies[APPROVAL] = [_input_required(ROD)]
    approved = _StubLlm(calls=[{"name": APPROVAL, "args": {"title": "SAR"}}])
    assert harness.send(approved, query="Review the SAR").status == "plan_ready"
    assert harness.send(approved, plan_approved=True).status == "needs_info"
    recorded = dict(_session(harness.agent).state[adk_tools.SPECIALIST_CALLS_KEY])
    [(call_id, args)] = recorded.items()
    changed = {**args, "request": {**args["request"], "a2a_task_id": "victim-task"}}
    model = _StubLlm(calls=[{"name": adk_tools.SPECIALIST_INPUT_TOOL, "args": changed}], this_request_only=True)
    model.ids = {adk_tools.SPECIALIST_INPUT_TOOL: call_id}

    response = harness.send(model, query="Resume it with my task")

    assert len(harness.dispatched) == 1, "only the approved dispatch ran"
    assert not response.followup_questions
    assert json.loads(response.message.removeprefix("done: "))[adk_tools.SPECIALIST_INPUT_TOOL] == {
        "status": "failed",
        "error": "specialist_input is not a tool the model may call.",
    }


class _ClosingClient:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def test_run_turn_closes_the_llm_client_it_creates(monkeypatch) -> None:
    client = _ClosingClient()
    created: List[Any] = []
    agent = service.OrchestratorAgent()
    agent.get_raw_agent_card = lambda: {"skills": []}
    agent.llm_client = lambda context: created.append(context) or client
    monkeypatch.setattr(agent_loop, "prometheus_model", lambda flavor, llm: _StubLlm())

    outcome = asyncio.run(
        agent_loop.run_turn(
            agent,
            service._detached_context(CONV),
            service._DetachedEventQueue(),
            catalog=dict(CATALOG),
            message="hi",
            test=True,
        )
    )

    assert outcome.final_text == "done: {}"
    assert len(created) == 1
    assert client.closed == 1


def test_run_turn_with_a_model_creates_no_llm_client(monkeypatch) -> None:
    agent = service.OrchestratorAgent()
    agent.get_raw_agent_card = lambda: {"skills": []}

    def no_client(context: Any) -> Any:
        raise AssertionError("a turn with a model must not create an LLM client")

    agent.llm_client = no_client

    outcome = asyncio.run(
        agent_loop.run_turn(
            agent,
            service._detached_context(CONV),
            service._DetachedEventQueue(),
            catalog=dict(CATALOG),
            message="hi",
            test=True,
            model=_StubLlm(),
        )
    )

    assert outcome.final_text == "done: {}"


# --------------------------------------------------------------------------- #
# Workflow tools
# --------------------------------------------------------------------------- #

WORKFLOW_ID = "thermal_quick_check"


def _compiled_workflow(version: str = "1.0.0") -> Any:
    raw = {
        "id": WORKFLOW_ID,
        "name": "Quick Thermal Check",
        "version": version,
        "description": "Thermal screening.",
        "matching": {"patterns": ["thermal"]},
        "inputs": {"required": ["material_id"]},
        "execution": {"mode": "sequential", "on_error": "fail_fast"},
        "steps": [
            {"id": "screen", "skill_id": "analyze_thermal", "params": {"material_id": {"from": "input.material_id"}}},
        ],
    }
    return compile_workflow(raw=raw, source_path=Path("test.yaml"), strict=False)


@pytest.fixture
def workflow(harness, monkeypatch) -> List[tuple]:
    """One compiled workflow in the catalog and the registry; returns the recorded step calls."""
    compiled = _compiled_workflow()
    steps: List[tuple] = []

    async def invoke(skill_id: str, payload: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        steps.append((skill_id, payload, conversation_id))
        return {"skill_id": skill_id, "result": {"answer": "Screened."}}

    registry = SimpleNamespace(get=lambda workflow_id, version=None: compiled, list_all=lambda: [compiled])
    name = workflow_tool_name(WORKFLOW_ID)
    harness.catalog[name] = agent_loop.ToolSpec(
        name=name,
        kind="workflow",
        target=WORKFLOW_ID,
        label="Quick Thermal Check",
        agent_name="workflow",
        description="Thermal screening.",
        parameters={"type": "object", "properties": {"material_id": {"type": "string"}}},
        user_required=("material_id",),
    )
    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", True)
    monkeypatch.setattr(adk_tools, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(chat_flow, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(
        adk_tools, "workflow_tool", lambda spec, compiled: adk_tools.WorkflowTool(spec, compiled, invoke)
    )
    return steps


def test_explicit_workflow_start_runs_the_workflow_tool(harness, workflow) -> None:
    name = workflow_tool_name(WORKFLOW_ID)
    model = _StubLlm(calls=[{"name": name, "args": {"material_id": "SS316"}}])

    response = harness.send(model, workflow_id=WORKFLOW_ID, followup_answers={"material_id": "SS316"})

    assert response.status == "completed", response.message
    assert [(skill, payload["material_id"], conv) for skill, payload, conv in workflow] == [
        ("analyze_thermal", "SS316", CONV)
    ]
    assert any(f"[Use the {name} tool for this request." in text for text in model.seen)
    assert json.loads(response.message.removeprefix("done: "))[name]["status"] == "succeeded"


def test_workflow_slash_command_starts_the_workflow(harness, workflow) -> None:
    name = workflow_tool_name(WORKFLOW_ID)
    model = _StubLlm(calls=[{"name": name, "args": {"material_id": "A36"}}])

    response = harness.send(model, query=f"/{WORKFLOW_ID} A36")

    assert response.status == "completed", response.message
    assert [payload["material_id"] for _, payload, _ in workflow] == ["A36"]
    assert any(text.startswith("A36") for text in model.seen)


@pytest.fixture
def versions(harness, monkeypatch) -> List[tuple]:
    """Workflow versions 1.0.0 and 2.0.0 (the newest, in the catalog); records (version, skill) per step."""
    compiled = {version: _compiled_workflow(version) for version in ("1.0.0", "2.0.0")}
    steps: List[tuple] = []

    def make_invoke(version: str):
        async def invoke(skill_id: str, payload: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
            steps.append((version, skill_id))
            return {"skill_id": skill_id, "result": {"answer": f"Screened by {version}."}}

        return invoke

    def get(workflow_id: str, version: Optional[str] = None) -> Any:
        return compiled.get(version) if version else compiled["2.0.0"]

    registry = SimpleNamespace(get=get, list_all=lambda: [compiled["2.0.0"]])
    name = workflow_tool_name(WORKFLOW_ID)
    harness.catalog[name] = agent_loop.ToolSpec(
        name=name,
        kind="workflow",
        target=WORKFLOW_ID,
        label="Quick Thermal Check",
        agent_name="workflow",
        description="Thermal screening.",
        parameters={"type": "object", "properties": {"material_id": {"type": "string"}}},
        user_required=("material_id",),
        requires_approval=True,
    )
    real_to_adk = adk_tools.to_adk_workflow
    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", True)
    monkeypatch.setattr(adk_tools, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(chat_flow, "get_workflow_registry", lambda: registry)
    # Each compiled version runs its own recording steps, so the run shows which version ran.
    monkeypatch.setattr(adk_tools, "to_adk_workflow", lambda wf, invoke: real_to_adk(wf, make_invoke(wf.version)))
    monkeypatch.setattr(
        adk_tools, "workflow_tool", lambda spec, compiled: adk_tools.WorkflowTool(spec, compiled, make_invoke("x"))
    )
    return steps


def test_catalog_start_of_an_older_version_shows_and_runs_that_version(harness, versions) -> None:
    name = workflow_tool_name(WORKFLOW_ID)
    model = _StubLlm(calls=[{"name": name, "args": {"material_id": "SS316"}}])

    first = harness.send(
        model,
        workflow_id=WORKFLOW_ID,
        workflow_version="1.0.0",
        selection_source="catalog",
        followup_answers={"material_id": "SS316"},
    )

    assert first.status == "plan_ready", first.message
    assert (first.plan["workflow_id"], first.plan["selection_source"], first.plan["workflow_version"]) == (
        WORKFLOW_ID,
        "catalog",
        "1.0.0",
    )
    assert versions == []

    second = harness.send(model, plan_approved=True)

    assert second.status == "completed", second.message
    assert versions == [("1.0.0", "analyze_thermal")]
    assert second.tool_results["analyze_thermal"] == {"answer": "Screened by 1.0.0."}


def test_slash_command_start_shows_slash_command_as_the_source(harness, versions) -> None:
    name = workflow_tool_name(WORKFLOW_ID)
    model = _StubLlm(calls=[{"name": name, "args": {"material_id": "A36"}}])

    response = harness.send(model, query=f"/{WORKFLOW_ID} A36")

    assert response.status == "plan_ready", response.message
    assert response.plan["selection_source"] == "slash_command"
    assert "workflow_version" not in response.plan


def test_an_unavailable_workflow_version_fails_the_call(harness, versions) -> None:
    name = workflow_tool_name(WORKFLOW_ID)
    model = _StubLlm(calls=[{"name": name, "args": {"material_id": "SS316"}}])

    assert harness.send(model, workflow_id=WORKFLOW_ID, workflow_version="9.9.9").status == "plan_ready"
    response = harness.send(model, plan_approved=True)

    assert versions == []
    result = json.loads(response.message.removeprefix("done: "))[name]
    assert result == {"status": "failed", "error": f"Workflow '{WORKFLOW_ID}' version 9.9.9 is unavailable."}


def test_unknown_workflow_start_is_an_error(harness) -> None:
    response = harness.send(_StubLlm(), workflow_id="no.such.workflow")

    assert response.status == "error"
    assert "no.such.workflow" in response.message


# --------------------------------------------------------------------------- #
# The A2A dispatch: parent record metadata and cancel forwarding
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


class _A2AClient:
    """httpx.AsyncClient stand-in: records each JSON-RPC post and answers it by method."""

    def __init__(self, posts: List[Dict[str, Any]], answers: Dict[str, Any]) -> None:
        self.posts = posts
        self.answers = answers

    async def __aenter__(self) -> "_A2AClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, endpoint: str, json: Dict[str, Any], headers: Dict[str, str]) -> _Response:
        self.posts.append(json)
        answer = self.answers[json["method"]]
        if isinstance(answer, BaseException):
            raise answer
        return _Response(answer)


def _completed(text: Dict[str, Any]) -> Dict[str, Any]:
    status = {"state": "TASK_STATE_COMPLETED", "message": {"parts": [{"text": json.dumps(text)}]}}
    return {"result": {"task": {"id": "t1", "status": status}}}


def _install_client(monkeypatch, answers: Dict[str, Any]) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    monkeypatch.setattr(tool_discovery.httpx, "AsyncClient", lambda *args, **kwargs: _A2AClient(posts, answers))
    return posts


def test_dispatch_carries_the_parent_execution_record(monkeypatch) -> None:
    posts = _install_client(monkeypatch, {"SendMessage": _completed({"answer": "ok"})})

    async def call() -> Dict[str, Any]:
        tool_discovery.parent_execution_record_id.set(42)
        return await tool_discovery.call_a2a_agent(AGENT_URL, PLAIN, conversation_id=CONV, word="valve")

    assert asyncio.run(call()) == {"answer": "ok"}
    message = posts[0]["params"]["message"]
    assert message["metadata"][PARENT_EXECUTION_RECORD_METADATA_KEY] == 42
    assert message["contextId"] == CONV
    assert json.loads(message["parts"][0]["text"]) == {"conversation_id": CONV, "word": "valve"}


def test_dispatch_without_a_parent_record_sends_none(monkeypatch) -> None:
    posts = _install_client(monkeypatch, {"SendMessage": _completed({"answer": "ok"})})

    asyncio.run(tool_discovery.call_a2a_agent(AGENT_URL, PLAIN, word="valve"))

    assert PARENT_EXECUTION_RECORD_METADATA_KEY not in posts[0]["params"]["message"]["metadata"]


def test_a_cancelled_new_dispatch_cancels_no_remote_task(monkeypatch) -> None:
    # A new task is not named until the reply, so nothing is guessed from the shared context.
    posts = _install_client(monkeypatch, {"SendMessage": asyncio.CancelledError()})

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tool_discovery.call_a2a_agent(AGENT_URL, PLAIN, conversation_id=CONV))

    assert [post["method"] for post in posts] == ["SendMessage"]


def test_cancelled_resume_cancels_the_task_it_continues(monkeypatch) -> None:
    posts = _install_client(monkeypatch, {"SendMessage": asyncio.CancelledError(), "CancelTask": {}})

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tool_discovery.call_a2a_agent(AGENT_URL, PLAIN, conversation_id=CONV, _a2a_task_id="task-7"))

    assert [(post["method"], post["params"]) for post in posts[1:]] == [("CancelTask", {"id": "task-7"})]


def test_a_failed_cancel_forward_never_masks_the_cancel(monkeypatch) -> None:
    posts = _install_client(
        monkeypatch, {"SendMessage": asyncio.CancelledError(), "CancelTask": RuntimeError("registry down")}
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tool_discovery.call_a2a_agent(AGENT_URL, PLAIN, conversation_id=CONV, _a2a_task_id="task-7"))

    assert [post["method"] for post in posts] == ["SendMessage", "CancelTask"]


# --------------------------------------------------------------------------- #
# Lifespan: detached turns resume where they stopped
# --------------------------------------------------------------------------- #


@pytest.fixture
def task_graph_fake(monkeypatch) -> SimpleNamespace:
    """service.task_graph with in-memory resumable nodes, states and results."""
    nodes: List[task_graph.TaskNode] = []
    states: Dict[str, Dict[str, Any]] = {}
    results: Dict[str, Dict[str, Any]] = {}

    def update_own_state(conversation_id: str, task_id: str, **fields: Any) -> None:
        states[task_id] = fields

    def store_result(conversation_id: str, task_id: str, payload: Dict[str, Any]) -> None:
        results[task_id] = payload

    monkeypatch.setattr(service.task_graph, "list_resumable_nodes", lambda: list(nodes))
    monkeypatch.setattr(service.task_graph, "update_own_state", update_own_state)
    monkeypatch.setattr(service.task_graph, "store_result", store_result)
    return SimpleNamespace(nodes=nodes, states=states, results=results)


def _node(task_id: str) -> task_graph.TaskNode:
    return task_graph.TaskNode(
        task_id=task_id, conversation_id=CONV, invocation_id=f"inv-{task_id}", adk_session_id="session-1"
    )


def test_lifespan_resumes_each_unfinished_turn(task_graph_fake, monkeypatch) -> None:
    task_graph_fake.nodes.extend([_node("done"), _node("paused"), _node("broken")])
    resumed: List[Dict[str, Any]] = []

    async def catalog() -> Dict[str, agent_loop.ToolSpec]:
        return dict(CATALOG)

    async def run_turn(agent, context, event_queue, **kwargs: Any) -> agent_loop.TurnOutcome:
        resumed.append({"session": context.context_id, "task": context.task_id, **kwargs})
        if kwargs["invocation_id"] == "inv-broken":
            raise RuntimeError("session lost")
        outcome = agent_loop.TurnOutcome(session_id="session-1", invocation_id=kwargs["invocation_id"])
        if kwargs["invocation_id"] == "inv-paused":
            outcome.pending_calls = [{"id": "c1", "name": agent_loop.ASK_USER_TOOL, "args": {}}]
        else:
            outcome.final_text = "Finished while you were away."
        return outcome

    async def refresh(trigger: str = "manual") -> Dict[str, Any]:
        return {}

    monkeypatch.setattr(agent_loop, "build_tool_catalog", catalog)
    monkeypatch.setattr(agent_loop, "run_turn", run_turn)
    monkeypatch.setattr(runtime, "refresh_dynamic_components", refresh)
    monkeypatch.setattr(runtime, "DISCOVERY_REFRESH_SECONDS", 0)
    agent = service.OrchestratorAgent()

    async def serve() -> None:
        async with agent.lifespan(None):
            await asyncio.gather(*list(service._BACKGROUND_TASKS))

    asyncio.run(serve())

    assert sorted(run["invocation_id"] for run in resumed) == ["inv-broken", "inv-done", "inv-paused"]
    assert all(run["session"] == "session-1" and run["message"] is None for run in resumed)
    assert {run["invocation_id"]: run["task"] for run in resumed}["inv-done"] == "done"
    assert task_graph_fake.states["done"] == {"own_state": "completed"}
    assert task_graph_fake.results["done"] == {
        "conversation_id": CONV,
        "status": "answer",
        "message": "Finished while you were away.",
    }
    assert task_graph_fake.states["paused"] == {"own_state": "input-required"}
    assert task_graph_fake.states["broken"] == {"own_state": "failed", "error": "session lost"}
    assert set(task_graph_fake.results) == {"done"}


def test_resume_runs_in_the_adk_session_of_the_user_who_started_the_turn(task_graph_fake, monkeypatch) -> None:
    owned = _node("owned")
    owned.adk_user_id = "alice"
    resumed: Dict[str, str] = {}

    async def catalog() -> Dict[str, agent_loop.ToolSpec]:
        return dict(CATALOG)

    async def run_turn(agent, context, event_queue, **kwargs: Any) -> agent_loop.TurnOutcome:
        resumed[kwargs["invocation_id"]] = kwargs["user_id"]
        return agent_loop.TurnOutcome(session_id="session-1", invocation_id=kwargs["invocation_id"], final_text="ok")

    monkeypatch.setattr(agent_loop, "build_tool_catalog", catalog)
    monkeypatch.setattr(agent_loop, "run_turn", run_turn)
    agent = service.OrchestratorAgent()

    asyncio.run(agent._resume_node(owned))
    asyncio.run(agent._resume_node(_node("legacy")))

    assert resumed == {"inv-owned": "alice", "inv-legacy": "local"}
    assert task_graph_fake.states["owned"] == {"own_state": "completed"}


def test_a_stored_node_without_an_adk_user_id_still_loads(monkeypatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(task_graph, "_client", lambda: fake)
    stored = _node("old").to_dict()
    del stored["adk_user_id"]  # written before the field existed
    fake.set("tasks:node:" + CONV + ":old", json.dumps(stored))

    node = task_graph.get_node(CONV, "old")

    assert node is not None
    assert node.adk_user_id is None
    assert (node.task_id, node.invocation_id, node.adk_session_id) == ("old", "inv-old", "session-1")


def test_lifespan_serves_and_shuts_down_when_the_task_graph_is_unreachable(monkeypatch) -> None:
    def unreachable() -> List[task_graph.TaskNode]:
        raise RuntimeError("valkey down")

    async def refresh(trigger: str = "manual") -> Dict[str, Any]:
        refreshed.append(trigger)
        return {}

    async def never(*args: Any, **kwargs: Any) -> agent_loop.TurnOutcome:
        raise AssertionError("no turn resumes when the task graph cannot be read")

    refreshed: List[str] = []
    monkeypatch.setattr(service.task_graph, "list_resumable_nodes", unreachable)
    monkeypatch.setattr(runtime, "refresh_dynamic_components", refresh)
    monkeypatch.setattr(runtime, "DISCOVERY_REFRESH_SECONDS", 0)
    monkeypatch.setattr(agent_loop, "run_turn", never)
    pending: List[int] = []

    async def serve() -> None:
        async with service.OrchestratorAgent().lifespan(None):
            pending.append(len(service._BACKGROUND_TASKS))

    asyncio.run(serve())

    # Startup ran, no resume task was scheduled, and the app served and shut down.
    assert refreshed == ["startup"]
    assert pending == [0]


# --------------------------------------------------------------------------- #
# Uploaded files: stored, partly stored, or not stored
# --------------------------------------------------------------------------- #


def _upload(name: str) -> Dict[str, Any]:
    return {"name": name, "mime_type": "text/csv", "size_bytes": 3, "upload_id": "a" * 32}


@pytest.fixture
def uploads(monkeypatch) -> SimpleNamespace:
    statuses: List[str] = []
    stored: List[str] = []

    class _Llm:
        async def __aenter__(self) -> "_Llm":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    async def infer(query: str, files: List[Any], llm: Any) -> Dict[str, str]:
        raise RuntimeError("no model")

    async def upload(agent, files, descriptions, context, event_queue, config, user_id=None):
        return [
            SimpleNamespace(
                artifact_id=f"art-{f.name}",
                name=f.name,
                to_dict=lambda f=f: {
                    "artifact_id": f"art-{f.name}",
                    "name": f.name,
                    "description": descriptions[f.name],
                },
            )
            for f in files
            if f.name in stored
        ]

    async def send_status_update(self, **kwargs: Any) -> None:
        statuses.append(kwargs["message"])

    monkeypatch.setattr(file_upload_handler, "infer_file_descriptions", infer)
    monkeypatch.setattr(file_upload_handler, "upload_files_to_deeplynx", upload)
    monkeypatch.setattr(ConnectionConfig, "from_env", classmethod(lambda cls: SimpleNamespace()))
    monkeypatch.setattr(runtime, "create_llm", lambda: _Llm())
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)
    monkeypatch.setattr(service.OrchestratorAgent, "send_status_update", send_status_update)
    agent = service.OrchestratorAgent()

    def handle(payload: Dict[str, Any]) -> List[str]:
        return asyncio.run(
            agent._handle_uploaded_files(payload, CONV, service._detached_context(CONV), service._DetachedEventQueue())
        )

    return SimpleNamespace(statuses=statuses, stored=stored, handle=handle)


def test_uploaded_files_are_stored_with_fallback_descriptions(uploads) -> None:
    uploads.stored.extend(["a.csv", "b.csv"])
    payload: Dict[str, Any] = {"query": "Summarize", "uploaded_files": [_upload("a.csv"), _upload("b.csv"), "junk"]}

    assert uploads.handle(payload) == ["art-a.csv", "art-b.csv"]
    assert [artifact["artifact_id"] for artifact in payload["artifacts"]] == ["art-a.csv", "art-b.csv"]
    assert payload["artifacts"][0]["description"].endswith(": a.csv")
    assert "received_files" not in payload
    assert "uploaded_files" not in payload


def test_partly_stored_uploads_name_the_files_that_were_not_stored(uploads) -> None:
    uploads.stored.append("a.csv")
    payload: Dict[str, Any] = {"uploaded_files": [_upload("a.csv"), _upload("b.csv")]}

    assert uploads.handle(payload) == ["art-a.csv"]
    assert [item["name"] for item in payload["received_files"]] == ["b.csv"]
    assert uploads.statuses[-1] == "1 of 2 file(s) could not be saved to DeepLynx."


def test_uploads_that_are_not_stored_are_reported_as_received(uploads) -> None:
    payload: Dict[str, Any] = {"uploaded_files": [_upload("a.csv")]}

    assert uploads.handle(payload) == []
    assert [item["name"] for item in payload["received_files"]] == ["a.csv"]
    assert uploads.statuses[-1] == "1 file(s) could not be saved to DeepLynx."


def test_uploads_without_storage_configuration_are_reported_as_received(uploads, monkeypatch) -> None:
    def unconfigured(cls: Any) -> None:
        raise ValueError("DEEPLYNX_BASE_URL is not set")

    monkeypatch.setattr(ConnectionConfig, "from_env", classmethod(unconfigured))
    payload: Dict[str, Any] = {"uploaded_files": [_upload("a.csv")]}

    assert uploads.handle(payload) == []
    assert [item["name"] for item in payload["received_files"]] == ["a.csv"]
    assert "DeepLynx storage is not configured" in uploads.statuses[-1]


# --------------------------------------------------------------------------- #
# The A2A wire: every pause ends with one final COMPLETED status of one Part.text
# --------------------------------------------------------------------------- #


def _backend_parser() -> Any:
    """The backend's parser of the client-agent's final status (app/a2a_client.py, by path)."""
    path = Path(__file__).resolve().parents[3] / "backend" / "app" / "a2a_client.py"
    spec = importlib.util.spec_from_file_location("backend_a2a_client", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.A2AClient("http://client-agent:8000", "unused")


class _RecordingQueue:
    def __init__(self) -> None:
        self.events: List[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture
def wire(harness, monkeypatch) -> SimpleNamespace:
    """service._execute behind the SDK executor, on the harness's stub model and fakes."""
    monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")
    monkeypatch.delenv("PROMETHEUS_BACKGROUND_DEADLINE_SECONDS", raising=False)
    monkeypatch.setattr(runtime, "_tools_cache", [object()])
    monkeypatch.setattr(service, "get_conversation", lambda conv_id: None)
    monkeypatch.setattr(service, "record_turn_artifacts", lambda *args: None)
    monkeypatch.setattr(ownership, "assert_conversation_owner", lambda *args: None)
    monkeypatch.setattr(ownership, "record_conversation_owner", lambda *args: None)

    async def no_upload(self, *args: Any, **kwargs: Any) -> List[str]:
        return []

    monkeypatch.setattr(service.OrchestratorAgent, "_handle_uploaded_files", no_upload)
    harness.agent.list_artifact_references = lambda *args, **kwargs: []
    models: List[_StubLlm] = []
    run_turn = agent_loop.run_turn

    async def stub_run_turn(*args: Any, **kwargs: Any) -> agent_loop.TurnOutcome:
        # _execute binds a production AdkRun; run its turn in memory on the stub model.
        return await run_turn(*args, **{**kwargs, "test": True, "model": models[-1]})

    monkeypatch.setattr(agent_loop, "run_turn", stub_run_turn)
    executor = DelegatingPrometheusAgentExecutor(agent_name="Client Agent", execute_fn=harness.agent._execute)

    def execute(model: _StubLlm, query: str) -> List[Dict[str, Any]]:
        models.append(model)
        queue = _RecordingQueue()
        message = Message(
            message_id="m1",
            role=Role.ROLE_USER,
            parts=[Part(text=json.dumps({"query": query, "conversation_id": CONV}))],
            context_id=CONV,
        )
        context = RequestContext(
            ServerCallContext(), request=SendMessageRequest(message=message), task_id="task-1", context_id=CONV
        )
        asyncio.run(executor.execute(context, queue))
        return [MessageToDict(event) for event in queue.events]

    return SimpleNamespace(execute=execute, parser=_backend_parser())


def _final_payload(wire: SimpleNamespace, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The final status's one Part.text, checked like the backend checks it."""
    finals = [event for event in events if event.get("status", {}).get("state") == "TASK_STATE_COMPLETED"]
    assert len(finals) == 1, "exactly one final COMPLETED status"
    assert finals[0] is events[-1]
    [part] = finals[0]["status"]["message"]["parts"]
    assert set(part) == {"text"}, f"the final status carries a text part only, not {sorted(part)}"
    # The client-agent emits no wire status of its own beyond the base's working and progress.
    assert all("data" not in p for event in events for p in event.get("status", {}).get("message", {}).get("parts", []))
    parsed = wire.parser._extract_from_status(finals[0])
    payload = json.loads(part["text"])
    assert parsed.status == payload["status"]
    return payload


def test_ask_user_pause_ends_with_one_needs_info_text_status(harness, wire) -> None:
    questions = [{"field": "word", "question": "Which word?"}]
    model = _StubLlm(calls=[{"name": agent_loop.ASK_USER_TOOL, "args": {"questions": questions}}])

    payload = _final_payload(wire, wire.execute(model, "Make a word"))

    assert payload["status"] == "needs_info"
    assert payload["message"] == "I need some additional information to proceed:"
    assert [question["field"] for question in payload["followup_questions"]] == ["word"]
    assert "plan" not in payload
    assert harness.store[CONV]["awaiting_approval"] is False


def test_specialist_pause_ends_with_one_needs_info_text_status(harness, wire) -> None:
    harness.replies[PLAIN] = _input_required(ROD)
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    payload = _final_payload(wire, wire.execute(model, "Make a valve"))

    assert payload["status"] == "needs_info"
    assert payload["message"] == "I need the rod diameter."
    assert [(q["field"], q["type"]) for q in payload["followup_questions"]] == [("rod_diameter", "number")]
    assert "plan" not in payload
    assert harness.store[CONV]["awaiting_approval"] is False


def test_approval_pause_ends_with_one_plan_ready_text_status(harness, wire) -> None:
    model = _StubLlm(calls=[{"name": APPROVAL, "args": {"title": "SAR"}}])

    payload = _final_payload(wire, wire.execute(model, "Review the SAR"))

    assert payload["status"] == "plan_ready"
    assert payload["plan"]["skills"] == [APPROVAL]
    assert payload["plan"]["steps"][0]["description"] == 'approval_skill(title="SAR")'
    assert "followup_questions" not in payload
    assert harness.store[CONV]["awaiting_approval"] is True
    assert harness.dispatched == []


# --------------------------------------------------------------------------- #
# Task Graph: one child node per dispatch, under the turn's root
# --------------------------------------------------------------------------- #


def _children() -> Dict[str, task_graph.TaskNode]:
    """The skill nodes of the conversation, by skill."""
    return {node.skill: node for node in task_graph.list_nodes(CONV) if node.parent_task_id}


def test_a_successful_dispatch_completes_its_node_with_the_first_artifact(harness) -> None:
    harness.replies[PLAIN] = {"skill_id": PLAIN, "result": {"ok": True}, "artifacts": [{"artifact_id": "svg-1"}]}
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    harness.send(model, turn=True, query="Make a valve")

    node = _children()[PLAIN]
    assert (node.own_state, node.result_ref, node.agent) == ("completed", "svg-1", None)
    [root] = task_graph.build_tree(CONV)
    assert root["state"] == "completed"
    assert [child["task_id"] for child in root["children"]] == [node.task_id]


def test_a_failed_dispatch_fails_its_node_with_the_error(harness) -> None:
    harness.replies[PLAIN] = {"error": "agent down"}
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    harness.send(model, turn=True, query="Make a valve")

    node = _children()[PLAIN]
    assert (node.own_state, node.error) == ("failed", "agent down")


def test_a_specialist_question_resumes_the_same_node(harness) -> None:
    harness.replies[PLAIN] = [_input_required(ROD), {"skill_id": PLAIN, "result": {"answer": "made"}}]
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    assert harness.send(model, turn=True, query="Make a valve").status == "needs_info"
    paused = _children()[PLAIN]
    assert paused.own_state == "input-required"
    [root] = task_graph.build_tree(CONV)
    assert root["state"] not in task_graph.TERMINAL_STATES

    assert harness.send(model, turn=True, followup_answers={"rod_diameter": "12"}).status == "completed"

    nodes = task_graph.list_nodes(CONV)
    assert len(nodes) == 2, "the answer resumes the paused node instead of creating one"
    resumed = _children()[PLAIN]
    assert (resumed.task_id, resumed.own_state) == (paused.task_id, "completed")


def test_an_approved_skill_that_asks_for_input_pauses_for_the_form_then_resumes_its_node(harness) -> None:
    json_type = {"name": "json_type", "type": "string"}
    question = _input_required(json_type)
    question["_a2a_task_id"], question["_a2a_context_id"] = "rt1", "c"
    harness.replies[APPROVAL] = [question, {"skill_id": APPROVAL, "result": {"answer": "reviewed"}}]
    model = _StubLlm(calls=[{"name": APPROVAL, "args": {"title": "SAR"}}])

    assert harness.send(model, turn=True, query="Review the SAR").status == "plan_ready"
    assert harness.dispatched == []

    asked = harness.send(model, turn=True, plan_approved=True)

    # The approved run dispatched once, and the specialist's question is the open form.
    assert asked.status == "needs_info", asked.message
    assert asked.followup_questions[0]["field"] == "json_type"
    assert "provided_inputs" not in harness.dispatched[0][2]
    [pending] = harness.store[CONV]["pending_calls"]
    assert pending["name"] == "adk_request_confirmation"
    assert pending["args"]["originalFunctionCall"]["name"] == "specialist_input"
    paused = _children()[APPROVAL]
    assert paused.own_state == "input-required"

    answered = harness.send(model, turn=True, followup_answers={"json_type": "list"})

    assert answered.status == "completed", answered.message
    assert len(harness.dispatched) == 2
    resumed = harness.dispatched[-1][2]
    assert resumed["provided_inputs"] == {"json_type": "list"}
    assert resumed["_a2a_task_id"] == "rt1"
    node = _children()[APPROVAL]
    assert (node.task_id, node.own_state) == (paused.task_id, "completed")
    assert len(task_graph.list_nodes(CONV)) == 2


def test_a_superseded_specialist_question_cancels_its_node(harness) -> None:
    harness.replies[PLAIN] = _input_required(ROD)
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    assert harness.send(model, turn=True, query="Make a valve").status == "needs_info"
    model.calls = []
    response = harness.send(model, turn=True, query="Forget it, say hi")

    assert response.status == "answer", response.message
    assert response.message == "done: {}"
    assert _children()[PLAIN].own_state == "canceled"
    assert len(harness.dispatched) == 1


def test_a_cancelled_dispatch_cancels_its_node(harness) -> None:
    harness.replies[PLAIN] = asyncio.CancelledError()
    model = _StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}])

    # ADK ends the root node's run on the cancel (it logs it); the turn gets no tool result.
    response = harness.send(model, turn=True, query="Make a valve")

    assert _children()[PLAIN].own_state == "canceled"
    assert response.message == ""


def test_tasks_command_counts_the_turns_and_their_state(harness) -> None:
    # Two turns: one finished, one paused on a specialist's question.
    harness.catalog["mesh_skill"] = _skill("mesh_skill", "size")
    harness.replies["mesh_skill"] = _input_required(ROD)
    harness.send(_StubLlm(calls=[{"name": PLAIN, "args": {"word": "valve"}}]), turn=True, query="Make a valve")
    asked = _StubLlm(calls=[{"name": "mesh_skill", "args": {"size": "fine"}}])
    assert harness.send(asked, turn=True, query="Mesh it").status == "needs_info"

    response = harness.send(_StubLlm(), query="/tasks")

    assert response.status == "answer"
    assert response.message.startswith("Tasks (2 total, 1 active)")
    # A root whose child waits on the user is still active ("working", task_graph._effective_state).
    trees = {tree["title"]: tree for tree in response.message_metadata["tasks"]}
    assert (trees["Make a valve"]["state"], trees["Mesh it"]["state"]) == ("completed", "working")
    assert [child["state"] for child in trees["Mesh it"]["children"]] == ["input-required"]
    assert debug_commands._format_tasks_list([]).startswith("Tasks (0 total, 0 active)")
