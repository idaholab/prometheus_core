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

from __future__ import annotations

import copy
import json
import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, cast

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from google.adk.agents.invocation_context import new_invocation_context_id
from google.adk.utils._function_call_names import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.models import BaseLlm
from google.genai import types
from prometheus_api.agent import PrometheusAgent
from prometheus_api.agent.events import context_id as event_context_id
from prometheus_api.agent.events import context_task_id
from prometheus_api.agent.identity import current_user_id

from artifact_handling import merge_artifacts_into_context, summarize_artifacts_for_context
from conversation_store import get_conversation, store_conversation
from workflow_library import find_workflow_by_command, get_workflow_registry

from . import adk_tools, agent_loop, runtime
from .debug_commands import (
    SUPPORTED_SLASH_COMMANDS,
    _maybe_handle_slash_command,
    _parse_slash_command,
)
from .models import AgentState, ConversationRequest, ConversationResponse
from .utils import collect_suggested_queries

logger = logging.getLogger(__name__)

_TITLE_MAX_CHARS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _maybe_generate_title(state: AgentState, conv_id: str) -> None:
    """Best-effort short title for a new conversation, via the ``small`` LLM flavor.

    Runs once per conversation (skipped once ``state["title"]`` is set — carried
    forward on every later turn by the caller). Chat history (frontend sidebar)
    is the only consumer; a failure here must never fail the turn, so every
    error is swallowed and logged, leaving the title unset (the backend falls
    back to the raw first query for display in that case).
    """
    if state.get("title"):
        return
    query = str(state.get("user_query") or "").strip()
    if not query:
        return
    try:
        async with runtime.create_llm() as llm:
            response = await llm.small(
                "Write a short title (max 6 words, no quotes or trailing "
                "punctuation) summarizing the topic of this user message, for "
                f"a chat history list:\n\n{query}",
                max_tokens=32,
            )
        title = " ".join(response.text.strip().strip("\"'").splitlines()).strip()
        if title:
            state["title"] = title[:_TITLE_MAX_CHARS]
    except Exception as exc:
        logger.warning("Title generation failed for conversation %s: %s", conv_id, exc)


def _workflow_slash_selection(query: Optional[str]) -> Optional[Dict[str, str]]:
    parsed = _parse_slash_command(query)
    if parsed is None:
        return None
    command, args = parsed
    if command in SUPPORTED_SLASH_COMMANDS or not runtime.ENABLE_WORKFLOW_LIBRARY:
        return None

    workflow = find_workflow_by_command(command, get_workflow_registry().list_all())
    if workflow is None:
        return None

    return {"workflow_id": workflow.definition.id, "args": args}


def _new_state(conv_id: str, existing: Optional[Dict[str, Any]]) -> AgentState:
    """Load the conversation record, filling any field a fresh conversation lacks."""
    state: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    state["conversation_id"] = conv_id
    state.setdefault("user_query", None)
    state.setdefault("title", None)
    state.setdefault("conversation_history", [])
    state.setdefault("context", {})
    state.setdefault("llm_messages", [])
    state.setdefault("pending_calls", [])
    state.setdefault("pending_note", "")
    state.setdefault("turn_tool_results", {})
    state.setdefault("turn_tool_inputs", {})
    state.setdefault("plan", None)
    state.setdefault("missing_info", [])
    state.setdefault("awaiting_approval", False)
    state.setdefault("final_report", None)
    # The ADK run of the latest turn; ``adk_invocation_id`` resumes it while calls are pending.
    state.setdefault("adk_session_id", None)
    state.setdefault("adk_invocation_id", None)
    # The user's explicit workflow pick of the latest turn (catalog or slash command).
    state.setdefault("workflow_selection", None)
    return cast(AgentState, state)


def _append_history(state: AgentState, entry: Dict[str, Any]) -> None:
    state["conversation_history"] = [*state.get("conversation_history", []), {**entry, "timestamp": _now()}]


def _store_turn_start(state: AgentState) -> None:
    """Best-effort store as a user turn starts, so Chat History lists the conversation
    while the turn runs. The final store merges over it by turn (conversation_store)."""
    conv_id = state["conversation_id"] or ""
    try:
        store_conversation(conv_id, state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Turn-start store failed for conversation %s: %s", conv_id, exc)


async def _start_user_turn(state: AgentState, request: ConversationRequest, query: str) -> None:
    _append_history(state, {"role": "user", "content": query})
    state["user_query"] = query
    _store_turn_start(state)
    await _maybe_generate_title(state, state["conversation_id"] or "")
    agent_loop.begin_user_turn(
        state,
        query,
        uploaded_artifact_ids=request.newly_uploaded_artifact_ids,
        received_files=request.received_files,
    )


def _specialist_request(call: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The confirmation payload of a specialist's INPUT_REQUIRED pause, or ``None``."""
    if call["name"] != REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
        return None
    payload = (call["args"].get("toolConfirmation") or {}).get("payload")
    return payload if isinstance(payload, dict) and adk_tools.SPECIALIST_INPUT_KEY in payload else None


def _is_approval(call: Mapping[str, Any]) -> bool:
    return call["name"] == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME and _specialist_request(call) is None


def _missing_inputs(call: Mapping[str, Any]) -> List[Dict[str, Any]]:
    request = _specialist_request(call) or {}
    return list((request.get(adk_tools.SPECIALIST_INPUT_KEY) or {}).get("missing_inputs") or [])


def _plan(
    outcome: agent_loop.TurnOutcome,
    catalog: Mapping[str, agent_loop.ToolSpec],
    selection: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The plan card of the calls an ADK approval pause holds; *selection* is the user's explicit workflow pick."""
    calls = [call["args"].get("originalFunctionCall") or {} for call in outcome.pending_calls if _is_approval(call)]
    steps: List[Dict[str, Any]] = []
    targets: List[str] = []
    duration = 0
    workflow: Optional[agent_loop.ToolSpec] = None
    for call in calls:
        spec = catalog.get(str(call.get("name") or ""))
        if spec is None:
            continue
        duration += spec.expected_duration_seconds
        targets.append(spec.target)
        if spec.kind == "workflow" and workflow is None:
            workflow = spec
        arguments = ", ".join(
            f"{key}={json.dumps(value, default=str)}" for key, value in (call.get("args") or {}).items()
        )
        steps.append(
            {
                "name": spec.label,
                "agent": spec.agent_name,
                "description": agent_loop._truncate(f"{spec.target}({arguments})", 400),
            }
        )
    plan: Dict[str, Any] = {
        "intent": outcome.final_text or "Review the next step(s) before they run.",
        "steps": steps,
        "skills": targets,
        "workflow_type": "parallel" if len(steps) > 1 else "single",
        "estimated_duration_seconds": duration,
        "required_params": [],
        "param_metadata": {},
    }
    if workflow is not None:
        # PlanViewerElement's details panel shows which workflow runs and who chose it.
        plan["workflow_id"] = workflow.target
        picked = selection is not None and selection.get("workflow_id") == workflow.target
        plan["selection_source"] = (selection or {}).get("source") if picked else "model"
        if picked and (selection or {}).get("version"):
            plan["workflow_version"] = selection["version"]
    return plan


def _questions(outcome: agent_loop.TurnOutcome) -> List[Dict[str, Any]]:
    """The form of the paused ``ask_user`` calls and specialist requests; one field answers every call asking it."""
    questions: Dict[str, Dict[str, Any]] = {}
    for call in outcome.pending_calls:
        if call["name"] == agent_loop.ASK_USER_TOOL:
            for question in agent_loop._normalize_questions(call["args"].get("questions")):
                questions.setdefault(question["field"], question)
        for item in _missing_inputs(call):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            kind = str(item.get("type") or "string").strip().lower()
            questions.setdefault(
                name,
                {
                    "field": name,
                    "question": item.get("user_prompt") or item.get("description") or name,
                    "description": item.get("description"),
                    "type": "select" if kind == "enum" or item.get("options") else _question_type(kind),
                    "options": item.get("options"),
                    "required": bool(item.get("required", True)),
                    "sensitive": bool(item.get("sensitive")),
                    "value_type": kind,
                },
            )
    return list(questions.values())


def _question_type(kind: str) -> str:
    if kind in {"number", "integer", "float"}:
        return "number"
    if kind == "boolean":
        return "checkbox"
    return "text"


def _sensitive_fields(state: AgentState) -> set[str]:
    """Names of the inputs pending specialists asked for as sensitive; never persisted."""
    return {
        str(item.get("name") or "")
        for call in state["pending_calls"]
        for item in _missing_inputs(call)
        if item.get("sensitive")
    }


def _coerced_answers(call: Mapping[str, Any], answers: Mapping[str, Any]) -> Dict[str, Any]:
    """The submitted *answers* to a specialist request's missing inputs, coerced to their types."""
    provided: Dict[str, Any] = {}
    for item in _missing_inputs(call):
        name = str(item.get("name") or "").strip()
        value = agent_loop.coerce_answer(answers.get(name), item.get("type")) if name else None
        if value is not None:
            provided[name] = value
    return provided


def _answer_response(
    call: Mapping[str, Any], answers: Mapping[str, Any], sensitive: set[str]
) -> Optional[Dict[str, Any]]:
    """The function response that answers *call* from submitted form *answers*, or ``None``.

    The response is stored in the ADK session, so it never holds a *sensitive* answer;
    those reach the tool out of band (``adk_tools.SENSITIVE_ANSWERS_KEY``).
    """
    if call["name"] == agent_loop.ASK_USER_TOOL:
        fields = {q["field"] for q in agent_loop._normalize_questions(call["args"].get("questions"))}
        return {
            "status": "answered",
            "answers": {name: value for name, value in answers.items() if name in fields and name not in sensitive},
        }
    request = _specialist_request(call)
    if request is None:
        return None
    provided = {name: value for name, value in _coerced_answers(call, answers).items() if name not in sensitive}
    return {"confirmed": True, "payload": {**request, "provided_inputs": provided}}


def _function_responses(state: AgentState, respond: Callable[[Mapping[str, Any]], Optional[Dict[str, Any]]]) -> types.Content:
    """The resume message: one function response per pending call that *respond* answers."""
    parts = []
    for call in state["pending_calls"]:
        response = respond(call)
        if response is not None:
            parts.append(types.Part(function_response=types.FunctionResponse(id=call["id"], name=call["name"], response=response)))
    return types.Content(role="user", parts=parts)


def _respond(
    conv_id: str,
    state: AgentState,
    outcome: agent_loop.TurnOutcome,
    catalog: Mapping[str, agent_loop.ToolSpec],
) -> ConversationResponse:
    """Persist state and map an ADK turn outcome onto the frontend contract."""
    state["adk_session_id"] = outcome.session_id
    state["adk_invocation_id"] = outcome.invocation_id
    state["pending_calls"] = outcome.pending_calls
    questions = _questions(outcome)
    state["awaiting_approval"] = any(_is_approval(call) for call in outcome.pending_calls) and not questions
    state["missing_info"] = [str(q["field"]) for q in questions]
    state["plan"] = _plan(outcome, catalog, state.get("workflow_selection")) if state["awaiting_approval"] else None
    state["final_report"] = None
    # The skill calls of this user turn (adk_tools records them in the ADK session).
    state["turn_tool_results"] = outcome.tool_results
    state["turn_tool_inputs"] = outcome.tool_inputs

    if questions:
        hints = [
            str(((_specialist_request(call) or {}).get(adk_tools.SPECIALIST_INPUT_KEY) or {}).get("hint") or "")
            for call in outcome.pending_calls
        ]
        message = outcome.final_text or next(filter(None, hints), "I need some additional information to proceed:")
        # Content = the live reply text, so artifacts made before the pause are stamped
        # on this entry (conversation_store.stamp_turn_artifacts) and restore with it.
        _append_history(
            state,
            {
                "role": "assistant",
                "type": "followup_questions",
                "content": message,
                "questions": questions,
            },
        )
        store_conversation(conv_id, state)
        runtime.store_status_update(conv_id, "Awaiting additional information.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="needs_info",
            message=message,
            followup_questions=questions,
        )

    if state["awaiting_approval"]:
        message = outcome.final_text or "Please review and approve the next step(s):"
        _append_history(state, {"role": "assistant", "type": "plan", "content": message, "plan": state["plan"]})
        store_conversation(conv_id, state)
        runtime.store_status_update(conv_id, "Plan ready for approval.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="plan_ready",
            message=message,
            plan=state["plan"],
        )

    message = outcome.final_text
    tool_results = dict(state.get("turn_tool_results") or {})
    entry: Dict[str, Any] = {"role": "assistant", "content": message}
    if tool_results:
        entry.update(
            type="final_report",
            tool_inputs=copy.deepcopy(state.get("turn_tool_inputs") or {}),
            tool_results=tool_results,
        )
        state["final_report"] = message
    else:
        entry["type"] = "answer"
    _append_history(state, entry)
    store_conversation(conv_id, state)
    runtime.store_status_update(conv_id, "Response ready.", final=True)

    if not tool_results:
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=message,
            response_text=message,
        )
    suggestions = [item["suggested_query"] for item in collect_suggested_queries(tool_results, limit=3)]
    return ConversationResponse(
        conversation_id=conv_id,
        status="completed",
        message=message,
        report=message,
        tool_results=tool_results,
        message_metadata={"follow_up_suggestions": suggestions} if suggestions else None,
    )


def _error_response(conv_id: str, log_msg: str, user_msg: str) -> ConversationResponse:
    """Store error status and return an error response."""
    runtime.store_status_update(conv_id, log_msg, final=True)
    return ConversationResponse(conversation_id=conv_id, status="error", message=user_msg)


def _ask_user_reply(reply: str) -> Callable[[Mapping[str, Any]], Optional[Dict[str, Any]]]:
    """Answer only the paused ``ask_user`` calls with *reply*."""
    return lambda call: {"status": "answered", "reply": reply} if call["name"] == agent_loop.ASK_USER_TOOL else None


def _closing_response(call: Mapping[str, Any]) -> Dict[str, Any]:
    """The response that closes *call* without running it (a rejection, or a reply that supersedes it)."""
    if call["name"] == agent_loop.ASK_USER_TOOL:
        return {"status": "not_executed", "message": "Not executed: the user started a new request."}
    request = _specialist_request(call)
    # A specialist request keeps its payload, so the tool knows the pause it closes.
    return {"confirmed": False, "payload": request} if request is not None else {"confirmed": False}


@dataclass
class AdkRun:
    """The A2A request a chat turn's ADK run serves, bound with :data:`adk_run` around ``chat()``."""

    agent: PrometheusAgent
    context: RequestContext
    event_queue: EventQueue
    # Filled with the run's ``invocation_id``, ``session_id`` and ``user_id`` as it
    # starts, so a detached turn can be resumed.
    ids: Dict[str, str] = field(default_factory=dict)
    # Passed to ``run_turn``: in-memory services and a stub model.
    test: bool = False
    model: Optional[BaseLlm] = None


adk_run: ContextVar[Optional[AdkRun]] = ContextVar("adk_run", default=None)


async def chat(request: ConversationRequest) -> ConversationResponse:
    """Conversational A2A orchestration endpoint.

    Debug slash commands are answered without the LLM. Everything else is one
    ADK run of the client agent (``agent_loop.run_turn``) for the A2A request
    bound in :data:`adk_run`:

    - with pending calls (an approval or an ``ask_user`` form is outstanding):
      ``plan_approved`` and ``plan_rejected`` answer the ``adk_request_confirmation``
      calls, ``followup_answers`` and free text answer ``ask_user``, and the paused
      invocation resumes;
    - an explicit workflow selection (slash command, catalog start) asks the
      model to call that workflow's tool;
    - otherwise the query starts a new invocation.
    """
    conv_id = request.conversation_id or str(uuid.uuid4())
    runtime.store_status_update(conv_id, "Received request.")
    request_artifacts = summarize_artifacts_for_context(request.artifacts)
    existing_state = get_conversation(conv_id)

    workflow_slash = _workflow_slash_selection(request.query)
    if workflow_slash is None:
        slash_response = await _maybe_handle_slash_command(
            request,
            conv_id,
            existing_state if isinstance(existing_state, dict) else None,
            request_artifacts,
        )
        if slash_response is not None:
            return slash_response

    state = _new_state(conv_id, existing_state)
    state["context"] = merge_artifacts_into_context(state.get("context") or {}, request_artifacts)
    has_pending = bool(state["pending_calls"])
    workflow_id = workflow_slash["workflow_id"] if workflow_slash else request.workflow_id

    try:
        catalog = await agent_loop.build_tool_catalog()

        async def run(
            message: str | types.Content,
            invocation_id: Optional[str] = None,
            extra_state: Optional[Dict[str, Any]] = None,
        ) -> agent_loop.TurnOutcome:
            bound = adk_run.get()
            if bound is None:
                raise RuntimeError("chat() needs the A2A request of its run bound in adk_run")
            invocation_id = invocation_id or new_invocation_context_id()
            # The ADK session belongs to the verified user; "local" only outside an identity scope.
            user_id = current_user_id() or "local"
            bound.ids.update(
                invocation_id=invocation_id,
                session_id=event_context_id(bound.context) or context_task_id(bound.context),
                user_id=user_id,
            )
            return await agent_loop.run_turn(
                bound.agent,
                bound.context,
                bound.event_queue,
                catalog=catalog,
                message=message,
                conversation_id=conv_id,
                conversation_context=state.get("context") or {},
                user_id=user_id,
                invocation_id=invocation_id,
                test=bound.test,
                model=bound.model,
                # The prompt's cross-turn skill inputs come from the conversation history,
                # which the ADK session does not hold; temp state is never stored.
                extra_state={
                    adk_tools.RECENT_SKILL_INPUTS_KEY: agent_loop.recent_skill_inputs(dict(state), catalog),
                    **(extra_state or {}),
                },
            )

        def resume(
            respond: Callable[[Mapping[str, Any]], Optional[Dict[str, Any]]],
            extra_state: Optional[Dict[str, Any]] = None,
        ) -> Any:
            return run(_function_responses(state, respond), state.get("adk_invocation_id"), extra_state)

        has_ask_user = any(call["name"] == agent_loop.ASK_USER_TOOL for call in state["pending_calls"])

        if request.plan_rejected and has_pending:
            outcome = await resume(_closing_response)
            if outcome.pending_calls:
                return _respond(conv_id, state, outcome, catalog)
            message = outcome.final_text or "Plan rejected. Tell me how you'd like to proceed."
            state["pending_calls"] = []
            state["awaiting_approval"] = False
            state["missing_info"] = []
            state["plan"] = None
            _append_history(state, {"role": "assistant", "type": "plan_rejected", "content": message})
            store_conversation(conv_id, state)
            runtime.store_status_update(conv_id, "Plan rejected by user.", final=True)
            return ConversationResponse(conversation_id=conv_id, status="answer", message=message)

        if request.plan_approved and has_pending:
            # Evidence only: no content, so a restored conversation shows no extra bubble.
            _append_history(state, {"role": "user", "type": "plan_approved"})
            outcome = await resume(lambda call: {"confirmed": True} if _is_approval(call) else None)
        elif workflow_id:
            spec = agent_loop.workflow_tool_for(catalog, workflow_id)
            if spec is None:
                return _error_response(
                    conv_id,
                    f"Workflow '{workflow_id}' is unavailable.",
                    f"Workflow '{workflow_id}' is unavailable.",
                )
            args = workflow_slash["args"] if workflow_slash else ""
            query = request.query if not workflow_slash else (args or f"Start workflow {workflow_id}")
            query = query or f"Start workflow {workflow_id}"
            if has_pending:
                # The explicit start supersedes the pause; the closing run's reply is not shown.
                await resume(_ask_user_reply(query) if has_ask_user else _closing_response)
            await _start_user_turn(state, request, query)
            # The model fills the workflow's inputs from the free text or the catalog form.
            hint = f"\n\n[Use the {spec.name} tool for this request."
            if request.followup_answers and not args:
                hint += f" Its arguments: {json.dumps(request.followup_answers, default=str)}"
            state["workflow_selection"] = {
                "workflow_id": workflow_id,
                "version": request.workflow_version,
                "source": request.selection_source or ("slash_command" if workflow_slash else "catalog"),
            }
            outcome = await run(
                state["llm_messages"][-1]["content"] + hint + "]",
                extra_state={adk_tools.WORKFLOW_SELECTION_KEY: state["workflow_selection"]},
            )
        elif request.followup_answers and has_pending:
            sensitive = _sensitive_fields(state)
            _append_history(
                state,
                {
                    "role": "user",
                    "content": request.query or "Provided requested inputs.",
                    "provided_inputs": {
                        name: copy.deepcopy(value)
                        for name, value in request.followup_answers.items()
                        if name not in sensitive
                    },
                },
            )
            answers = dict(request.followup_answers)
            secret = {
                name: value
                for call in state["pending_calls"]
                for name, value in _coerced_answers(call, answers).items()
                if name in sensitive
            }
            outcome = await resume(
                lambda call: _answer_response(call, answers, sensitive),
                {adk_tools.SENSITIVE_ANSWERS_KEY: secret} if secret else None,
            )
        elif request.query and has_pending:
            _append_history(state, {"role": "user", "content": request.query})
            reply = request.query + agent_loop.upload_note(
                state, request.newly_uploaded_artifact_ids, request.received_files
            )
            if has_ask_user:
                outcome = await resume(_ask_user_reply(reply))
            else:
                # Nothing asked for this reply: the paused calls close without running, and
                # the reply is a new request. The closing run's reply is not shown.
                await resume(_closing_response)
                await _start_user_turn(state, request, request.query)
                outcome = await run(state["llm_messages"][-1]["content"])
        elif request.query:
            await _start_user_turn(state, request, request.query)
            state["workflow_selection"] = None
            outcome = await run(
                state["llm_messages"][-1]["content"], extra_state={adk_tools.WORKFLOW_SELECTION_KEY: None}
            )
        elif request.plan_approved or request.followup_answers:
            return _error_response(
                conv_id,
                "Nothing is awaiting approval or input.",
                "There is no pending step awaiting approval or input in this conversation.",
            )
        else:
            return _error_response(conv_id, "A query is required.", "A query is required.")

        return _respond(conv_id, state, outcome, catalog)
    except Exception as exc:
        logger.exception("Request failed for conversation %s", conv_id)
        # Keep completed tool calls and produced artifacts in the transcript.
        store_conversation(conv_id, state)
        return _error_response(conv_id, f"Request failed: {exc}", f"Error processing request: {exc}")
