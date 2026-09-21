"""
LLM tool-calling planner for control-plane routing decisions.

`compile_plan_with_tools` is the single entry point. It is called by `chat()`
in `agent.py` whenever a new query needs to be routed. It drives an LLM
through a structured tool-call loop and returns a `PlanningResult` describing
what to do next — no subagents are invoked here.

HOW IT WORKS
------------
1. A schema-bound LLM call resolves the current turn into a standalone task or
   an explicit non-executable response.
2. A second schema-bound call decomposes standalone tasks without seeing capabilities.
3. A `_PlanDraft` freezes those operations and accumulates routing state.
4. The routing LLM is given:
   - The user query and conversation history
   - Available capabilities (skills + their input schemas)
   - Optional workflow templates (pre-built execution blueprints)
5. The LLM calls planning tools until it calls `finalize_plan`, at which point
   the loop exits.
6. The `_PlanDraft` is converted to an immutable `PlanningResult` and returned.
7. Parameter extraction runs separately after the planner selects capabilities.

PLANNING TOOLS (called by the LLM, not external code)
------------------------------------------------------
- `select_capabilities`      — choose primary + supporting skills and workflow type
- `workflow_*`              — choose a registered workflow blueprint directly
- `select_workflow_template` — choose a pre-built workflow blueprint by id/version
- `get_workflow_candidates`  — inspect registered workflow options
- `get_requirement_status`   — check which required params are still missing
- `set_plan_steps`           — set human-readable steps shown in the approval UI
- `set_user_message`         — set the planning summary shown to the user
- `set_operation_coverage`   — map every requested operation or mark it unsupported
- `finalize_plan`            — commit the plan (preserves missing user inputs for collection)

OUTCOMES (`PlanningResult.outcome`)
------------------------------------
- `"agent_plan"`  — one or more skills selected; `agent.py` will collect missing
                    params then call `execute_current_plan`
- `"fallback"`    — capability-neutral decomposition produced a conversational
                    response or clarification; `agent.py` returns it directly
- `"unsupported"` — one or more requested operations have no registered
                    capability; no partial plan is executed

WORKFLOW TEMPLATES vs DYNAMIC SKILL SELECTION
---------------------------------------------
Dynamic selection (always available): the planner picks skills freely from the
capability registry. Flexible but requires the agent cards to have good metadata.

Workflow templates (when ENABLE_WORKFLOW_LIBRARY=true): pre-authored blueprints
stored in `workflow_library/`. Registered workflows are exposed to the planner
as dedicated `workflow_*` tools. The planner can call one of those tools, or
select one by id/version via `select_workflow_template`. Templates define fixed
skill sequences, input bindings, and execution order.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from langchain_core.tools import StructuredTool
from prometheus_api import load_prompt
from pydantic import BaseModel, ValidationError

from artifact_handling import collect_chain_required_paths
from capability_cache import AgentCapability
from file_upload_handler import mime_type_label
from param_schema import (
    extract_required_param_paths,
    flatten_schema_properties,
    get_nested_value,
    has_param_path,
    set_nested_value,
)
from planner_models import (
    AssignDependenciesInput,
    ClarificationResolutionInput,
    CoveredOperationInput,
    DecomposeTaskInput,
    NewTaskResolutionInput,
    PlanningResult,
    PriorResultDiscussionInput,
    RepeatTaskResolutionInput,
    RequestedOperation,
    SelectCapabilitiesInput,
    SelectRegisteredWorkflowInput,
    SelectWorkflowTemplateInput,
    SetOperationCoverageInput,
    SetPlanStepsInput,
    SetUserMessageInput,
    TaskDecomposition,
    TurnResolution,
    UnsupportedOperationInput,
    WorkflowPlanningCandidate,
    _PlanDraft,
)
from workflow_library.naming import workflow_tool_name
from orchestrator import runtime

PROMPTS_DIR = Path(__file__).with_name("prompts")

SYSTEM_PROMPT = load_prompt("planner_system.txt", prompts_dir=PROMPTS_DIR)
TURN_RESOLUTION_SYSTEM_PROMPT = load_prompt(
    "turn_resolution_system.txt",
    prompts_dir=PROMPTS_DIR,
)
TASK_DECOMPOSITION_SYSTEM_PROMPT = load_prompt(
    "task_decomposition_system.txt",
    prompts_dir=PROMPTS_DIR,
)
DEPENDENCY_ASSIGNMENT_SYSTEM_PROMPT = load_prompt(
    "dependency_assignment_system.txt",
    prompts_dir=PROMPTS_DIR,
)

# Retry instruction and per-stage shape hints fed back to the model when a
# schema-bound tool call is rejected (see `_call_planning_tool`).
PLANNING_TOOL_RETRY_PROMPT = load_prompt(
    "planning_tool_retry.txt",
    prompts_dir=PROMPTS_DIR,
)
TURN_RESOLUTION_SHAPE_HINT = load_prompt(
    "turn_resolution_shape_hint.txt",
    prompts_dir=PROMPTS_DIR,
)
TASK_DECOMPOSITION_SHAPE_HINT = load_prompt(
    "task_decomposition_shape_hint.txt",
    prompts_dir=PROMPTS_DIR,
)
DEPENDENCY_ASSIGNMENT_SHAPE_HINT = load_prompt(
    "dependency_assignment_shape_hint.txt",
    prompts_dir=PROMPTS_DIR,
)

# JSON-Schema keywords that OpenAI strict tool-call mode rejects outright; they
# are stripped from every advertised schema by `_strip_unsupported_strict_keywords`.
_STRICT_UNSUPPORTED_SCHEMA_KEYWORDS = {
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "patternProperties",
    "propertyNames",
    "unevaluatedProperties",
}

# How many layers of drift `_repair_tool_arg_fields` will peel off one field.
# Each pass removes exactly one layer: a JSON-encoded string, or a field nested
# inside itself. Two layers is the worst combination seen in practice (a JSON
# string whose object repeats the field name); 4 leaves headroom for a
# double-encoded variant while keeping the loop bounded on pathological input.
_TOOL_ARG_UNWRAP_LIMIT = 4


class PlanningContractError(RuntimeError):
    """Raised when an LLM planning response violates its declared schema."""


def _result_summary(result: Any, assistant_content: str) -> str:
    if isinstance(result, Mapping):
        for key in ("error", "answer", "summary", "message", "status"):
            value = result.get(key)
            if value not in (None, ""):
                return str(value)[:500]
    elif result not in (None, ""):
        return str(result)[:500]
    return assistant_content[:500]


def _result_outcome(result: Any) -> str:
    if isinstance(result, Mapping):
        if result.get("error"):
            return "error"
        if result.get("missing_inputs") or result.get("missing_required_params"):
            return "input_required"
    return "completed"


def _recent_capability_invocations(
    history: List[Dict[str, Any]],
    *,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Return bounded actual invocation records for turn-reference resolution."""
    records: List[Dict[str, Any]] = []
    user_request = ""
    for item in history:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if item.get("role") == "user" and content:
            user_request = content
        tool_inputs = item.get("tool_inputs")
        if not isinstance(tool_inputs, Mapping):
            continue
        tool_results = item.get("tool_results")
        if not isinstance(tool_results, Mapping):
            tool_results = {}
        for skill_id, params in tool_inputs.items():
            if str(skill_id) == "workflow_execution" or not isinstance(params, Mapping):
                continue
            result = tool_results.get(skill_id)
            records.append(
                {
                    "capability_id": str(skill_id),
                    "user_request": user_request,
                    "tool_inputs": dict(params),
                    "outcome": _result_outcome(result),
                    "result_summary": _result_summary(result, content),
                }
            )

    records = records[-max(1, limit):]
    for index, record in enumerate(records, 1):
        record["invocation_id"] = f"invocation_{index}"
    return records


def _recent_conversation_excerpt(
    history: List[Dict[str, Any]],
    *,
    limit: int = 8,
) -> List[Dict[str, str]]:
    excerpt: List[Dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        excerpt.append(
            {
                "role": str(item.get("role") or "user"),
                "content": content[:1000],
            }
        )
    return excerpt[-max(1, limit):]


def _resolver_artifact_context(context: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    artifacts: List[Dict[str, str]] = []
    for item in ((context or {}).get("artifacts") or [])[-12:]:
        if not isinstance(item, Mapping):
            continue
        artifact_id = str(item.get("artifact_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not artifact_id and not name:
            continue
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "name": name,
                "description": str(item.get("description") or "")[:300],
                "mime_type": str(item.get("mime_type") or ""),
            }
        )
    return artifacts


async def resolve_turn(
    *,
    query: str,
    history: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
    status_callback: Optional[Callable[[str], None]] = None,
) -> TurnResolution:
    """Resolve the current utterance into a standalone task or explicit response."""
    if status_callback:
        status_callback("Planner LLM resolving the current turn.")

    history = history or []
    invocations = _recent_capability_invocations(history)
    invocation_ids = [item["invocation_id"] for item in invocations]

    messages = [
        {
            "role": "system",
            "content": TURN_RESOLUTION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": (
                f"Current user query:\n{query}\n\n"
                "Recent conversation text:\n"
                f"{json.dumps(_recent_conversation_excerpt(history), default=str)}\n\n"
                "Recent actual capability invocations:\n"
                f"{json.dumps(invocations, default=str)}\n\n"
                "Available artifact references:\n"
                f"{json.dumps(_resolver_artifact_context(context), default=str)}"
            ),
        },
    ]
    resolution_specs = [
        (
            "resolve_new_task",
            "Resolve an independent executable request.",
            NewTaskResolutionInput,
        ),
        (
            "resolve_prior_result_discussion",
            "Answer a question about prior results without requesting new work.",
            PriorResultDiscussionInput,
        ),
        (
            "resolve_needs_clarification",
            "Ask one focused question when no standalone task can be determined.",
            ClarificationResolutionInput,
        ),
    ]
    if invocation_ids:
        resolution_specs.insert(
            1,
            (
                "resolve_repeat_prior_task_with_changes",
                "Repeat one supplied prior invocation with requested changes.",
                RepeatTaskResolutionInput,
            ),
        )

    resolution_tools: List[Dict[str, Any]] = []
    resolution_models: Dict[str, Any] = {}
    for name, description, model in resolution_specs:
        schema = model.model_json_schema()
        if name == "resolve_repeat_prior_task_with_changes":
            schema["properties"]["referenced_invocation_id"] = {
                "type": "string",
                "enum": invocation_ids,
            }
        elif name == "resolve_prior_result_discussion":
            schema["properties"]["referenced_invocation_id"] = (
                {
                    "anyOf": [
                        {"type": "string", "enum": invocation_ids},
                        {"type": "null"},
                    ]
                }
                if invocation_ids
                else {"type": "null"}
            )
        resolution_models[name] = model
        resolution_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )

    def _check_invocation_reference(_tool_name: str, parsed: Any) -> Optional[str]:
        referenced = getattr(parsed, "referenced_invocation_id", None)
        if referenced and referenced not in invocation_ids:
            return (
                f"referenced_invocation_id '{referenced}' is not an available prior "
                f"invocation; choose one of {invocation_ids or '(none available)'}"
            )
        return None

    tool_name, parsed = await _call_planning_tool(
        messages=messages,
        tools=resolution_tools,
        expected=resolution_models,
        error_prefix="Turn resolution violates its schema",
        shape_hint=TURN_RESOLUTION_SHAPE_HINT,
        semantic_check=_check_invocation_reference,
    )

    standalone_request = str(getattr(parsed, "standalone_request", "")).strip()
    message = str(getattr(parsed, "message", "")).strip()
    referenced_invocation_id = getattr(parsed, "referenced_invocation_id", None)

    resolution_kinds = {
        "resolve_new_task": "new_task",
        "resolve_repeat_prior_task_with_changes": "repeat_prior_task_with_changes",
        "resolve_prior_result_discussion": "discuss_prior_result",
        "resolve_needs_clarification": "needs_clarification",
    }

    return TurnResolution(
        resolution_kind=resolution_kinds[tool_name],
        standalone_request=standalone_request,
        referenced_invocation_id=referenced_invocation_id,
        message=message,
    )


def _strip_unsupported_strict_keywords(schema: Any) -> Any:
    """Recursively drop JSON-Schema keywords unsupported by OpenAI strict tool-call mode.

    Pydantic still enforces the dropped constraints locally in ``model_validate``;
    this only affects the schema advertised to the model.
    """
    if isinstance(schema, dict):
        return {
            key: _strip_unsupported_strict_keywords(value)
            for key, value in schema.items()
            if key not in _STRICT_UNSUPPORTED_SCHEMA_KEYWORDS
        }
    if isinstance(schema, list):
        return [_strip_unsupported_strict_keywords(item) for item in schema]
    return schema


def _strict_tool_schema(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Build an OpenAI strict-mode tool schema from a (possibly Pydantic-derived) parameters schema.

    ``strict`` is advisory: OpenAI honors it as constrained decoding, but the
    registry/LiteLLM proxy and non-OpenAI providers ignore it. Correctness must
    therefore never depend on it — ``_call_planning_tool`` repairs and re-asks.
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": _strip_unsupported_strict_keywords(parameters),
            "strict": True,
        },
    }


def _json_from_string(value: Any) -> Any:
    """Parse ``value`` as JSON when it is a non-empty string, else return ``None``.

    Callers pass values that are just as often already-decoded structure (a
    ``dict`` or ``list``) as text, so every non-string input returns ``None``:
    "already decoded" and "not parseable as JSON" are the same answer here —
    there is nothing left to unwrap.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _repair_tool_arg_fields(
    payload: Mapping[str, Any], field_names: set[str]
) -> Dict[str, Any]:
    """Unwrap JSON-string values and self-named nesting for each known field.

    Handles the two observed drifts: a field carrying a JSON *string* instead of
    the structure, and a field repeated inside itself
    (``{"operations": {"operations": [...]}}``).
    """
    repaired = dict(payload)
    for name in field_names & set(repaired):
        value = repaired[name]
        for _ in range(_TOOL_ARG_UNWRAP_LIMIT):
            parsed = _json_from_string(value)
            if parsed is not None:
                value = parsed
                continue
            if isinstance(value, Mapping) and set(value.keys()) == {name}:
                value = value[name]
                continue
            break
        repaired[name] = value
    return repaired


def _coerce_tool_args(
    decoded_args: Any, model: type[BaseModel], arguments_json: str = ""
) -> List[Any]:
    """Return candidate payloads for ``model``, most faithful first.

    ``decoded_args`` is the tool call's arguments as the provider decoded them;
    ``arguments_json`` is the original argument JSON text, retried as a fallback
    root when that decoding produced something unusable.

    The untouched tool args are always the first candidate, so a payload that
    already satisfies the model is never rewritten. Later candidates repair the
    shape drift that appears when the provider does not enforce constrained
    tool-call decoding (see ``_strict_tool_schema``): the whole payload arriving
    as a JSON string, a payload hidden under a stray wrapper key, a property
    repeated inside itself, or the wrapper omitted entirely.
    """
    candidates: List[Any] = [decoded_args]

    def add(candidate: Any) -> None:
        if not any(candidate == existing for existing in candidates):
            candidates.append(candidate)

    field_names = set(model.model_fields)
    single_field = next(iter(field_names)) if len(field_names) == 1 else None

    roots: List[Any] = [decoded_args]
    for source in (decoded_args, arguments_json):
        parsed_root = _json_from_string(source)
        if parsed_root is not None:
            roots.append(parsed_root)

    for root in roots:
        if not isinstance(root, Mapping):
            # A bare structure with no wrapper object at all.
            if single_field is not None and root is not None:
                add({single_field: root})
            continue

        payload = dict(root)
        if root is not decoded_args:
            add(payload)

        # Payload hidden under a single stray key ("input", "args", ...).
        if len(payload) == 1:
            only_key, only_value = next(iter(payload.items()))
            if only_key not in field_names:
                inner = _json_from_string(only_value)
                if inner is None:
                    inner = only_value
                if isinstance(inner, Mapping):
                    add(_repair_tool_arg_fields(inner, field_names))
                elif single_field is not None:
                    add({single_field: inner})

        add(_repair_tool_arg_fields(payload, field_names))

        # The wrapper was omitted and the payload sits at the top level.
        if single_field is not None and single_field not in payload:
            add({single_field: payload})

    return candidates


async def _call_planning_tool(
    *,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    expected: Mapping[str, type[BaseModel]],
    error_prefix: str,
    shape_hint: str,
    max_tokens: int = 2048,
    max_attempts: int = 2,
    semantic_check: Optional[Callable[[str, Any], Optional[str]]] = None,
) -> tuple[str, Any]:
    """Run one single-tool planning phase, repairing and re-asking as needed.

    Every planning phase that expects exactly one tool call goes through here so
    they share the same tolerance. A rejected call — wrong call count, unusable
    argument shape, or a ``semantic_check`` failure — is re-asked once with the
    reason fed back, and only a genuinely unrecoverable answer raises
    ``PlanningContractError``.

    Returns the ``(tool_name, parsed_model)`` pair of the accepted call.
    """
    attempt_messages = list(messages)
    tool_names = sorted(expected)
    attempts = max(1, max_attempts)
    last_error = "no attempts made"

    for attempt in range(1, attempts + 1):
        async with runtime.create_llm() as llm:
            response = await llm.medium(
                attempt_messages,
                temperature=0,
                max_tokens=max_tokens,
                tools=tools,
            )
        _, calls = _planning_tool_calls(response.raw)

        if len(calls) != 1 or str(calls[0].get("name")) not in expected:
            called = [str(call.get("name")) for call in calls]
            last_error = (
                f"{' or '.join(tool_names)} must be called exactly once; got "
                f"{called if called else 'no tool calls'}"
            )
        else:
            call = calls[0]
            tool_name = str(call["name"])
            model = expected[tool_name]
            decode_error = str(call.get("args_error") or "")

            parsed: Any = None
            for candidate in _coerce_tool_args(
                call.get("args"), model, str(call.get("raw_arguments") or "")
            ):
                try:
                    parsed = model.model_validate(candidate)
                except ValidationError as exc:
                    last_error = str(exc)
                    parsed = None
                    continue
                break

            if parsed is None and decode_error:
                last_error = f"tool-call arguments were not valid JSON ({decode_error})"
            elif parsed is not None:
                problem = semantic_check(tool_name, parsed) if semantic_check else None
                if problem is None:
                    return tool_name, parsed
                last_error = problem

        if attempt < attempts:
            attempt_messages.append(
                {
                    "role": "user",
                    "content": PLANNING_TOOL_RETRY_PROMPT.format(
                        last_error=last_error,
                        tool_names=" or ".join(tool_names),
                        shape_hint=shape_hint,
                    ),
                }
            )

    raise PlanningContractError(f"{error_prefix}: {last_error}")


async def decompose_task(
    *,
    query: str,
    status_callback: Optional[Callable[[str], None]] = None,
) -> TaskDecomposition:
    """Decompose a standalone task before exposing registered capabilities."""
    if status_callback:
        status_callback("Planner LLM decomposing the standalone task into operations.")

    messages = [
        {
            "role": "system",
            "content": TASK_DECOMPOSITION_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f"Standalone user task:\n{query}",
        },
    ]
    tool_schema = _strict_tool_schema(
        "decompose_task",
        "Return the exact capability-neutral task decomposition.",
        DecomposeTaskInput.model_json_schema(),
    )

    def _check_descriptions(_tool_name: str, parsed: Any) -> Optional[str]:
        for index, description in enumerate(parsed.operation_descriptions, 1):
            if not str(description).strip():
                return f"operation {index} has an empty description"
        return None

    _, decomposed = await _call_planning_tool(
        messages=messages,
        tools=[tool_schema],
        expected={"decompose_task": DecomposeTaskInput},
        error_prefix="Task decomposition violates its schema",
        shape_hint=TASK_DECOMPOSITION_SHAPE_HINT,
        semantic_check=_check_descriptions,
    )

    operation_descriptions: List[str] = [
        str(description).strip() for description in decomposed.operation_descriptions
    ]

    dependency_map: Dict[str, List[str]] = {
        f"op_{index}": [] for index in range(1, len(operation_descriptions) + 1)
    }
    if len(operation_descriptions) > 1:
        if status_callback:
            status_callback("Planner LLM assigning operation dependencies.")
        operation_ids = list(dependency_map)
        dependency_properties = {}
        for index, operation_id in enumerate(operation_ids):
            earlier_ids = operation_ids[:index]
            dependency_properties[operation_id] = {
                "type": "array",
                "description": (
                    f"Earlier operations that {operation_id} directly depends on."
                ),
                "items": (
                    {"type": "string", "enum": earlier_ids}
                    if earlier_ids
                    else {"type": "string"}
                ),
                "uniqueItems": True,
                "maxItems": len(earlier_ids),
            }
        dependency_tool = _strict_tool_schema(
            "assign_dependencies",
            "Assign dependencies among the frozen ordered operations.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "depends_on_by_operation": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": dependency_properties,
                        "required": operation_ids,
                    }
                },
                "required": ["depends_on_by_operation"],
            },
        )
        frozen_operations = [
            {"operation_id": operation_id, "description": description}
            for operation_id, description in zip(
                operation_ids, operation_descriptions
            )
        ]
        dependency_messages = [
            {
                "role": "system",
                "content": DEPENDENCY_ASSIGNMENT_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"Current user query:\n{query}\n\n"
                    "Frozen ordered operations:\n"
                    f"{json.dumps(frozen_operations)}"
                ),
            },
        ]

        def _check_dependencies(_tool_name: str, parsed: Any) -> Optional[str]:
            """Validate the edges themselves, so semantic drift also earns a retry."""
            assignment = parsed.depends_on_by_operation
            if set(assignment) != set(operation_ids):
                return (
                    "the assignment must contain exactly one entry for each of "
                    f"{operation_ids}"
                )
            for position, operation_id in enumerate(operation_ids):
                dependencies = assignment[operation_id]
                if len(set(dependencies)) != len(dependencies):
                    return f"{operation_id} lists duplicate dependencies"
                earlier_ids = operation_ids[:position]
                invalid = [item for item in dependencies if item not in earlier_ids]
                if invalid:
                    return (
                        f"{operation_id} may only depend on earlier operations "
                        f"{earlier_ids or '(none)'}; got {invalid}"
                    )
            return None

        _, assigned = await _call_planning_tool(
            messages=dependency_messages,
            tools=[dependency_tool],
            expected={"assign_dependencies": AssignDependenciesInput},
            error_prefix="Dependency assignment violates its schema",
            shape_hint=DEPENDENCY_ASSIGNMENT_SHAPE_HINT.format(
                operation_ids=operation_ids
            ),
            max_tokens=1024,
            semantic_check=_check_dependencies,
        )
        dependency_map = assigned.depends_on_by_operation

    operations: List[RequestedOperation] = []
    for index, description in enumerate(operation_descriptions, 1):
        operation_id = f"op_{index}"
        dependencies = dependency_map[operation_id]
        operations.append(
            RequestedOperation(
                operation_id=operation_id,
                description=description,
                depends_on=list(dependencies),
            )
        )

    return TaskDecomposition(operations=operations)


def _set_param_path(params: Dict[str, Any], path: str, value: Any) -> None:
    set_nested_value(params, path, value)


def _get_param_path(params: Dict[str, Any], path: str) -> Any:
    return get_nested_value(params, path)


def _build_capability_context(capabilities: List[AgentCapability]) -> str:
    """Format capability metadata for planner prompt grounding."""
    blocks: List[str] = []
    for cap in capabilities:
        lines = [
            f"- skill_id: {cap.skill_id}",
            f"  agent: {cap.agent_name}",
            f"  description: {cap.description}",
            f"  requires_approval: {cap.requires_approval}",
        ]
        if cap.usage_notes:
            lines.append(f"  usage_notes: {cap.usage_notes}")
        if cap.tags:
            lines.append(f"  tags: {', '.join(cap.tags)}")
        if cap.input_schema:
            required = extract_required_param_paths(cap.input_schema)
            internal_required = sorted(
                set(extract_required_param_paths(cap.input_schema, include_internal=True)) - set(required)
            )
            props = cap.input_schema.get("properties", {}) or {}
            if required:
                lines.append(f"  required_params: {', '.join(required)}")
            if internal_required:
                lines.append(
                    "  internal_required_params: "
                    + ", ".join(internal_required)
                    + " (provided by workflow/runtime, not user)"
                )
            if props:
                prop_lines = []
                for name, info in props.items():
                    desc = str(info.get("description", "")).strip()
                    typ = str(info.get("type", "string"))
                    prop_lines.append(f"{name}({typ}){': ' + desc if desc else ''}")
                if prop_lines:
                    lines.append(f"  params: {', '.join(prop_lines)}")
        if cap.expected_duration_seconds:
            lines.append(f"  expected_duration_seconds: {cap.expected_duration_seconds}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _build_prompt(
    query: str,
    history: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]],
    capabilities: List[AgentCapability],
    operations: List[RequestedOperation],
    workflow_candidates: Optional[List[WorkflowPlanningCandidate]] = None,
) -> str:
    """Build the routing prompt from resolved intent and bounded conversational text."""
    history_lines: List[str] = []
    for item in history[-12:]:
        role = str(item.get("role", "user"))
        text = str(item.get("content", "")).strip()
        if text:
            history_lines.append(f"{role}: {text[:1000]}")

    artifacts_block = ""
    artifacts = (context or {}).get("artifacts")
    newly_uploaded_ids = set((context or {}).get("newly_uploaded_artifact_ids") or [])
    if isinstance(artifacts, list) and artifacts:
        rows = []
        for artifact in artifacts[:12]:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            name = str(artifact.get("name") or "").strip()
            desc = str(artifact.get("description") or "").strip()
            if not artifact_id or not name:
                continue
            if artifact_id in newly_uploaded_ids:
                mime = str(artifact.get("mime_type") or "")
                label = mime_type_label(mime, name)
                desc = f"[User-uploaded {label} for this request] {desc}".strip()
            rows.append(f"- {name} (id: {artifact_id}) {desc[:200]}")
        if rows:
            artifacts_block = "Available artifacts:\n" + "\n".join(rows)

    # Files received this turn but not stored (storage unavailable or upload failed).
    received_files = (context or {}).get("received_files") or []
    if received_files:
        received_rows = []
        for f in received_files:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "file")
            mime = str(f.get("mime_type") or "")
            label = mime_type_label(mime, name)
            received_rows.append(f"- {name} ({label}) [received this request — not stored, storage unavailable]")
        if received_rows:
            received_block = "Files received (not stored — storage unavailable):\n" + "\n".join(received_rows)
            artifacts_block = (artifacts_block + "\n" + received_block).strip() if artifacts_block else received_block

    history_block = "\n".join(history_lines) if history_lines else "(none)"
    capability_block = _build_capability_context(capabilities)
    context_block = json.dumps(context or {}, indent=2, default=str)
    operations_block = json.dumps(
        [operation.model_dump() for operation in operations],
        indent=2,
    )
    workflow_block = ""
    if workflow_candidates:
        rows = []
        for candidate in workflow_candidates:
            label = candidate.display_name or candidate.workflow_id
            tool_name = candidate.tool_name or workflow_tool_name(candidate.workflow_id)
            rows.append(
                f"- tool: {tool_name} "
                f"label={label} "
                f"workflow={candidate.workflow_id}@{candidate.workflow_version} "
                f"mode={candidate.execution_mode} "
                f"skills={candidate.skills} "
                f"required={candidate.required_paths}"
            )
        workflow_block = "Registered workflow tools:\n" + "\n".join(rows) + "\n\n"

    return (
        f"User query:\n{query}\n\n"
        f"Recent conversation text:\n{history_block}\n\n"
        f"Current conversation context:\n{context_block}\n\n"
        f"Required operations (immutable):\n{operations_block}\n\n"
        f"{workflow_block}"
        f"{artifacts_block}\n\n"
        f"Available capabilities:\n{capability_block}\n"
    ).strip()


def _build_planning_tools(
    draft: _PlanDraft,
    capabilities_by_skill: Dict[str, AgentCapability],
    context: Optional[Dict[str, Any]],
    workflow_candidates: Optional[List[WorkflowPlanningCandidate]] = None,
) -> List[StructuredTool]:
    """Create side-effect-free planning tools for one planning session."""
    planning_context = dict(context or {})
    candidate_list = list(workflow_candidates or [])
    candidates_by_id: Dict[str, List[WorkflowPlanningCandidate]] = {}
    for candidate in candidate_list:
        candidates_by_id.setdefault(candidate.workflow_id, []).append(candidate)
    for workflow_id, items in candidates_by_id.items():
        items.sort(key=lambda item: item.workflow_version, reverse=True)

    def get_selected_workflow_candidate() -> Optional[WorkflowPlanningCandidate]:
        if not draft.workflow_id:
            return None
        options = candidates_by_id.get(draft.workflow_id, [])
        if not options:
            return None
        if draft.workflow_version:
            for candidate in options:
                if candidate.workflow_version == draft.workflow_version:
                    return candidate
        return options[0]

    def selected_skill_ids() -> List[str]:
        if not draft.primary_skill:
            return []
        selected = [draft.primary_skill]
        for skill_id in draft.supporting_skills:
            if skill_id and skill_id not in selected:
                selected.append(skill_id)
        return selected

    def hydrate_context_assumptions(required_paths: List[str]) -> None:
        for path in required_paths:
            if not path.startswith("context.") or has_param_path(draft.extracted_params, path):
                continue
            context_key = path.split(".", 1)[1]
            value = _get_param_path(planning_context, context_key)
            if value is not None:
                _set_param_path(draft.extracted_params, path, value)

    def get_requirement_status() -> Dict[str, Any]:
        selected = selected_skill_ids()
        selected_workflow = get_selected_workflow_candidate()
        if not selected and not selected_workflow:
            return {
                "ok": False,
                "error": (
                    "No skills/workflow selected yet. Call select_capabilities or select_workflow_template first."
                ),
            }

        required_paths_set = set()
        runtime_required_paths_set = set()
        deferred_runtime_paths_set = set()
        properties: Dict[str, Dict[str, Any]] = {}
        if selected_workflow:
            required_paths_set.update(selected_workflow.required_paths)
            # For workflow templates, required inputs come from workflow bindings
            # (`input.*` refs) rather than full downstream skill schemas.
            for skill_id in selected:
                cap = capabilities_by_skill.get(skill_id)
                if cap:
                    properties.update(flatten_schema_properties(cap.input_schema))
        else:
            chain_capabilities = [capabilities_by_skill.get(skill_id) for skill_id in selected]
            chain = collect_chain_required_paths(chain_capabilities, draft.workflow_type)
            required_paths_set.update(chain.user_paths)
            runtime_required_paths_set.update(chain.runtime_paths)
            deferred_runtime_paths_set.update(chain.deferred_paths)
            for cap in chain_capabilities:
                if cap:
                    properties.update(flatten_schema_properties(cap.input_schema))

        required_paths = sorted(required_paths_set)
        runtime_required_paths = sorted(runtime_required_paths_set)
        hydrate_context_assumptions(required_paths)
        missing_paths = [path for path in required_paths if not has_param_path(draft.extracted_params, path)]
        unresolved_runtime_paths = [
            path for path in runtime_required_paths if not has_param_path(draft.extracted_params, path)
        ]

        details: List[Dict[str, Any]] = []
        for path in required_paths:
            prop = properties.get(path)
            if not prop and "." in path:
                prop = properties.get(path.split(".", 1)[1])
            details.append(
                {
                    "path": path,
                    "type": (prop or {}).get("type", "string"),
                    "description": (prop or {}).get("description", ""),
                }
            )

        return {
            "ok": True,
            "required_paths": required_paths,
            "missing_paths": missing_paths,
            "runtime_required_paths": runtime_required_paths,
            "unresolved_runtime_paths": unresolved_runtime_paths,
            # Filled at runtime from earlier sequential steps' outputs; do not
            # ask the user for these and do not treat them as blocking.
            "deferred_runtime_paths": sorted(deferred_runtime_paths_set),
            "details": details,
            "params": draft.extracted_params,
        }

    def get_workflow_candidates() -> Dict[str, Any]:
        payload = [
            {
                "workflow_id": candidate.workflow_id,
                "workflow_version": candidate.workflow_version,
                "tool_name": candidate.tool_name or workflow_tool_name(candidate.workflow_id),
                "required_paths": candidate.required_paths,
                "skills": candidate.skills,
                "execution_mode": candidate.execution_mode,
                "display_name": candidate.display_name,
                "summary": candidate.summary,
                "extracted_params": candidate.extracted_params,
            }
            for candidate in candidate_list
        ]
        return {"ok": True, "candidates": payload}

    def select_workflow_template(
        workflow_id: str,
        workflow_version: Optional[str] = None,
        reasoning: str = "",
        confidence: float = 0.5,
    ) -> Dict[str, Any]:
        options = candidates_by_id.get(workflow_id, [])
        if not options:
            return {"ok": False, "error": f"Unknown workflow_id '{workflow_id}'"}
        selected_candidate = None
        if workflow_version:
            for candidate in options:
                if candidate.workflow_version == workflow_version:
                    selected_candidate = candidate
                    break
            if selected_candidate is None:
                return {
                    "ok": False,
                    "error": f"Unknown workflow version '{workflow_version}' for workflow '{workflow_id}'",
                }
        else:
            selected_candidate = options[0]

        selected_candidate = selected_candidate or options[0]
        draft.workflow_id = selected_candidate.workflow_id
        draft.workflow_version = selected_candidate.workflow_version
        draft.workflow_match_score = float(selected_candidate.score)
        draft.selection_source = selected_candidate.selection_source
        draft.workflow_type = "workflow_template"
        draft.reasoning = (reasoning or draft.reasoning or "").strip()
        draft.confidence = max(0.0, min(1.0, float(confidence)))
        draft.primary_skill = selected_candidate.skills[0] if selected_candidate.skills else None
        draft.supporting_skills = selected_candidate.skills[1:] if len(selected_candidate.skills) > 1 else []
        if selected_candidate.estimated_duration_seconds and selected_candidate.estimated_duration_seconds > 0:
            draft.estimated_duration_seconds = int(selected_candidate.estimated_duration_seconds)
        if selected_candidate.extracted_params:
            merged = dict(selected_candidate.extracted_params)
            merged.update(draft.extracted_params)
            draft.extracted_params = merged

        status = get_requirement_status()
        return {
            "ok": True,
            "workflow_id": draft.workflow_id,
            "workflow_version": draft.workflow_version,
            "missing_paths": status.get("missing_paths", []),
        }

    def select_capabilities(
        primary_skill: str,
        supporting_skills: Optional[List[str]] = None,
        workflow_type: str = "single",
        reasoning: str = "",
        confidence: float = 0.5,
    ) -> Dict[str, Any]:
        if primary_skill not in capabilities_by_skill:
            return {"ok": False, "error": f"Unknown primary_skill '{primary_skill}'"}
        if workflow_type not in {"single", "parallel", "sequential"}:
            return {"ok": False, "error": f"Invalid workflow_type '{workflow_type}'"}

        normalized_support: List[str] = []
        for skill_id in supporting_skills or []:
            if skill_id == primary_skill:
                continue
            if skill_id not in capabilities_by_skill:
                return {"ok": False, "error": f"Unknown supporting skill '{skill_id}'"}
            if skill_id not in normalized_support:
                normalized_support.append(skill_id)

        draft.primary_skill = primary_skill
        draft.supporting_skills = normalized_support
        draft.workflow_type = workflow_type  # type: ignore[assignment]
        draft.workflow_id = None
        draft.workflow_version = None
        draft.workflow_match_score = None
        draft.selection_source = "dynamic_router"
        draft.reasoning = (reasoning or "").strip()
        draft.confidence = max(0.0, min(1.0, float(confidence)))
        draft.outcome = "agent_plan"
        status = get_requirement_status()
        return {
            "ok": True,
            "primary_skill": draft.primary_skill,
            "supporting_skills": draft.supporting_skills,
            "workflow_type": draft.workflow_type,
            "required_paths": status.get("required_paths", []),
            "missing_paths": status.get("missing_paths", []),
        }

    def set_operation_coverage(
        covered: Optional[List[CoveredOperationInput]] = None,
        unsupported: Optional[List[UnsupportedOperationInput]] = None,
    ) -> Dict[str, Any]:
        operation_ids = {operation.operation_id for operation in draft.operations}
        covered_map: Dict[str, str] = {}
        unsupported_map: Dict[str, str] = {}

        for entry in covered or []:
            operation_id = str(
                entry.operation_id if isinstance(entry, CoveredOperationInput) else entry.get("operation_id", "")
            )
            skill_id = str(
                entry.skill_id if isinstance(entry, CoveredOperationInput) else entry.get("skill_id", "")
            )
            if operation_id not in operation_ids:
                return {"ok": False, "error": f"Unknown operation_id '{operation_id}'"}
            if operation_id in covered_map:
                return {"ok": False, "error": f"Duplicate coverage for '{operation_id}'"}
            if skill_id not in capabilities_by_skill:
                return {"ok": False, "error": f"Unknown skill_id '{skill_id}'"}
            covered_map[operation_id] = skill_id

        for entry in unsupported or []:
            operation_id = str(
                entry.operation_id
                if isinstance(entry, UnsupportedOperationInput)
                else entry.get("operation_id", "")
            )
            reason = str(
                entry.reason if isinstance(entry, UnsupportedOperationInput) else entry.get("reason", "")
            ).strip()
            if operation_id not in operation_ids:
                return {"ok": False, "error": f"Unknown operation_id '{operation_id}'"}
            if operation_id in covered_map or operation_id in unsupported_map:
                return {"ok": False, "error": f"Duplicate coverage for '{operation_id}'"}
            if not reason:
                return {"ok": False, "error": f"Unsupported operation '{operation_id}' needs a reason"}
            unsupported_map[operation_id] = reason

        draft.covered_operations = covered_map
        draft.unsupported_operations = unsupported_map
        uncovered = [
            operation.operation_id
            for operation in draft.operations
            if operation.operation_id not in covered_map
            and operation.operation_id not in unsupported_map
        ]
        return {
            "ok": True,
            "covered_operation_ids": list(covered_map),
            "unsupported_operation_ids": list(unsupported_map),
            "uncovered_operation_ids": uncovered,
        }

    def set_plan_steps(
        steps: List[str],
        estimated_duration_seconds: int = 120,
    ) -> Dict[str, Any]:
        normalized = [str(step).strip() for step in (steps or []) if str(step).strip()]
        draft.steps = normalized
        draft.estimated_duration_seconds = max(1, int(estimated_duration_seconds))
        return {
            "ok": True,
            "steps": draft.steps,
            "estimated_duration_seconds": draft.estimated_duration_seconds,
        }

    def set_user_message(message: str) -> Dict[str, Any]:
        draft.message = str(message or "").strip()
        return {"ok": True, "message": draft.message}

    def finalize_plan() -> Dict[str, Any]:
        operation_ids = [operation.operation_id for operation in draft.operations]
        uncovered = [
            operation_id
            for operation_id in operation_ids
            if operation_id not in draft.covered_operations
            and operation_id not in draft.unsupported_operations
        ]
        if uncovered:
            return {
                "ok": False,
                "error": "Every requested operation must be covered or marked unsupported.",
                "uncovered_operation_ids": uncovered,
            }

        if draft.unsupported_operations:
            draft.outcome = "unsupported"
            draft.primary_skill = None
            draft.supporting_skills = []
            draft.workflow_id = None
            draft.workflow_version = None
            draft.extracted_params = {}
            draft.steps = []
            draft.finalized = True
            return {
                "ok": True,
                "finalized": True,
                "unsupported_operation_ids": list(draft.unsupported_operations),
            }

        if not draft.primary_skill and not draft.workflow_id:
            return {
                "ok": False,
                "error": "No plan selection found. Call select_capabilities or select_workflow_template first.",
            }
        selected = selected_skill_ids()
        unselected_coverage = {
            operation_id: skill_id
            for operation_id, skill_id in draft.covered_operations.items()
            if skill_id not in selected
        }
        if unselected_coverage:
            return {
                "ok": False,
                "error": "Operation coverage references capabilities outside the selected plan.",
                "unselected_coverage": unselected_coverage,
            }
        if draft.operations and not draft.workflow_id:
            covered_skill_ids = set(draft.covered_operations.values())
            unused_selected = [
                skill_id for skill_id in selected if skill_id not in covered_skill_ids
            ]
            if unused_selected:
                return {
                    "ok": False,
                    "error": (
                        "Every selected dynamic capability must cover at least one "
                        "requested operation."
                    ),
                    "unused_selected_skill_ids": unused_selected,
                }

        selected_workflow = get_selected_workflow_candidate()
        if selected_workflow is None:
            # Registered templates own dependency validation and ordering through their compiled step graph.
            sequential = draft.workflow_type == "sequential"
            skill_positions = {skill_id: index for index, skill_id in enumerate(selected)}
            operations_by_id = {operation.operation_id: operation for operation in draft.operations}
            for operation in draft.operations:
                skill_id = draft.covered_operations.get(operation.operation_id)
                for dependency_id in operation.depends_on:
                    dependency_skill = draft.covered_operations.get(dependency_id)
                    if not dependency_skill or not skill_id or dependency_skill == skill_id:
                        continue
                    if not sequential:
                        return {
                            "ok": False,
                            "error": (
                                "Dependencies covered by different capabilities require a "
                                "sequential workflow."
                            ),
                        }
                    if skill_positions[dependency_skill] >= skill_positions[skill_id]:
                        dependency = operations_by_id[dependency_id]
                        return {
                            "ok": False,
                            "error": (
                                "Selected capability order violates operation dependency order: "
                                f"'{dependency.description}' must run before '{operation.description}'."
                            ),
                        }
        status = get_requirement_status()
        missing = status.get("missing_paths", [])
        unresolved_runtime = status.get("unresolved_runtime_paths", [])
        if unresolved_runtime and not get_selected_workflow_candidate():
            return {
                "ok": False,
                "error": (
                    "Selected capabilities require runtime-only inputs that cannot be asked from user. "
                    "Choose a workflow template or different capabilities."
                ),
                "unresolved_runtime_paths": unresolved_runtime,
            }
        draft.outcome = "agent_plan"
        draft.finalized = True
        return {
            "ok": True,
            "finalized": True,
            "missing_paths": missing,
        }

    workflow_tools: List[StructuredTool] = []
    seen_tool_names: set[str] = set()
    for candidate in candidate_list:
        tool_name = candidate.tool_name or workflow_tool_name(candidate.workflow_id)
        if tool_name in seen_tool_names:
            continue
        seen_tool_names.add(tool_name)

        def run_registered_workflow(
            reasoning: str = "",
            confidence: float = 0.8,
            *,
            _candidate: WorkflowPlanningCandidate = candidate,
        ) -> Dict[str, Any]:
            return select_workflow_template(
                workflow_id=_candidate.workflow_id,
                workflow_version=_candidate.workflow_version,
                reasoning=reasoning,
                confidence=confidence,
            )

        label = candidate.display_name or candidate.workflow_id
        summary = candidate.summary or ""
        workflow_tools.append(
            StructuredTool.from_function(
                func=run_registered_workflow,
                name=tool_name,
                description=(
                    f"Select workflow template '{label}' "
                    f"({candidate.workflow_id}@{candidate.workflow_version}). {summary}"
                ).strip(),
                args_schema=SelectRegisteredWorkflowInput,
            )
        )

    planning_tools = [
        StructuredTool.from_function(
            func=select_capabilities,
            name="select_capabilities",
            description="Select the primary/supporting capabilities and workflow type for this request.",
            args_schema=SelectCapabilitiesInput,
        ),
        StructuredTool.from_function(
            func=get_workflow_candidates,
            name="get_workflow_candidates",
            description="Return registered workflow templates available as workflow_* tools.",
        ),
        StructuredTool.from_function(
            func=select_workflow_template,
            name="select_workflow_template",
            description="Select a workflow template candidate by id/version for workflow-template planning.",
            args_schema=SelectWorkflowTemplateInput,
        ),
        StructuredTool.from_function(
            func=get_requirement_status,
            name="get_requirement_status",
            description="Return required parameter paths, missing paths, and schema descriptions for currently selected capabilities.",
        ),
        StructuredTool.from_function(
            func=set_operation_coverage,
            name="set_operation_coverage",
            description=(
                "Map every immutable requested operation to a registered capability, or mark "
                "the operation unsupported with a concrete reason."
            ),
            args_schema=SetOperationCoverageInput,
        ),
        StructuredTool.from_function(
            func=set_plan_steps,
            name="set_plan_steps",
            description="Set user-visible plan steps and estimated duration.",
            args_schema=SetPlanStepsInput,
        ),
        StructuredTool.from_function(
            func=set_user_message,
            name="set_user_message",
            description="Set a concise user-facing planning message.",
            args_schema=SetUserMessageInput,
        ),
        StructuredTool.from_function(
            func=finalize_plan,
            name="finalize_plan",
            description=(
                "Finalize the planning decision after selecting capabilities. Parameter extraction "
                "and missing-input collection run after routing."
            ),
        ),
    ]
    return workflow_tools + planning_tools


def _default_steps_from_selection(
    primary_skill: str,
    supporting_skills: List[str],
    capabilities_by_skill: Dict[str, AgentCapability],
) -> List[str]:
    skills = [primary_skill] + [skill for skill in supporting_skills if skill != primary_skill]
    steps: List[str] = []
    for idx, skill_id in enumerate(skills, 1):
        cap = capabilities_by_skill.get(skill_id)
        label = cap.skill_name if cap else skill_id
        desc = cap.description if cap else "Invoke selected capability"
        steps.append(f"Step {idx}: Invoke '{label}' ({skill_id}) - {desc}")
    return steps


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _planning_tool_schema(tool: StructuredTool) -> Dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if isinstance(args_schema, dict):
        parameters = args_schema
    elif hasattr(args_schema, "model_json_schema"):
        parameters = args_schema.model_json_schema()
    elif hasattr(args_schema, "schema"):
        parameters = args_schema.schema()
    else:
        parameters = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        },
    }


def _planning_tool_calls(raw: Any) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    choices = _value(raw, "choices", []) or []
    message = _value(choices[0], "message", {}) if choices else {}
    content = _value(message, "content", "")
    raw_calls = _value(message, "tool_calls", []) or []

    assistant_message: Dict[str, Any] = {
        "role": "assistant",
        "content": content or "Planning tool calls requested.",
    }
    tool_calls: List[Dict[str, Any]] = []
    assistant_calls: List[Dict[str, Any]] = []
    for call in raw_calls:
        function = _value(call, "function", {}) or {}
        name = str(_value(function, "name", ""))
        arguments = _value(function, "arguments", {})
        args_error = ""
        if isinstance(arguments, str):
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                # Keep args empty so tool invocation still sees a mapping, but
                # record why: otherwise truncated JSON is indistinguishable from
                # an empty call and surfaces as a misleading "field required".
                parsed_arguments = {}
                args_error = str(exc)
            wire_arguments = arguments
        elif isinstance(arguments, Mapping):
            parsed_arguments = dict(arguments)
            wire_arguments = json.dumps(parsed_arguments)
        else:
            parsed_arguments = {}
            args_error = f"arguments had unusable type {type(arguments).__name__}"
            wire_arguments = "{}"
        call_id = str(_value(call, "id", ""))
        tool_calls.append(
            {
                "name": name,
                "args": parsed_arguments,
                "id": call_id,
                "raw_arguments": wire_arguments,
                "args_error": args_error,
            }
        )
        assistant_calls.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": wire_arguments},
            }
        )
    if assistant_calls:
        assistant_message["tool_calls"] = assistant_calls
    return assistant_message, tool_calls


async def compile_plan_with_tools(
    query: str,
    capabilities: List[AgentCapability],
    history: Optional[List[Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
    operations: Optional[List[RequestedOperation]] = None,
    workflow_candidates: Optional[List[WorkflowPlanningCandidate]] = None,
    forced_workflow_id: Optional[str] = None,
    forced_workflow_version: Optional[str] = None,
    forced_selection_source: Optional[str] = None,
    status_callback: Optional[Callable[[str], None]] = None,
    max_turns: int = 8,
) -> PlanningResult:
    """
    Compile routing/plan decisions using LLM tool calling.

    Who uses this:
    - `chat(...)` in `agent.py` for new user turns and plan refinements.
    """
    history = history or []
    resolved_query = query
    resolution_kind: Optional[str] = "new_task"
    referenced_invocation_id: Optional[str] = None
    if operations is None:
        resolution = await resolve_turn(
            query=query,
            history=history,
            context=context,
            status_callback=status_callback,
        )
        resolution_kind = resolution.resolution_kind
        referenced_invocation_id = resolution.referenced_invocation_id
        if resolution.resolution_kind not in {
            "new_task",
            "repeat_prior_task_with_changes",
        }:
            return PlanningResult(
                outcome="fallback",
                message=resolution.message,
                resolution_kind=resolution.resolution_kind,
                referenced_invocation_id=resolution.referenced_invocation_id,
            )
        resolved_query = resolution.standalone_request
        decomposition = await decompose_task(
            query=resolved_query,
            status_callback=status_callback,
        )
        operations = list(decomposition.operations)
    elif not operations:
        raise PlanningContractError(
            "Task planning requires at least one decomposed operation."
        )

    capabilities_by_skill = {cap.skill_id: cap for cap in capabilities}
    draft = _PlanDraft(
        operations=list(operations),
        resolved_query=resolved_query,
        resolution_kind=resolution_kind,
        referenced_invocation_id=referenced_invocation_id,
    )

    if not capabilities_by_skill:
        return PlanningResult(
            outcome="unsupported",
            operations=list(operations),
            unsupported_operations=[
                UnsupportedOperationInput(
                    operation_id=operation.operation_id,
                    reason="No registered capability is available for this operation.",
                )
                for operation in operations
            ],
            resolved_query=resolved_query,
            resolution_kind=resolution_kind,
            referenced_invocation_id=referenced_invocation_id,
        )

    candidate_list = list(workflow_candidates or [])
    if forced_workflow_id:
        # If forced selection isn't already present, keep best-effort synthetic candidate.
        exists = any(
            c.workflow_id == forced_workflow_id
            and (forced_workflow_version is None or c.workflow_version == forced_workflow_version)
            for c in candidate_list
        )
        if not exists:
            candidate_list.append(
                WorkflowPlanningCandidate(
                    workflow_id=forced_workflow_id,
                    workflow_version=forced_workflow_version or "",
                    score=1.0,
                    required_paths=[],
                    selection_source=forced_selection_source or "catalog",
                    skills=[],
                    execution_mode="sequential",
                )
            )

    tools = _build_planning_tools(
        draft,
        capabilities_by_skill,
        context=context,
        workflow_candidates=candidate_list,
    )
    tools_by_name = {tool.name: tool for tool in tools}

    system_prompt = SYSTEM_PROMPT
    user_prompt = _build_prompt(
        query=resolved_query,
        history=history,
        context=context,
        capabilities=capabilities,
        operations=list(operations),
        workflow_candidates=candidate_list,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    tool_schemas = [_planning_tool_schema(tool) for tool in tools]

    async with runtime.create_llm() as llm:
        for _ in range(max(1, max_turns)):
            if status_callback:
                status_callback("Planner LLM evaluating routing/tool calls.")
            response = await llm.medium(
                messages,
                temperature=0,
                max_tokens=2048,
                tools=tool_schemas,
            )
            assistant_message, tool_calls = _planning_tool_calls(response.raw)
            messages.append(assistant_message)

            if not tool_calls:
                if draft.finalized:
                    break
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Planning is not complete. You must set exhaustive operation coverage "
                            "and call finalize_plan."
                        ),
                    }
                )
                continue

            for call in tool_calls:
                tool_name = str(call.get("name"))
                tool_args = call.get("args", {}) or {}
                tool_id = str(call.get("id") or "")
                tool = tools_by_name.get(tool_name)
                if tool is None:
                    tool_result = {"ok": False, "error": f"Unknown tool '{tool_name}'"}
                else:
                    try:
                        tool_result = tool.invoke(tool_args)
                    except Exception as exc:
                        tool_result = {"ok": False, "error": f"{tool_name} failed: {exc}"}

                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(tool_result, default=str),
                        "tool_call_id": tool_id,
                    }
                )
            if draft.finalized:
                break

    if not draft.finalized:
        raise PlanningContractError(
            f"Planner did not finalize a valid decision within {max(1, max_turns)} turns."
        )

    if draft.outcome == "agent_plan" and draft.primary_skill:
        if not draft.steps:
            draft.steps = _default_steps_from_selection(
                primary_skill=draft.primary_skill,
                supporting_skills=draft.supporting_skills,
                capabilities_by_skill=capabilities_by_skill,
            )
        if not draft.message:
            draft.message = "I've created an execution plan. Please review and confirm."

    return draft.to_result()
