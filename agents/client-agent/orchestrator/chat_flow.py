from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from prometheus_api.agent import PrometheusAgent

from artifact_handling import merge_artifacts_into_context, summarize_artifacts_for_context
from conversation_store import get_conversation, store_conversation

from . import runtime
from .debug_commands import _maybe_handle_slash_command
from .execution import (
    _format_plan_for_response,
    _latest_conversation_entry,
    apply_followup_answers_to_state,
    ask_followup_dynamic,
    execute_approved_plan,
    execute_current_plan,
    extract_followup_answers_from_query,
    resume_pending_subagent_requests,
)
from .models import AgentState, ConversationRequest, ConversationResponse
from .planning_flow import compile_query_plan, extract_refinement_param_updates, plan_analysis, show_plan


def _needs_info_response(
    conv_id: str,
    state: AgentState,
    hint: str = "I need some additional information to proceed:",
) -> ConversationResponse:
    """Persist state and return a needs_info response with followup questions."""
    store_conversation(conv_id, state)
    runtime.store_status_update(conv_id, "Awaiting additional parameters.", final=True)
    latest = _latest_conversation_entry(state)
    return ConversationResponse(
        conversation_id=conv_id,
        status="needs_info",
        message=PrometheusAgent.pending_hint(state.get("pending_subagent_requests"), hint),
        followup_questions=latest.get("questions", []),
    )


def _completed_response(conv_id: str, state: AgentState) -> ConversationResponse:
    """Persist state and return a completed response with the final report."""
    store_conversation(conv_id, state)
    runtime.store_status_update(conv_id, "Response ready.", final=True)
    return ConversationResponse(
        conversation_id=conv_id,
        status="completed",
        message=state.get("final_report", ""),
        report=state.get("final_report", ""),
        tool_results=state.get("tool_results"),
    )


def _error_response(conv_id: str, log_msg: str, user_msg: str) -> ConversationResponse:
    """Store error status and return an error response."""
    runtime.store_status_update(conv_id, log_msg, final=True)
    return ConversationResponse(conversation_id=conv_id, status="error", message=user_msg)


async def chat(request: ConversationRequest) -> ConversationResponse:
    """Conversational A2A orchestration endpoint.

    Every frontend message arrives here. Slash commands are handled first via a
    deterministic path that never invokes the planner LLM. Otherwise, the
    function dispatches to one of three high-level paths based on what the
    request carries:

    ┌─────────────────────────────────────────────────────────────────────────┐
    │ PATH A — CONTINUATION (existing conversation + followup/approval)       │
    │                                                                         │
    │  plan_approved=True  → execute_approved_plan → _completed_response      │
    │                      (may loop back to _needs_info if agent requests     │
    │                       more input mid-execution)                          │
    │                                                                         │
    │  followup_answers    → apply_followup_answers_to_state                  │
    │                      → still missing?  → _needs_info_response           │
    │                      → requires approval? → plan_ready response         │
    │                      → otherwise → execute_current_plan                 │
    │                                  → _completed_response                  │
    │                                                                         │
    │  (query only, pending followup) → ask_followup_dynamic                  │
    │                                 → _needs_info_response                  │
    ├─────────────────────────────────────────────────────────────────────────┤
    │ PATH B — NEW QUERY (new conversation, or new query on existing one)     │
    │                                                                         │
    │  compile_query_plan → planner LLM selects skill(s) or workflow          │
    │                                                                         │
    │    outcome=fallback       → answer response (no subagent called)        │
    │    missing params         → ask_followup_dynamic → _needs_info_response │
    │    requires_approval=True → plan_ready response (await approval)        │
    │    ready to execute       → execute_current_plan → _completed_response  │
    └─────────────────────────────────────────────────────────────────────────┘

    Key helpers:
      compile_query_plan   — calls planner.compile_plan_with_tools (LLM-based)
      execute_current_plan — invokes selected skills via A2A, collects results
      ask_followup_dynamic — converts missing param paths into UI form fields
      _needs_info_response — persist + return ConversationResponse(needs_info)
      _completed_response  — persist + return ConversationResponse(completed)
    """
    conv_id = request.conversation_id or str(uuid.uuid4())
    runtime.store_status_update(conv_id, "Received request.")
    request_artifacts = summarize_artifacts_for_context(request.artifacts)
    existing_state = get_conversation(conv_id)
    slash_response = await _maybe_handle_slash_command(
        request,
        conv_id,
        existing_state if isinstance(existing_state, dict) else None,
        request_artifacts,
    )
    if slash_response is not None:
        return slash_response

    has_pending_followup = bool(existing_state and existing_state.get("missing_info"))
    is_new_query_on_existing = (
        bool(existing_state)
        and bool(request.query)
        and not request.followup_answers
        and not request.plan_approved
        and not has_pending_followup
    )

    # Existing conversation continuation path: followup answers and/or approval.
    if existing_state and not is_new_query_on_existing:
        state = existing_state
        if request_artifacts:
            state["context"] = merge_artifacts_into_context(state.get("context", {}), request_artifacts)

        if request.plan_approved:
            state["awaiting_approval"] = False
            try:
                final_state = await execute_approved_plan(state)
                if final_state.get("missing_info"):
                    followup_result = await ask_followup_dynamic(final_state)
                    for key, value in followup_result.items():
                        if value is not None:
                            final_state[key] = value
                    return _needs_info_response(conv_id, final_state)
                return _completed_response(conv_id, final_state)
            except Exception as exc:
                return _error_response(conv_id, f"Execution failed: {exc}", f"Error during analysis: {exc}")

        followup_answers = dict(request.followup_answers or {})

        if request.query and not followup_answers and has_pending_followup and not state.get("pending_subagent_requests"):
            state["conversation_history"] = state.get("conversation_history", []) + [{
                "role": "user",
                "content": request.query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
            extracted = await extract_followup_answers_from_query(state, request.query)
            followup_answers.update(extracted)

        if followup_answers:
            routing_decision = state.get("routing_decision", {}) or {}
            requires_approval = routing_decision.get("requires_approval", False)

            try:
                if state.get("pending_subagent_requests"):
                    state = await resume_pending_subagent_requests(state, followup_answers)
                    if state.get("missing_info"):
                        followup_result = await ask_followup_dynamic(state)
                        for key, value in followup_result.items():
                            if value is not None:
                                state[key] = value
                        return _needs_info_response(conv_id, state)
                    # For workflow templates, re-execute the full plan so downstream steps run.
                    rd = state.get("routing_decision", {}) or {}
                    if rd.get("workflow_type") == "workflow_template":
                        for key, value in followup_answers.items():
                            rd.setdefault("extracted_params", {})[key] = value
                        state["routing_decision"] = rd
                        final_state = await execute_current_plan(
                            state, start_message="Resuming workflow with provided parameters."
                        )
                        if final_state.get("missing_info"):
                            followup_result = await ask_followup_dynamic(final_state)
                            for key, value in followup_result.items():
                                if value is not None:
                                    final_state[key] = value
                            return _needs_info_response(conv_id, final_state)
                        return _completed_response(conv_id, final_state)
                    return _completed_response(conv_id, state)

                if routing_decision:
                    state = await apply_followup_answers_to_state(
                        state,
                        followup_answers,
                        query=request.query or "",
                    )
                    routing_decision = state.get("routing_decision", {}) or routing_decision

                if state.get("missing_info"):
                    followup_result = await ask_followup_dynamic(state)
                    for key, value in followup_result.items():
                        if value is not None:
                            state[key] = value
                    return _needs_info_response(conv_id, state)

                if not requires_approval:
                    runtime.store_status_update(conv_id, "All required parameters resolved. Executing skills.")
                    final_state = await execute_current_plan(
                        state,
                        start_message="All required parameters resolved. Starting execution.",
                    )
                    if final_state.get("missing_info"):
                        followup_result = await ask_followup_dynamic(final_state)
                        for key, value in followup_result.items():
                            if value is not None:
                                final_state[key] = value
                        return _needs_info_response(conv_id, final_state)
                    return _completed_response(conv_id, final_state)

                plan_result = plan_analysis(state)
                for key, value in plan_result.items():
                    if value is not None:
                        state[key] = value
                show_plan_result = show_plan(state)
                for key, value in show_plan_result.items():
                    if value is not None:
                        state[key] = value

                store_conversation(conv_id, state)
                runtime.store_status_update(conv_id, "Plan ready for approval.", final=True)
                return ConversationResponse(
                    conversation_id=conv_id,
                    status="plan_ready",
                    message="I've created an analysis plan. Please review and approve:",
                    plan=_format_plan_for_response(state),
                )
            except Exception as exc:
                return _error_response(conv_id, f"Follow-up processing failed: {exc}", f"Error processing followup: {exc}")

        if request.query and has_pending_followup:
            followup_result = await ask_followup_dynamic(state)
            for key, value in followup_result.items():
                if value is not None:
                    state[key] = value
            return _needs_info_response(conv_id, state, "I still need a few details to proceed:")

        return _error_response(conv_id, "No actionable follow-up input was provided.", "No actionable followup input was provided.")

    # New query path: new conversation or new query in existing conversation.
    if not request.query and not request.workflow_id:
        return _error_response(
            conv_id,
            "A query or explicit workflow selection is required for a new planning turn.",
            "A query or explicit workflow selection is required for a new planning turn.",
        )

    if is_new_query_on_existing:
        old_history = existing_state.get("conversation_history", [])
        previous_context = existing_state.get("context", {})
    else:
        old_history = []
        previous_context = {}

    forced_workflow_id = request.workflow_id
    forced_workflow_version = request.workflow_version
    forced_selection_source = request.selection_source
    seed_params: Dict[str, Any] = {}
    if isinstance(request.followup_answers, dict):
        seed_params.update(request.followup_answers)

    # Plan-refinement turns (while awaiting approval) should preserve the
    # selected template and previously extracted parameters.
    if is_new_query_on_existing and isinstance(existing_state, dict) and existing_state.get("awaiting_approval"):
        existing_routing = existing_state.get("routing_decision", {}) or {}
        existing_plan = existing_state.get("plan", {}) or {}

        if not forced_workflow_id:
            forced_workflow_id = (
                existing_plan.get("workflow_id")
                or existing_routing.get("workflow_id")
            )
        if not forced_workflow_version:
            forced_workflow_version = (
                existing_plan.get("workflow_version")
                or existing_routing.get("workflow_version")
            )
        if not forced_selection_source:
            forced_selection_source = (
                existing_routing.get("selection_source")
                or "plan_refinement"
            )

        existing_params = existing_routing.get("extracted_params")
        if isinstance(existing_params, dict):
            merged_seed = dict(existing_params)
            merged_seed.update(seed_params)
            seed_params = merged_seed

        if request.query:
            runtime.store_status_update(conv_id, "Applying refinement instructions to plan parameters.")
            refinement_updates = await extract_refinement_param_updates(
                query=request.query,
                routing_decision=existing_routing,
                conversation_history=old_history,
            )
            if refinement_updates:
                merged_seed = dict(seed_params)
                merged_seed.update(refinement_updates)
                seed_params = merged_seed
                runtime.store_status_update(conv_id, "Refinement parameters applied.")

    previous_context = merge_artifacts_into_context(previous_context, request_artifacts)
    # Inject transient per-turn upload IDs so planner and resolve_artifact_inputs can see them.
    if request.newly_uploaded_artifact_ids:
        previous_context["newly_uploaded_artifact_ids"] = list(request.newly_uploaded_artifact_ids)
    if request.received_files:
        previous_context["received_files"] = list(request.received_files)

    state: AgentState = {
        "messages": [],
        "conversation_id": conv_id,
        "user_query": request.query or f"Start workflow {request.workflow_id}",
        "conversation_history": old_history + [{
            "role": "user",
            "content": request.query or f"Start workflow {request.workflow_id}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
        "routing_decision": None,
        "plan": None,
        "missing_info": [],
        "awaiting_approval": False,
        "pending_subagent_requests": [],
        "material_id": None,
        "analysis_types": None,
        "context": previous_context,
        "question": None,
        "tool_results": {},
        "final_report": None,
    }

    if isinstance(request.followup_answers, dict) and request.followup_answers:
        merged_context = dict(state.get("context", {}) or {})
        for key, value in request.followup_answers.items():
            if key.startswith("context."):
                merged_context[key.split(".", 1)[1]] = value
            elif key != "material_id":
                merged_context[key] = value
        if merged_context:
            state["context"] = merged_context

    try:
        planning_update = await compile_query_plan(
            state,
            explicit_workflow_id=forced_workflow_id,
            explicit_workflow_version=forced_workflow_version,
            selection_source=forced_selection_source or ("catalog" if forced_workflow_id else None),
            seed_params=seed_params or None,
        )
        if planning_update.get("is_fallback"):
            fallback_message = planning_update.get("fallback_message", "I couldn't plan a capability invocation for that query.")
            state["conversation_history"] = state.get("conversation_history", []) + [{
                "role": "assistant",
                "content": fallback_message,
                "type": "fallback_response",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
            store_conversation(conv_id, state)
            runtime.store_status_update(conv_id, "Responded without subagent execution.", final=True)
            return ConversationResponse(
                conversation_id=conv_id,
                status="answer",
                message=fallback_message,
                response_text=fallback_message,
            )

        for key, value in planning_update.items():
            if key in {"is_fallback", "fallback_message", "planner_message"}:
                continue
            if value is not None:
                state[key] = value

        if state.get("missing_info"):
            followup_result = await ask_followup_dynamic(state)
            for key, value in followup_result.items():
                if value is not None:
                    state[key] = value
            return _needs_info_response(conv_id, state)

        routing_decision = state.get("routing_decision", {}) or {}
        requires_approval = routing_decision.get("requires_approval", False)

        if requires_approval:
            plan_result = plan_analysis(state)
            for key, value in plan_result.items():
                if value is not None:
                    state[key] = value
            show_plan_result = show_plan(state)
            for key, value in show_plan_result.items():
                if value is not None:
                    state[key] = value
            store_conversation(conv_id, state)
            runtime.store_status_update(conv_id, "Plan ready for approval.", final=True)
            return ConversationResponse(
                conversation_id=conv_id,
                status="plan_ready",
                message=planning_update.get("planner_message") or "I've created an analysis plan. Please review and approve:",
                plan=_format_plan_for_response(state),
            )

        runtime.store_status_update(conv_id, "All required parameters resolved. Executing skills.")
        final_state = await execute_current_plan(
            state,
            start_message="All required parameters resolved. Starting execution.",
        )
        if final_state.get("missing_info"):
            followup_result = await ask_followup_dynamic(final_state)
            for key, value in followup_result.items():
                if value is not None:
                    final_state[key] = value
            return _needs_info_response(conv_id, final_state)
        return _completed_response(conv_id, final_state)
    except Exception as exc:
        return _error_response(conv_id, f"Request failed: {exc}", f"Error processing request: {exc}")
