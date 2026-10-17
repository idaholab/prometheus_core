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
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

from artifact_handling import merge_artifacts_into_context, summarize_artifacts_for_context
from conversation_store import get_conversation, store_conversation
from workflow_library import find_workflow_by_command, get_workflow_registry

from . import agent_loop, runtime
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


def _respond(conv_id: str, state: AgentState, outcome: agent_loop.LoopOutcome) -> ConversationResponse:
    """Persist state and map a loop outcome onto the frontend contract."""
    state["awaiting_approval"] = outcome.kind == "needs_approval"
    state["missing_info"] = [str(q["field"]) for q in outcome.questions] if outcome.kind == "needs_info" else []
    state["plan"] = outcome.plan
    state["final_report"] = None

    if outcome.kind == "needs_info":
        # Content = the live reply text, so artifacts made before the pause are stamped
        # on this entry (conversation_store.stamp_turn_artifacts) and restore with it.
        _append_history(
            state,
            {
                "role": "assistant",
                "type": "followup_questions",
                "content": outcome.message,
                "questions": outcome.questions,
            },
        )
        store_conversation(conv_id, state)
        runtime.store_status_update(conv_id, "Awaiting additional information.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="needs_info",
            message=outcome.message,
            followup_questions=outcome.questions,
        )

    if outcome.kind == "needs_approval":
        _append_history(state, {"role": "assistant", "type": "plan", "content": outcome.message, "plan": outcome.plan})
        store_conversation(conv_id, state)
        runtime.store_status_update(conv_id, "Plan ready for approval.", final=True)
        return ConversationResponse(
            conversation_id=conv_id,
            status="plan_ready",
            message=outcome.message,
            plan=outcome.plan,
        )

    if outcome.kind == "error":
        _append_history(state, {"role": "assistant", "type": "error", "content": outcome.message})
        store_conversation(conv_id, state)
        runtime.store_status_update(conv_id, outcome.message, final=True)
        return ConversationResponse(conversation_id=conv_id, status="error", message=outcome.message)

    tool_results = dict(state.get("turn_tool_results") or {})
    entry: Dict[str, Any] = {"role": "assistant", "content": outcome.message}
    if tool_results:
        entry.update(
            type="final_report",
            tool_inputs=copy.deepcopy(state.get("turn_tool_inputs") or {}),
            tool_results=tool_results,
        )
        state["final_report"] = outcome.message
    else:
        entry["type"] = "answer"
    _append_history(state, entry)
    store_conversation(conv_id, state)
    runtime.store_status_update(conv_id, "Response ready.", final=True)

    if not tool_results:
        return ConversationResponse(
            conversation_id=conv_id,
            status="answer",
            message=outcome.message,
            response_text=outcome.message,
        )
    suggestions = [item["suggested_query"] for item in collect_suggested_queries(tool_results, limit=3)]
    return ConversationResponse(
        conversation_id=conv_id,
        status="completed",
        message=outcome.message,
        report=outcome.message,
        tool_results=tool_results,
        message_metadata={"follow_up_suggestions": suggestions} if suggestions else None,
    )


def _error_response(conv_id: str, log_msg: str, user_msg: str) -> ConversationResponse:
    """Store error status and return an error response."""
    runtime.store_status_update(conv_id, log_msg, final=True)
    return ConversationResponse(conversation_id=conv_id, status="error", message=user_msg)


async def chat(request: ConversationRequest) -> ConversationResponse:
    """Conversational A2A orchestration endpoint.

    Debug slash commands are answered without the LLM. Everything else maps the
    request onto the tool-calling loop (``agent_loop``):

    - with pending tool calls (a form, an approval, or a specialist's
      INPUT_REQUIRED is outstanding): ``plan_rejected`` closes them,
      ``plan_approved`` releases them, ``followup_answers`` fill them, and free
      text answers ``ask_user`` or supersedes the rest;
    - an explicit workflow selection (slash command, catalog start) injects a
      call to that workflow's tool;
    - otherwise the query starts a new user turn.

    Then ``agent_loop.advance`` runs until a final answer or the next pause.
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

        if request.plan_rejected and has_pending:
            agent_loop.reject_pending(state)
            message = "Plan rejected. Tell me how you'd like to proceed."
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
            agent_loop.approve_pending(state)
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
                agent_loop.apply_reply(state, query)
                agent_loop.commit_batch(state)
            await _start_user_turn(state, request, query)
            if args:
                # Free-text arguments: let the model fill the workflow's inputs from them.
                state["llm_messages"][-1]["content"] += f"\n\n[Use the {spec.name} tool for this request.]"
            else:
                agent_loop.inject_tool_call(
                    state,
                    catalog,
                    spec,
                    dict(request.followup_answers or {}),
                    f"Running workflow '{workflow_id}'.",
                    workflow_version=request.workflow_version,
                    selection_source=request.selection_source or ("slash_command" if workflow_slash else None),
                )
        elif request.followup_answers and has_pending:
            sensitive = agent_loop.sensitive_fields(state)
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
            agent_loop.apply_answers(state, catalog, request.followup_answers)
        elif request.query and has_pending:
            _append_history(state, {"role": "user", "content": request.query})
            agent_loop.apply_reply(
                state,
                request.query,
                uploaded_artifact_ids=request.newly_uploaded_artifact_ids,
                received_files=request.received_files,
            )
        elif request.query:
            await _start_user_turn(state, request, request.query)
        elif request.plan_approved or request.followup_answers:
            return _error_response(
                conv_id,
                "Nothing is awaiting approval or input.",
                "There is no pending step awaiting approval or input in this conversation.",
            )
        else:
            return _error_response(conv_id, "A query is required.", "A query is required.")

        outcome = await agent_loop.advance(state, catalog)
        return _respond(conv_id, state, outcome)
    except Exception as exc:
        logger.exception("Request failed for conversation %s", conv_id)
        # Keep completed tool calls and produced artifacts in the transcript.
        store_conversation(conv_id, state)
        return _error_response(conv_id, f"Request failed: {exc}", f"Error processing request: {exc}")
