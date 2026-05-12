from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from capability_cache import get_capability_cache
from param_schema import extract_required_param_paths, flatten_schema_properties, has_param_path, is_user_input_schema
from planner import PlanningResult, WorkflowPlanningCandidate, compile_plan_with_tools
from workflow_library import get_workflow_registry, match_workflows

from . import runtime
from .models import AgentState
from .parameters import (
    build_plan_param_metadata,
    get_selected_skills,
    order_skills_for_workflow,
    resolve_params_via_capability_metadata,
)
from .utils import enrich_material_params, extract_json_from_text, extract_material_ids_from_text


def _unique_workflow_skills(workflow) -> List[str]:
    skills: List[str] = []
    for step in workflow.definition.steps:
        if step.skill_id and step.skill_id not in skills:
            skills.append(step.skill_id)
    return skills


async def compile_query_plan(
    state: AgentState,
    explicit_workflow_id: Optional[str] = None,
    explicit_workflow_version: Optional[str] = None,
    selection_source: Optional[str] = None,
    seed_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile an execution plan via planner tool calls (no subagent side effects)."""
    query = state.get("user_query", "") or ""
    conversation_history = state.get("conversation_history", [])
    context = state.get("context", {}) or {}
    conversation_id = state.get("conversation_id")
    runtime.store_status_update(
        conversation_id,
        "Planning request: matching workflows and selecting capabilities.",
    )

    cache = get_capability_cache()
    capabilities = await cache.get_capabilities()
    capabilities_by_skill = {cap.skill_id: cap for cap in capabilities}
    seed_params = dict(seed_params or {})

    workflow_registry = get_workflow_registry() if runtime.ENABLE_WORKFLOW_LIBRARY else None
    matched_workflow = None
    workflow_candidates: List[WorkflowPlanningCandidate] = []
    if workflow_registry is not None:
        if explicit_workflow_id:
            selected = workflow_registry.get(explicit_workflow_id, version=explicit_workflow_version)
            if selected:
                matched_workflow = selected
                workflow_candidates.append(
                    WorkflowPlanningCandidate(
                        workflow_id=selected.definition.id,
                        workflow_version=selected.definition.version,
                        score=1.0,
                        required_paths=list(selected.required_input_paths),
                        selection_source=selection_source or "catalog",
                        skills=_unique_workflow_skills(selected),
                        execution_mode=selected.definition.execution.mode,
                        estimated_duration_seconds=selected.definition.metadata.estimated_duration_seconds,
                        display_name=selected.definition.ui.display_name or selected.definition.name,
                        summary=selected.definition.ui.summary or selected.definition.description,
                        extracted_params=seed_params,
                    )
                )
        else:
            matches = match_workflows(query=query, workflows=workflow_registry.list_all())
            for item in matches[:5]:
                workflow = workflow_registry.get(item.workflow_id, version=item.workflow_version)
                if not workflow:
                    continue
                workflow_candidates.append(
                    WorkflowPlanningCandidate(
                        workflow_id=workflow.definition.id,
                        workflow_version=workflow.definition.version,
                        score=item.score,
                        required_paths=list(workflow.required_input_paths),
                        selection_source="matcher",
                        skills=_unique_workflow_skills(workflow),
                        execution_mode=workflow.definition.execution.mode,
                        estimated_duration_seconds=workflow.definition.metadata.estimated_duration_seconds,
                        display_name=workflow.definition.ui.display_name or workflow.definition.name,
                        summary=workflow.definition.ui.summary or workflow.definition.description,
                        extracted_params=dict(item.extracted_params),
                    )
                )
            if workflow_candidates:
                top = workflow_candidates[0]
                matched_workflow = workflow_registry.get(top.workflow_id, version=top.workflow_version)

    # Catalog-selected workflows bypass matcher/router selection and resolve requirements directly.
    if explicit_workflow_id and matched_workflow is not None:
        runtime.store_status_update(
            conversation_id,
            f"Using selected workflow template '{matched_workflow.definition.id}'.",
        )
        selected_skills = _unique_workflow_skills(matched_workflow)
        extracted_params = enrich_material_params(query, seed_params)
        extracted_params = await resolve_params_via_capability_metadata(
            query=query,
            extracted_params=extracted_params,
            selected_skills=selected_skills,
            context=context,
            conversation_history=conversation_history,
        )
        required_params = sorted(set(matched_workflow.required_input_paths))
        requires_approval = bool(matched_workflow.definition.metadata.requires_approval)
        for skill_id in selected_skills:
            cap = capabilities_by_skill.get(skill_id)
            if not cap:
                continue
            if cap.requires_approval:
                requires_approval = True
        missing_required_params = [path for path in required_params if not has_param_path(extracted_params, path)]
        if missing_required_params:
            runtime.store_status_update(
                conversation_id,
                "Missing required parameters: " + ", ".join(missing_required_params),
            )

        merged_context = dict(context)
        if isinstance(extracted_params.get("context"), dict):
            merged_context.update(extracted_params["context"])
        for key, value in extracted_params.items():
            if key.startswith("context.") and value is not None:
                merged_context[key.split(".", 1)[1]] = value
        param_metadata = build_plan_param_metadata(
            selected_skills=selected_skills,
            capabilities_by_skill=capabilities_by_skill,
            selected_workflow=matched_workflow,
        )

        routing_decision = {
            "primary_skill": selected_skills[0] if selected_skills else None,
            "supporting_skills": selected_skills[1:] if len(selected_skills) > 1 else [],
            "workflow_type": "workflow_template",
            "workflow_id": matched_workflow.definition.id,
            "workflow_version": matched_workflow.definition.version,
            "workflow_match_score": 1.0,
            "selection_source": selection_source or "catalog",
            "confidence": 1.0,
            "needs_clarification": False,
            "clarification_question": None,
            "extracted_params": extracted_params,
            "reasoning": f"Catalog-selected workflow {matched_workflow.definition.id}",
            "agent_url": None,
            "requires_approval": requires_approval,
            "required_params": required_params,
            "missing_required_params": missing_required_params,
        }
        plan_steps = [
            f"Step {idx}: Invoke '{step.skill_id}' ({step.id})"
            for idx, step in enumerate(matched_workflow.definition.steps, 1)
        ]
        runtime.store_status_update(
            conversation_id,
            (
                f"Routing decision: templated workflow "
                f"'{matched_workflow.definition.id}@{matched_workflow.definition.version}'."
            ),
        )
        return {
            "is_fallback": False,
            "routing_decision": routing_decision,
            "material_id": extracted_params.get("material_id"),
            "analysis_types": extracted_params.get("analysis_types", []),
            "context": merged_context,
            "question": extracted_params.get("question"),
            "plan": {
                "intent": matched_workflow.definition.description,
                "workflow_type": "workflow_template",
                "workflow_id": matched_workflow.definition.id,
                "workflow_version": matched_workflow.definition.version,
                "skills": selected_skills,
                "required_params": required_params,
                "steps": plan_steps,
                "missing_info": missing_required_params,
                "estimated_duration_seconds": matched_workflow.definition.metadata.estimated_duration_seconds or 120,
                "param_metadata": param_metadata,
            },
            "missing_info": missing_required_params,
            "planner_message": "I've prepared the selected workflow plan. Please review and approve.",
        }

    runtime.store_status_update(conversation_id, "Calling planner LLM for routing decision.")
    planning_result = await compile_plan_with_tools(
        query=query,
        capabilities=capabilities,
        history=conversation_history,
        context=context,
        workflow_candidates=workflow_candidates,
        forced_workflow_id=explicit_workflow_id,
        forced_workflow_version=explicit_workflow_version,
        forced_selection_source=selection_source,
        status_callback=lambda msg: runtime.store_status_update(conversation_id, msg),
    )

    if planning_result.outcome == "fallback" or not planning_result.primary_skill:
        # Guardrail: if deterministic workflow matching found candidates, prefer that
        # over conversational fallback so missing-parameter collection remains structured
        # (`needs_info` + followup form) instead of plain text.
        if workflow_candidates and workflow_registry is not None:
            top = workflow_candidates[0]
            selected = workflow_registry.get(top.workflow_id, version=top.workflow_version)
            if selected:
                planning_result = PlanningResult(
                    outcome="agent_plan",
                    message="I've prepared a workflow plan and need a few parameters to continue.",
                    workflow_id=top.workflow_id,
                    workflow_version=top.workflow_version,
                    workflow_match_score=top.score,
                    selection_source=top.selection_source,
                    primary_skill=top.skills[0] if top.skills else None,
                    supporting_skills=top.skills[1:] if len(top.skills) > 1 else [],
                    workflow_type="workflow_template",
                    confidence=0.9,
                    reasoning=(
                        f"Deterministically matched workflow template "
                        f"{top.workflow_id}@{top.workflow_version}."
                    ),
                    extracted_params=dict(top.extracted_params or {}),
                    steps=[],
                    estimated_duration_seconds=top.estimated_duration_seconds or 120,
                )
                runtime.store_status_update(
                    conversation_id,
                    (
                        f"Using deterministic workflow match "
                        f"'{top.workflow_id}@{top.workflow_version}'."
                    ),
                )
            else:
                message = planning_result.message or "I couldn't find a capability plan for that request."
                runtime.store_status_update(conversation_id, "No capability plan found for this request.", final=True)
                return {
                    "is_fallback": True,
                    "fallback_message": message,
                }
        else:
            message = planning_result.message or "I couldn't find a capability plan for that request."
            runtime.store_status_update(conversation_id, "No capability plan found for this request.", final=True)
            return {
                "is_fallback": True,
                "fallback_message": message,
            }

    selected_skills: List[str] = [planning_result.primary_skill]
    for skill_id in planning_result.supporting_skills:
        if skill_id and skill_id not in selected_skills:
            selected_skills.append(skill_id)

    selected_workflow = None
    selected_workflow_candidate: Optional[WorkflowPlanningCandidate] = None
    if planning_result.workflow_id and workflow_registry is not None:
        selected_workflow = workflow_registry.get(
            planning_result.workflow_id,
            version=planning_result.workflow_version,
        )
        for candidate in workflow_candidates:
            if candidate.workflow_id != planning_result.workflow_id:
                continue
            if planning_result.workflow_version and candidate.workflow_version != planning_result.workflow_version:
                continue
            selected_workflow_candidate = candidate
            break
        if selected_workflow:
            wf_skills = _unique_workflow_skills(selected_workflow)
            if wf_skills:
                selected_skills = wf_skills

    primary_capability = capabilities_by_skill.get(planning_result.primary_skill)
    if primary_capability is None and selected_skills:
        primary_capability = capabilities_by_skill.get(selected_skills[0])
    if primary_capability is None and selected_workflow is None:
        runtime.store_status_update(
            conversation_id,
            f"Selected capability '{planning_result.primary_skill}' is unavailable.",
            final=True,
        )
        return {
            "is_fallback": True,
            "fallback_message": (
                f"Capability '{planning_result.primary_skill}' is currently unavailable. "
                "Please retry after discovery refresh."
            ),
        }

    required_params_set = set(selected_workflow.required_input_paths if selected_workflow else [])
    runtime_required_params_set: set[str] = set()
    requires_approval = False
    if selected_workflow and selected_workflow.definition.metadata.requires_approval:
        requires_approval = True
    for skill_id in selected_skills:
        cap = capabilities_by_skill.get(skill_id)
        if not cap:
            continue
        if selected_workflow is None:
            user_required_paths = extract_required_param_paths(cap.input_schema)
            all_required_paths = extract_required_param_paths(cap.input_schema, include_internal=True)
            required_params_set.update(user_required_paths)
            runtime_required_params_set.update(set(all_required_paths) - set(user_required_paths))
        if cap.requires_approval:
            requires_approval = True

    required_params = sorted(required_params_set)
    runtime_required_params = sorted(runtime_required_params_set)
    extracted_seed = dict(seed_params)
    if selected_workflow_candidate and selected_workflow_candidate.extracted_params:
        extracted_seed.update(selected_workflow_candidate.extracted_params)
    extracted_seed.update(planning_result.extracted_params)
    extracted_params = enrich_material_params(query, extracted_seed)
    extracted_params = await resolve_params_via_capability_metadata(
        query=query,
        extracted_params=extracted_params,
        selected_skills=selected_skills,
        context=context,
        conversation_history=conversation_history,
    )
    unresolved_runtime_params = [
        path for path in runtime_required_params
        if not has_param_path(extracted_params, path)
    ]
    if selected_workflow is None and unresolved_runtime_params:
        runtime.store_status_update(
            conversation_id,
            (
                "Planner selected capabilities with unresolved runtime inputs: "
                + ", ".join(unresolved_runtime_params)
            ),
            final=True,
        )
        return {
            "is_fallback": True,
            "fallback_message": (
                "I couldn't execute that plan directly because it requires internal runtime inputs. "
                "Please request a workflow plan that includes upstream specialist steps."
            ),
        }

    missing_required_params = [
        path for path in required_params
        if not has_param_path(extracted_params, path)
    ]
    if missing_required_params:
        runtime.store_status_update(
            conversation_id,
            "Missing required parameters: " + ", ".join(missing_required_params),
        )

    merged_context = dict(context)
    if isinstance(extracted_params.get("context"), dict):
        merged_context.update(extracted_params["context"])
    for key, value in extracted_params.items():
        if key.startswith("context.") and value is not None:
            merged_context[key.split(".", 1)[1]] = value

    material_id = extracted_params.get("material_id")
    analysis_types = extracted_params.get("analysis_types", [])
    if isinstance(analysis_types, str):
        analysis_types = [analysis_types]

    steps = planning_result.steps
    if not steps:
        if selected_workflow is not None:
            for idx, step in enumerate(selected_workflow.definition.steps, 1):
                steps.append(f"Step {idx}: Invoke '{step.skill_id}' ({step.id})")
        else:
            for idx, skill_id in enumerate(selected_skills, 1):
                cap = capabilities_by_skill.get(skill_id)
                skill_name = cap.skill_name if cap else skill_id
                skill_desc = cap.description if cap else "Invoke capability"
                steps.append(f"Step {idx}: Invoke '{skill_name}' ({skill_id}) - {skill_desc}")

    estimated_duration = planning_result.estimated_duration_seconds
    if not estimated_duration or estimated_duration < 1:
        estimated_duration = 0
        for skill_id in selected_skills:
            cap = capabilities_by_skill.get(skill_id)
            estimated_duration += cap.expected_duration_seconds if cap and cap.expected_duration_seconds else 30

    routing_decision = {
        "primary_skill": planning_result.primary_skill or (selected_skills[0] if selected_skills else None),
        "supporting_skills": [skill for skill in selected_skills[1:]] if selected_skills else [],
        "workflow_type": planning_result.workflow_type,
        "workflow_id": planning_result.workflow_id,
        "workflow_version": planning_result.workflow_version,
        "workflow_match_score": planning_result.workflow_match_score,
        "selection_source": planning_result.selection_source,
        "confidence": planning_result.confidence,
        "needs_clarification": False,
        "clarification_question": None,
        "extracted_params": extracted_params,
        "reasoning": planning_result.reasoning or planning_result.message or query,
        "agent_url": primary_capability.agent_url if primary_capability else None,
        "requires_approval": requires_approval,
        "required_params": required_params,
        "missing_required_params": missing_required_params,
    }
    if planning_result.workflow_type == "workflow_template" and planning_result.workflow_id:
        runtime.store_status_update(
            conversation_id,
            (
                f"Routing decision: templated workflow "
                f"'{planning_result.workflow_id}@{planning_result.workflow_version}'."
            ),
        )
    elif planning_result.workflow_type == "single":
        runtime.store_status_update(
            conversation_id,
            f"Routing decision: single capability '{routing_decision.get('primary_skill')}'.",
        )
    else:
        skill_list = ", ".join(selected_skills) if selected_skills else "(none)"
        runtime.store_status_update(
            conversation_id,
            f"Routing decision: {planning_result.workflow_type} multi-skill plan ({skill_list}).",
        )
    param_metadata = build_plan_param_metadata(
        selected_skills=selected_skills,
        capabilities_by_skill=capabilities_by_skill,
        selected_workflow=selected_workflow,
    )

    return {
        "is_fallback": False,
        "routing_decision": routing_decision,
        "material_id": material_id,
        "analysis_types": analysis_types,
        "context": merged_context,
        "question": extracted_params.get("question"),
        "plan": {
            "intent": planning_result.reasoning or planning_result.message or query,
            "workflow_type": planning_result.workflow_type,
            "workflow_id": planning_result.workflow_id,
            "workflow_version": planning_result.workflow_version,
            "skills": selected_skills,
            "required_params": required_params,
            "steps": steps,
            "missing_info": missing_required_params,
            "estimated_duration_seconds": estimated_duration,
            "param_metadata": param_metadata,
        },
        "missing_info": missing_required_params,
        "planner_message": planning_result.message,
    }


async def extract_refinement_param_updates(
    query: str,
    routing_decision: Dict[str, Any],
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Extract parameter updates from plan-refinement instructions.

    Unlike follow-up extraction, refinement extraction considers both required and
    optional user-facing fields so users can tweak assumptions without reopening
    missing-info flow.
    """
    text = str(query or "").strip()
    if not text or not isinstance(routing_decision, dict):
        return {}

    selected_skills = get_selected_skills(routing_decision)
    cache = get_capability_cache()
    properties: Dict[str, Any] = {}
    for skill_id in selected_skills:
        capability = await cache.get_capability_by_skill_id(skill_id)
        if capability:
            properties.update(flatten_schema_properties(capability.input_schema))

    candidate_paths: List[str] = []
    workflow_type = routing_decision.get("workflow_type")
    workflow_id = routing_decision.get("workflow_id")
    workflow_version = routing_decision.get("workflow_version")
    if workflow_type == "workflow_template" and workflow_id and runtime.ENABLE_WORKFLOW_LIBRARY:
        workflow = get_workflow_registry().get(str(workflow_id), version=workflow_version)
        if workflow:
            candidate_paths.extend(list(workflow.required_input_paths))
            candidate_paths.extend(list(workflow.definition.inputs.optional or []))

    if not candidate_paths:
        for path, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            is_object = prop.get("type") == "object" or "properties" in prop
            if is_object:
                continue
            if is_user_input_schema(prop):
                candidate_paths.append(path)
    else:
        filtered: List[str] = []
        for path in candidate_paths:
            prop = properties.get(path)
            if not prop and "." in path:
                prop = properties.get(path.split(".", 1)[1], {})
            if isinstance(prop, dict) and not is_user_input_schema(prop):
                continue
            filtered.append(path)
        candidate_paths = filtered

    normalized_paths: List[str] = []
    seen_paths = set()
    for path in candidate_paths:
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        normalized_paths.append(path)
    if not normalized_paths:
        return {}

    param_schema = {}
    for path in normalized_paths:
        prop = properties.get(path)
        if not prop and "." in path:
            prop = properties.get(path.split(".", 1)[1], {})
        param_schema[path] = prop if isinstance(prop, dict) and prop else {"type": "string"}

    history_lines: List[str] = []
    for item in (conversation_history or [])[-8:]:
        role = str(item.get("role") or "user")
        content = str(item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "(none)"

    current_params = routing_decision.get("extracted_params", {}) or {}
    prompt = f"""Extract parameter updates from this plan-refinement instruction.

REFINEMENT INSTRUCTION:
{text}

RECENT CONVERSATION:
{history_block}

CURRENT PARAMS:
{json.dumps(current_params, indent=2, default=str)}

ALLOWED PARAM KEYS (use these exact dotted keys):
{json.dumps(normalized_paths, indent=2)}

PARAM SCHEMA BY KEY:
{json.dumps(param_schema, indent=2, default=str)}

Rules:
- Return ONLY a JSON object.
- Include ONLY keys that should be updated by this refinement.
- Do NOT repeat unchanged values.
- If no updates are implied, return {{}}.
- Preserve schema data types when possible.
- If a duration field is in hours and user gives years/months/days, convert to hours.
"""

    llm = runtime.create_llm()
    response = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
    parsed = extract_json_from_text(response.content)
    if not isinstance(parsed, dict):
        return {}

    updates: Dict[str, Any] = {}
    for path in normalized_paths:
        value = get_nested_value(parsed, path)
        if value is None and path in parsed:
            value = parsed.get(path)
        if value is None or value == "":
            continue
        if path == "material_id":
            inferred = extract_material_ids_from_text(str(value))
            if inferred:
                updates["material_id"] = inferred[0]
                updates["material_ids"] = inferred
                continue
        updates[path] = value

    return updates


def plan_analysis(state: AgentState) -> Dict:
    """Create a capability-driven execution plan with no hardcoded agent logic.

    Generates an execution plan dynamically from capability metadata. The plan includes:
    - Intent/reasoning from routing decision
    - Ordered list of skills to invoke
    - Step-by-step description of what will happen
    - Estimated duration from capability metadata
    - Missing parameters that need to be provided

    All plan details come from agent card metadata - there is no hardcoded knowledge
    of what specific skills do.

    Args:
        state: Current workflow state with routing_decision

    Returns:
        State updates with generated plan
    """
    routing_decision = state.get("routing_decision", {}) or {}
    existing_plan = state.get("plan")
    if isinstance(existing_plan, dict) and existing_plan.get("steps"):
        provided_params = routing_decision.get("extracted_params", {}) or {}
        required_params = existing_plan.get("required_params") or routing_decision.get("required_params", []) or []
        missing = [param for param in required_params if not has_param_path(provided_params, param)]
        if not missing:
            missing = routing_decision.get("missing_required_params", []) or state.get("missing_info", [])

        preserved_plan = dict(existing_plan)
        preserved_plan["missing_info"] = missing
        if "workflow_type" not in preserved_plan:
            preserved_plan["workflow_type"] = routing_decision.get("workflow_type", "single")
        if "skills" not in preserved_plan:
            preserved_plan["skills"] = order_skills_for_workflow(routing_decision)
        return {
            "plan": preserved_plan,
            "missing_info": missing,
            "messages": [],
        }

    selected_skills = order_skills_for_workflow(routing_decision)
    provided_params = routing_decision.get("extracted_params", {}) or {}
    required_params = routing_decision.get("required_params", []) or []
    missing = [param for param in required_params if not has_param_path(provided_params, param)]
    if not missing:
        missing = routing_decision.get("missing_required_params", []) or state.get("missing_info", [])

    # Build plan steps from capability metadata
    capability_cache = get_capability_cache()
    steps: List[str] = []
    estimated_duration = 0

    for idx, skill_id in enumerate(selected_skills, 1):
        capability = capability_cache.get_by_skill_id(skill_id)
        skill_name = capability.skill_name if capability else skill_id
        skill_desc = capability.description if capability else "Invoke capability"
        steps.append(f"Step {idx}: Invoke '{skill_name}' ({skill_id}) - {skill_desc}")
        estimated_duration += capability.expected_duration_seconds if capability and capability.expected_duration_seconds else 30

    if not steps:
        steps = ["Invoke selected capability based on query intent"]
        estimated_duration = 30

    plan = {
        "intent": routing_decision.get("reasoning") or state.get("user_query") or "Capability execution",
        "workflow_type": routing_decision.get("workflow_type", "single"),
        "skills": selected_skills,
        "required_params": required_params,
        "steps": steps,
        "missing_info": missing,
        "estimated_duration_seconds": estimated_duration,
    }

    return {
        "plan": plan,
        "missing_info": missing,
        "messages": []
    }


def show_plan(state: AgentState) -> Dict:
    """Show plan to user and wait for approval."""
    return {
        "awaiting_approval": True
    }
