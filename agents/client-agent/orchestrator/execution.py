from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage

from capability_cache import get_capability_cache
from param_schema import flatten_schema_properties, get_nested_value, has_param_path
from workflow_library import execute_workflow, get_workflow_registry

from . import runtime
from .models import AgentState
from .parameters import (
    attach_artifact_context,
    extract_provided_context_maps,
    get_selected_skills,
    merge_context_map,
    order_skills_for_workflow,
    resolve_params_via_capability_metadata,
    resolve_user_required_params,
)
from .skills import invoke_skill
from .utils import (
    build_comparison_summary,
    collect_suggested_queries,
    enrich_material_params,
    extract_json_from_text,
    extract_material_ids_from_text,
    extract_result_text,
)


async def invoke_agent_generic(state: AgentState) -> Dict:
    """Generic agent invocation - calls any agent based on routing decision.

    This function implements fully dynamic agent invocation with support for
    different workflow types (single, parallel, sequential). The workflow type
    is determined by the routing decision based on capability metadata.

    Workflow types:
    - single: Invoke one skill
    - parallel: Invoke multiple skills concurrently
    - sequential: Invoke skills in order, passing results between them

    All invocation logic is generic and data-driven - there is no hardcoded
    knowledge of specific agents or skills.

    Args:
        state: Current workflow state with routing_decision

    Returns:
        State updates with tool_results and conversation_history
    """
    routing_decision = state.get("routing_decision", {})
    selected_skills = order_skills_for_workflow(routing_decision)
    params = attach_artifact_context(
        routing_decision.get("extracted_params", {}),
        state.get("context", {}),
    )
    workflow_type = routing_decision.get("workflow_type", "single")
    conversation_id = state.get("conversation_id", str(uuid.uuid4()))

    print(
        f"[DEBUG] invoke_agent_generic: workflow_type={workflow_type}, "
        f"skills={selected_skills}, params={params}"
    )
    runtime.store_status_update(
        conversation_id,
        f"Executing {len(selected_skills)} skill(s) with workflow mode '{workflow_type}'.",
    )

    if not selected_skills:
        runtime.store_status_update(conversation_id, "No skills selected for execution.", final=True)
        return {
            "conversation_history": state.get("conversation_history", []) + [{
                "role": "assistant",
                "content": "I couldn't determine which agent to invoke. Please try rephrasing your request.",
                "type": "error",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }],
            "awaiting_approval": False
        }

    try:
        # Execute skills based on workflow type
        if workflow_type == "parallel" and len(selected_skills) > 1:
            # Parallel: invoke all skills concurrently
            invocation_results = await asyncio.gather(
                *[invoke_skill(skill_id, params, conversation_id) for skill_id in selected_skills]
            )
        elif workflow_type == "sequential" and len(selected_skills) > 1:
            # Sequential: invoke skills in order, passing results between them
            invocation_results = []
            previous_results: Dict[str, Any] = {}
            for skill_id in selected_skills:
                invoke_params = dict(params)
                if previous_results:
                    # Pass upstream results to downstream skills
                    invoke_params["upstream_results"] = previous_results
                item = await invoke_skill(skill_id, invoke_params, conversation_id)
                invocation_results.append(item)
                if "result" in item:
                    previous_results[skill_id] = item["result"]
        else:
            # Single: invoke skills one by one (no result passing)
            invocation_results = []
            for skill_id in selected_skills:
                invocation_results.append(await invoke_skill(skill_id, params, conversation_id))

        tool_results: Dict[str, Any] = {}
        response_lines = []
        has_errors = False
        missing_required_params: List[str] = []
        pending_subagent_requests: List[Dict[str, Any]] = []

        def append_skill_line(skill: str, text: str, *, is_error: bool = False) -> None:
            """Render plain text for single-skill success, bracketed for multi/error cases."""
            if is_error or len(selected_skills) > 1:
                response_lines.append(f"[{skill}] {text}")
            else:
                response_lines.append(text)

        for item in invocation_results:
            skill_id = item["skill_id"]
            if item.get("input_required"):
                payload = item.get("input_required", {}) or {}
                missing_inputs = payload.get("missing_inputs", []) if isinstance(payload, dict) else []
                auto_resolved, unresolved = resolve_missing_inputs_from_state(
                    state,
                    missing_inputs,
                )
                if auto_resolved:
                    resumed = await invoke_skill(
                        skill_id,
                        {
                            **params,
                            "provided_inputs": auto_resolved,
                            "_a2a_context_id": item.get("_a2a_context_id"),
                            "_a2a_task_id": item.get("_a2a_task_id"),
                        },
                        conversation_id,
                        emit_status=False,
                    )
                    if resumed.get("input_required"):
                        payload = resumed.get("input_required", {}) or {}
                        # Auto-resolution already failed — the subagent still needs these inputs.
                        # Do not attempt re-resolution; pass all missing_inputs to the user.
                        unresolved = payload.get("missing_inputs", []) if isinstance(payload, dict) else []
                        if unresolved:
                            pending_subagent_requests.append({
                                "skill_id": skill_id,
                                "a2a_context_id": resumed.get("_a2a_context_id"),
                                "a2a_task_id": resumed.get("_a2a_task_id"),
                                "missing_inputs": unresolved,
                                "hint": payload.get("hint"),
                            })
                            missing_required_params.extend(
                                [str(entry.get("name") or "") for entry in unresolved if entry.get("name")]
                            )
                            continue
                        item = resumed
                    else:
                        item = resumed
                else:
                    pending_subagent_requests.append({
                        "skill_id": skill_id,
                        "a2a_context_id": item.get("_a2a_context_id"),
                        "a2a_task_id": item.get("_a2a_task_id"),
                        "missing_inputs": unresolved,
                        "hint": payload.get("hint"),
                    })
                    missing_required_params.extend(
                        [str(entry.get("name") or "") for entry in unresolved if entry.get("name")]
                    )
                    continue
            if "error" in item:
                has_errors = True
                tool_results[skill_id] = {"error": item["error"]}
                if item.get("missing_required_params"):
                    tool_results[skill_id]["missing_required_params"] = item["missing_required_params"]
                    missing_required_params.extend(item["missing_required_params"])
                append_skill_line(skill_id, f"Error: {item['error']}", is_error=True)
            else:
                result_data = item.get("result", {})
                tool_results[skill_id] = result_data
                if isinstance(result_data, dict) and result_data.get("by_material"):
                    by_material = result_data.get("by_material", {})
                    compared = ", ".join(by_material.keys())
                    append_skill_line(skill_id, f"Retrieved results for: {compared}")
                    summary = build_comparison_summary(state.get("user_query", ""), by_material)
                    if summary:
                        response_lines.append(summary)
                    else:
                        append_skill_line(skill_id, extract_result_text(result_data))
                else:
                    append_skill_line(skill_id, extract_result_text(result_data))

        if missing_required_params:
            routing_decision = dict(state.get("routing_decision", {}) or {})
            unique_missing = sorted(set(missing_required_params))
            routing_decision["missing_required_params"] = unique_missing
            return {
                "routing_decision": routing_decision,
                "tool_results": tool_results,
                "missing_info": unique_missing,
                "pending_subagent_requests": pending_subagent_requests,
                "awaiting_approval": False,
            }

        response_type = "error" if has_errors else (
            f"agent_response_{selected_skills[0]}" if len(selected_skills) == 1 else "agent_response_multi_skill"
        )
        response_content = "\n\n".join(response_lines)
        suggested_queries = collect_suggested_queries(tool_results, limit=3)
        assistant_metadata = {"suggested_queries": suggested_queries} if suggested_queries else None

        history_entry = {
            "role": "assistant",
            "content": response_content,
            "type": response_type,
            "tool_results": tool_results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if assistant_metadata:
            history_entry["message_metadata"] = assistant_metadata

        response_payload = {
            "conversation_history": state.get("conversation_history", []) + [history_entry],
            "tool_results": tool_results,
            "awaiting_approval": False
        }
        if assistant_metadata:
            response_payload["message_metadata"] = assistant_metadata
        merged_context = dict(state.get("context", {}) or {})
        context_changed = False
        cache = get_capability_cache()
        for skill_id, result_data in tool_results.items():
            capability = await cache.get_capability_by_skill_id(skill_id)
            if not capability or not capability.provides:
                continue
            extracted_maps = extract_provided_context_maps(result_data, capability.provides)
            for context_key, entries in extracted_maps.items():
                before = get_nested_value(merged_context, context_key)
                merge_context_map(merged_context, context_key, entries)
                after = get_nested_value(merged_context, context_key)
                if before != after:
                    context_changed = True

        if context_changed:
            response_payload["context"] = merged_context

        return response_payload

    except Exception as e:
        print(f"[ERROR] invoke_agent_generic failed: {e}")
        import traceback
        traceback.print_exc()
        runtime.store_status_update(conversation_id, f"Execution failed: {e}", final=True)
        return {
            "conversation_history": state.get("conversation_history", []) + [{
                "role": "assistant",
                "content": f"I encountered an error while invoking the agent: {str(e)}",
                "type": "error",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }],
            "awaiting_approval": False
        }


async def ask_followup_dynamic(state: AgentState) -> Dict:
    """Generate followup questions dynamically from capability's input_schema.

    This function implements fully dynamic followup question generation based on
    capability metadata. Instead of hardcoded questions for specific skills, it:

    1. Identifies missing required parameters from routing decision
    2. Looks up parameter schemas from agent cards
    3. Generates appropriate questions based on parameter types and descriptions

    This means adding a new skill with different parameters automatically works
    without any code changes - the questions are generated from the schema.

    Args:
        state: Current workflow state with routing_decision

    Returns:
        State updates with followup_questions in conversation_history
    """
    pending_subagent = state.get("pending_subagent_requests")
    if pending_subagent:
        questions = _questions_from_pending_subagent_requests(state)
        return {
            "conversation_history": state.get("conversation_history", []) + [{
                "role": "assistant",
                "type": "followup_questions",
                "questions": questions,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
            "missing_info": [str(q.get("field") or "") for q in questions if q.get("field")],
            "awaiting_approval": False,
        }

    routing_decision = state.get("routing_decision", {})
    required_params = await resolve_user_required_params(routing_decision)
    provided_params = routing_decision.get("extracted_params", {}) or {}
    missing_params = [param for param in required_params if not has_param_path(provided_params, param)]
    if not missing_params:
        missing_params = routing_decision.get("missing_required_params", [])
    routing_decision["required_params"] = required_params
    routing_decision["missing_required_params"] = missing_params
    state["routing_decision"] = routing_decision
    selected_skills = get_selected_skills(routing_decision)

    print(f"[DEBUG] ask_followup_dynamic: skills={selected_skills}, missing_params={missing_params}")

    if not missing_params:
        return {
            "conversation_history": state.get("conversation_history", []),
            "awaiting_approval": False
        }

    # Gather parameter schemas from all selected skills
    cache = get_capability_cache()
    properties: Dict[str, Any] = {}
    for skill_id in selected_skills:
        capability = await cache.get_capability_by_skill_id(skill_id)
        if capability:
            properties.update(flatten_schema_properties(capability.input_schema))

    # Fallback to primary capability only if selected_skills metadata is unavailable
    if not properties and routing_decision.get("primary_skill"):
        capability = await cache.get_capability_by_skill_id(routing_decision["primary_skill"])
        if capability:
            properties = flatten_schema_properties(capability.input_schema)

    # Overlay param_metadata (from workflow ui.input_overrides) to fill gaps for
    # skills that have no inputSchema (e.g. those using INPUT_REQUIRED instead).
    param_metadata = routing_decision.get("param_metadata", {}) or {}
    for path, meta in param_metadata.items():
        if path not in properties:
            properties[path] = {}
        for key in ("type", "description", "unit", "label", "enum"):
            if meta.get(key) and not properties[path].get(key):
                properties[path][key] = meta[key]

    questions = []

    for param in missing_params:
        prop_info = properties.get(param, {})
        if not prop_info and "." in param:
            prop_info = properties.get(param.split(".", 1)[1], {})
        param_type = prop_info.get("type", "string")
        param_desc = prop_info.get("description", "")
        param_enum = prop_info.get("enum", [])
        param_display = param.replace(".", " ").replace("_", " ")

        if param == "question" or param == "query":
            questions.append({
                "field": param,
                "question": param_desc or "What would you like to know?",
                "type": "text"
            })
        elif param_type == "number" or param_type == "integer":
            questions.append({
                "field": param,
                "question": param_desc or f"Please provide the {param_display}:",
                "type": "number"
            })
        elif param_enum:
            questions.append({
                "field": param,
                "question": param_desc or f"Please select {param_display}:",
                "type": "select",
                "options": param_enum
            })
        else:
            questions.append({
                "field": param,
                "question": param_desc or f"Please provide {param_display}:",
                "type": "text"
            })

    return {
        "conversation_history": state.get("conversation_history", []) + [{
            "role": "assistant",
            "type": "followup_questions",
            "questions": questions,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }],
        "missing_info": missing_params,  # For backward compatibility
        "awaiting_approval": False
    }


async def extract_followup_answers_from_query(state: AgentState, query: str) -> Dict[str, Any]:
    """Extract missing required parameters from a natural-language followup response.

    Uses selected capability schemas and current missing params from routing_decision.
    """
    routing_decision = state.get("routing_decision", {}) or {}
    required_params = await resolve_user_required_params(routing_decision)
    provided_params = routing_decision.get("extracted_params", {}) or {}
    missing_params = [param for param in required_params if not has_param_path(provided_params, param)]
    if not missing_params:
        missing_params = routing_decision.get("missing_required_params", []) or state.get("missing_info", [])
    if not missing_params:
        return {}

    selected_skills = get_selected_skills(routing_decision)
    cache = get_capability_cache()
    properties: Dict[str, Any] = {}
    for skill_id in selected_skills:
        capability = await cache.get_capability_by_skill_id(skill_id)
        if capability:
            properties.update(flatten_schema_properties(capability.input_schema))

    param_schema = {param: properties.get(param, {"type": "string"}) for param in missing_params}

    prompt = f"""Extract parameter values from the user's followup response.

USER FOLLOWUP RESPONSE:
{query}

PARAMETERS TO EXTRACT (JSON schema by field):
{json.dumps(param_schema, indent=2)}

REQUIRED OUTPUT KEYS:
{json.dumps(missing_params)}

Rules:
- Return ONLY a JSON object.
- Include only keys from REQUIRED OUTPUT KEYS.
- Only extract values that are explicitly stated in the user's text.
- Never infer defaults, typical operating conditions, or domain assumptions.
- If a value is not present or is uncertain, set it to null.
- Preserve data types (number/integer/boolean/array/object/string) per schema when possible.
"""

    llm = runtime.create_llm()
    runtime.store_status_update(state.get("conversation_id"), "Calling planner LLM to extract follow-up answers.")
    response = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
    parsed = extract_json_from_text(response.content)
    if not isinstance(parsed, dict):
        return {}

    extracted: Dict[str, Any] = {}
    for param in missing_params:
        value = get_nested_value(parsed, param)
        if value is None or value == "":
            continue
        if param == "material_id":
            inferred = extract_material_ids_from_text(str(value))
            if inferred:
                extracted["material_id"] = inferred[0]
                if len(inferred) > 1:
                    extracted["material_ids"] = inferred
                continue
        extracted[param] = value

    # Fallback: infer material IDs directly from the user followup text.
    if "material_id" in missing_params and "material_id" not in extracted:
        inferred = extract_material_ids_from_text(query)
        if inferred:
            extracted["material_id"] = inferred[0]
            if len(inferred) > 1:
                extracted["material_ids"] = inferred

    return extracted


async def apply_followup_answers_to_state(
    state: AgentState,
    followup_answers: Dict[str, Any],
    query: str = "",
) -> AgentState:
    """Merge follow-up answers into routing params and recompute missing requirements."""
    routing_decision = state.get("routing_decision", {}) or {}
    if not routing_decision:
        return state

    extracted_params = dict(routing_decision.get("extracted_params", {}))
    for key, value in (followup_answers or {}).items():
        if key == "material_id":
            inferred = extract_material_ids_from_text(str(value))
            if inferred:
                extracted_params["material_id"] = inferred[0]
                extracted_params["material_ids"] = inferred
                continue
        extracted_params[key] = value

    effective_query = state.get("user_query", "") or query or ""
    extracted_params = enrich_material_params(effective_query, extracted_params)
    extracted_params = await resolve_params_via_capability_metadata(
        query=effective_query,
        extracted_params=extracted_params,
        selected_skills=get_selected_skills(routing_decision),
        context=state.get("context", {}),
        conversation_history=state.get("conversation_history", []),
    )

    routing_decision["extracted_params"] = extracted_params
    required_params = await resolve_user_required_params(routing_decision)
    routing_decision["required_params"] = required_params
    routing_decision["missing_required_params"] = [
        param for param in required_params if not has_param_path(extracted_params, param)
    ]
    state["routing_decision"] = routing_decision
    state["missing_info"] = routing_decision["missing_required_params"]

    if extracted_params.get("material_id"):
        state["material_id"] = extracted_params.get("material_id")
    merged_context = dict(state.get("context", {}) or {})
    if isinstance(extracted_params.get("context"), dict):
        merged_context.update(extracted_params["context"])
    for key, value in extracted_params.items():
        if key.startswith("context.") and value is not None:
            merged_context[key.split(".", 1)[1]] = value
    if merged_context:
        state["context"] = merged_context

    return state


async def execute_current_plan(state: AgentState, *, start_message: str) -> AgentState:
    """Execute the current routing decision through the canonical execution path."""
    conversation_id = state.get("conversation_id", str(uuid.uuid4()))
    runtime.store_status_update(conversation_id, start_message)

    routing_decision = state.get("routing_decision", {}) or {}
    workflow_type = routing_decision.get("workflow_type", "single")
    workflow_final_output: Any = None

    if workflow_type == "workflow_template" and runtime.ENABLE_WORKFLOW_LIBRARY:
        workflow_id = routing_decision.get("workflow_id")
        workflow_version = routing_decision.get("workflow_version")
        registry = get_workflow_registry()
        compiled_workflow = registry.get(str(workflow_id or ""), version=workflow_version)
        if not compiled_workflow:
            raise RuntimeError(
                f"Workflow template '{workflow_id}'"
                f"{'@' + str(workflow_version) if workflow_version else ''} is unavailable."
            )
        runtime.store_status_update(
            conversation_id,
            (
                f"Executing workflow template "
                f"'{compiled_workflow.definition.id}@{compiled_workflow.definition.version}' "
                f"({len(compiled_workflow.definition.steps)} steps)."
            ),
        )

        context_state = dict(state.get("context", {}) or {})
        input_params = attach_artifact_context(
            routing_decision.get("extracted_params", {}),
            context_state,
        )
        execution_result = await execute_workflow(
            workflow=compiled_workflow,
            input_params=input_params,
            context=context_state,
            invoke_skill=invoke_skill,
            conversation_id=state.get("conversation_id", str(uuid.uuid4())) or str(uuid.uuid4()),
        )
        workflow_final_output = execution_result.get("final_output")
        step_statuses = execution_result.get("step_statuses", {}) or {}
        succeeded = [sid for sid, status in step_statuses.items() if status == "succeeded"]
        failed = [sid for sid, status in step_statuses.items() if status == "failed"]
        blocked = [sid for sid, status in step_statuses.items() if status == "blocked"]
        if succeeded:
            runtime.store_status_update(conversation_id, f"Completed workflow steps: {', '.join(succeeded)}.")
        if failed:
            runtime.store_status_update(conversation_id, f"Failed workflow steps: {', '.join(failed)}.")
        if blocked:
            runtime.store_status_update(conversation_id, f"Blocked workflow steps: {', '.join(blocked)}.")

        tool_results: Dict[str, Any] = {"workflow_execution": execution_result}
        for step_id, payload in (execution_result.get("step_results", {}) or {}).items():
            if not isinstance(payload, dict):
                continue
            skill_id = payload.get("skill_id") or step_id
            result = payload.get("result")
            tool_results[str(skill_id)] = result

        state["tool_results"] = tool_results
        if context_state:
            state["context"] = context_state

        ir_steps = execution_result.get("input_required_steps") or []
        if ir_steps:
            ir = ir_steps[0]
            ir_payload = ir.get("input_required", {}) or {}
            missing_inputs = ir_payload.get("missing_inputs", []) if isinstance(ir_payload, dict) else []
            auto_resolved, unresolved = resolve_missing_inputs_from_state(state, missing_inputs)

            if auto_resolved and not unresolved:
                resumed = await invoke_skill(
                    ir["skill_id"],
                    {**input_params, "provided_inputs": auto_resolved},
                    conversation_id,
                )
                if not resumed.get("input_required"):
                    tool_results[ir["skill_id"]] = resumed.get("result")
                    state["tool_results"] = tool_results
                    state["missing_info"] = []
                else:
                    ir_payload = resumed.get("input_required", {}) or {}
                    unresolved = ir_payload.get("missing_inputs", []) if isinstance(ir_payload, dict) else []

            if unresolved:
                state["pending_subagent_requests"] = [{
                    "skill_id": ir["skill_id"],
                    "a2a_context_id": ir.get("_a2a_context_id"),
                    "a2a_task_id": ir.get("_a2a_task_id"),
                    "missing_inputs": unresolved,
                    "hint": ir_payload.get("hint"),
                }]
                state["missing_info"] = [str(item.get("name") or "") for item in unresolved if item.get("name")]
                state["tool_results"] = tool_results
                runtime.store_status_update(
                    conversation_id,
                    "Additional parameters are required before execution can continue.",
                )
                return state
    else:
        invoke_update = await invoke_agent_generic(state)
        for key, value in invoke_update.items():
            if value is not None:
                state[key] = value
        if state.get("missing_info"):
            runtime.store_status_update(
                conversation_id,
                "Additional parameters are required before execution can continue.",
            )
            return state

    if workflow_type == "workflow_template":
        if workflow_final_output is None:
            raise RuntimeError(
                "Workflow completed without final output. Ensure the template defines a final synthesis step."
            )
        if isinstance(workflow_final_output, dict):
            summary = str(workflow_final_output.get("executive_summary") or "").strip()
            findings = workflow_final_output.get("key_findings")
            if summary and isinstance(findings, list) and findings:
                finding_lines = [f"- {str(item)}" for item in findings[:6]]
                final_report = f"{summary}\n\nKey findings:\n" + "\n".join(finding_lines)
            elif summary:
                final_report = summary
            else:
                final_report = extract_result_text(workflow_final_output)
        else:
            final_report = extract_result_text(workflow_final_output)
    else:
        # Non-template approvals return the combined direct invocation response.
        latest_history = state.get("conversation_history", []) or []
        latest_message = latest_history[-1].get("content") if latest_history else None
        final_report = str(latest_message or "").strip() or extract_result_text(state.get("tool_results", {}))
    state["final_report"] = final_report

    state["conversation_history"] = state.get("conversation_history", []) + [{
        "role": "assistant",
        "content": final_report,
        "type": "final_report",
        "tool_results": state.get("tool_results", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]

    runtime.store_status_update(conversation_id, "Execution complete.", final=True)

    return state


async def execute_approved_plan(state: AgentState) -> AgentState:
    """Execute an approved plan using the same execution path as auto-execution."""
    return await execute_current_plan(state, start_message="Plan approved. Starting execution.")


def _format_plan_for_response(state: AgentState) -> Dict[str, Any]:
    """Normalize internal plan state for frontend consumption."""
    plan = state.get("plan", {}) or {}
    routing_decision = state.get("routing_decision", {}) or {}
    return {
        "intent": plan.get("intent", "Capability execution"),
        "steps": plan.get("steps", []),
        "skills": plan.get("skills", []),
        "workflow_type": plan.get("workflow_type", "single"),
        "workflow_id": plan.get("workflow_id") or routing_decision.get("workflow_id"),
        "workflow_version": plan.get("workflow_version") or routing_decision.get("workflow_version"),
        "workflow_match_score": routing_decision.get("workflow_match_score"),
        "selection_source": routing_decision.get("selection_source"),
        "required_params": plan.get("required_params", []),
        "estimated_duration_seconds": plan.get("estimated_duration_seconds", 120),
        "material_id": state.get("material_id"),
        "analysis_types": state.get("analysis_types", []),
        "context": state.get("context", {}),
        "param_metadata": plan.get("param_metadata", {}),
    }


def _latest_conversation_entry(state: AgentState) -> Dict[str, Any]:
    """Return the latest conversation entry with safe fallback."""
    history = state.get("conversation_history", []) or []
    if history:
        return history[-1]
    return {}


def _coerce_followup_value(value: Any, value_type: str) -> Any:
    """Coerce form-submitted values into the type requested by a subagent."""
    if value is None:
        return None
    # Treat empty string as absent (optional field left blank)
    if isinstance(value, str) and value.strip() == "":
        return None
    normalized_type = str(value_type or "").strip().lower()
    if normalized_type in {"number", "float"}:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Expected a number for field but got: {value!r}")
    if normalized_type == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Expected an integer for field but got: {value!r}")
    if normalized_type == "boolean":
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    return value


def _lookup_context_value(state: AgentState, name: str) -> Any:
    """Resolve one missing-input name from orchestration state/context."""
    routing_decision = state.get("routing_decision", {}) or {}
    extracted_params = routing_decision.get("extracted_params", {}) or {}
    if name in extracted_params:
        return extracted_params.get(name)
    if isinstance(extracted_params.get("context"), dict) and name in extracted_params["context"]:
        return extracted_params["context"].get(name)
    context = state.get("context", {}) or {}
    if name in context:
        return context.get(name)
    if has_param_path(extracted_params, f"context.{name}"):
        return get_nested_value(extracted_params, f"context.{name}")
    if has_param_path(context, name):
        return get_nested_value(context, name)
    return None


def resolve_missing_inputs_from_state(
    state: AgentState,
    missing_inputs: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Resolve context-backed missing inputs using the orchestrator's shared state."""
    auto_resolved: Dict[str, Any] = {}
    unresolved: List[Dict[str, Any]] = []
    for item in missing_inputs or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if item.get("resolvable_from_context"):
            value = _lookup_context_value(state, name)
            if value is not None:
                auto_resolved[name] = value
                continue
        unresolved.append(item)
    return auto_resolved, unresolved


def _questions_from_pending_subagent_requests(state: AgentState) -> List[Dict[str, Any]]:
    """Translate pending INPUT_REQUIRED payloads into frontend form fields, deduplicated by field name."""
    pending_list = state.get("pending_subagent_requests") or []
    seen_fields: set = set()
    questions: List[Dict[str, Any]] = []
    for pending in pending_list:
        for item in (pending or {}).get("missing_inputs", []) or []:
            field = item.get("name")
            if not field or field in seen_fields:
                continue
            seen_fields.add(field)
            input_type = str(item.get("type") or "string").strip().lower()
            questions.append(
                {
                    "field": field,
                    "question": item.get("user_prompt") or item.get("description") or field,
                    "type": "number" if input_type in {"number", "integer"} else ("checkbox" if input_type == "boolean" else ("select" if input_type == "enum" or item.get("options") else "text")),
                    "options": item.get("options"),
                    "description": item.get("description"),
                    "required": bool(item.get("required", True)),
                    "sensitive": bool(item.get("sensitive")),
                    "value_type": input_type,
                }
            )
    return questions


async def resume_pending_subagent_requests(
    state: AgentState,
    followup_answers: Dict[str, Any],
) -> AgentState:
    """Resume all previously blocked subagent tasks with user-provided inputs."""
    pending_list = list(state.get("pending_subagent_requests") or [])
    if not pending_list:
        return state

    routing_decision = dict(state.get("routing_decision", {}) or {})
    base_params = attach_artifact_context(
        routing_decision.get("extracted_params", {}),
        state.get("context", {}),
    )
    conversation_id = state.get("conversation_id", str(uuid.uuid4())) or str(uuid.uuid4())

    still_pending: List[Dict[str, Any]] = []
    merged_context = dict(state.get("context", {}) or {})
    accumulated_tool_results = dict(state.get("tool_results") or {})
    final_reports: List[str] = []

    for pending in pending_list:
        pending = dict(pending)
        skill_id = str(pending.get("skill_id") or "")
        missing_inputs = pending.get("missing_inputs", []) or []

        typed_answers: Dict[str, Any] = {}
        for item in missing_inputs:
            name = str(item.get("name") or "").strip()
            if not name or name not in followup_answers:
                continue
            coerced = _coerce_followup_value(followup_answers[name], str(item.get("type") or "string"))
            if coerced is not None:
                typed_answers[name] = coerced

        auto_resolved, _ = resolve_missing_inputs_from_state(state, missing_inputs)
        provided_inputs = {**auto_resolved, **typed_answers}

        for item in missing_inputs:
            name = str(item.get("name") or "").strip()
            if not name or item.get("sensitive"):
                continue
            if name in provided_inputs:
                merged_context[name] = provided_inputs[name]

        resumed = await invoke_skill(
            skill_id,
            {
                **base_params,
                "provided_inputs": provided_inputs,
                "_a2a_context_id": pending.get("a2a_context_id"),
                "_a2a_task_id": pending.get("a2a_task_id"),
            },
            conversation_id,
        )

        if resumed.get("input_required"):
            ir_payload = resumed.get("input_required", {}) or {}
            _, unresolved = resolve_missing_inputs_from_state(state, ir_payload.get("missing_inputs", []) or [])
            still_pending.append({
                "skill_id": skill_id,
                "a2a_context_id": resumed.get("_a2a_context_id"),
                "a2a_task_id": resumed.get("_a2a_task_id"),
                "missing_inputs": unresolved,
                "hint": ir_payload.get("hint"),
            })
        elif resumed.get("error"):
            accumulated_tool_results[skill_id] = {"error": resumed["error"]}
            final_reports.append(f"[{skill_id}] Error: {resumed['error']}")
        else:
            result_data = resumed.get("result", {})
            accumulated_tool_results[skill_id] = result_data
            final_reports.append(extract_result_text(result_data))

    state["context"] = merged_context
    state["pending_subagent_requests"] = still_pending
    state["tool_results"] = accumulated_tool_results

    if still_pending:
        state["missing_info"] = [
            str(item.get("name") or "")
            for p in still_pending
            for item in (p.get("missing_inputs") or [])
            if item.get("name")
        ]
        return state

    state["missing_info"] = []
    report = "\n\n".join(final_reports) if final_reports else ""
    state["final_report"] = report
    state["conversation_history"] = state.get("conversation_history", []) + [{
        "role": "assistant",
        "content": report,
        "type": (
            f"agent_response_{pending_list[0].get('skill_id', '')}"
            if len(pending_list) == 1
            else "agent_response_multi_skill"
        ),
        "tool_results": accumulated_tool_results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]
    return state
