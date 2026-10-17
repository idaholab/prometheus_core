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

"""Tool-calling orchestration loop.

Every registered skill (and workflow template) is a tool. The LLM sees the
whole conversation — user turns, its own earlier tool calls, and their compact
results with artifact ids — and decides the next fully parameterized call after
each result arrives. Decomposition, chaining, and data flow between steps are
ordinary tool-calling behavior; there is no up-front plan.

The unfinished tool calls of the latest assistant message ("pending calls")
persist in conversation state, so the loop can pause for a form, an approval,
or a specialist's INPUT_REQUIRED and resume on a later request. See
``docs/docs/dev-docs/agent-loop-orchestration.md``.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from jsonschema import Draft202012Validator
from prometheus_api import load_prompt
from prometheus_api.llm_client import (
    ToolCall,
    ToolDefinition,
    assistant_message,
    tool_result_message,
)

from artifact_handling import (
    extract_artifact_field_paths,
    merge_artifacts_into_context,
    summarize_artifacts_for_context,
)
from capability_cache import AgentCapability, get_capability_cache
from param_schema import (
    extract_required_param_paths,
    flatten_schema_properties,
    get_nested_value,
    has_param_path,
    normalize_params_for_input_schema,
    set_nested_value,
)
from workflow_library import (
    execute_workflow,
    get_workflow_registry,
    verify_workflow_source_health,
    workflow_tool_name,
)

from . import runtime
from .llm_model import ORCHESTRATOR_LLM_ALIAS, cached_llm_model, resolve_llm_model
from .skills import invoke_skill
from .utils import extract_result_text

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_TEMPLATE = load_prompt("orchestrator_system.txt", prompts_dir=PROMPTS_DIR)

MAX_LLM_TURNS = 12
MAX_TRANSCRIPT_MESSAGES = 80
SUMMARY_CHARS = 2000
RESULT_CHARS = 6000
# Newest-inputs digest in the system prompt: skills listed, chars per skill.
MAX_DIGEST_SKILLS = 20
DIGEST_INPUT_CHARS = 400
ASK_USER_TOOL = "ask_user"
# Attached by the orchestrator on every invocation; never model-authored.
ORCHESTRATOR_PARAMS = {"artifacts", "conversation_id"}

_TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_SCHEMA_MAP_KEYS = {"properties", "patternProperties", "$defs", "definitions"}

ToolKind = Literal["skill", "workflow", "ask_user"]
CallStatus = Literal[
    "needs_args",  # required user-input parameters missing → form
    "needs_answer",  # ask_user question → form
    "needs_approval",  # skill/workflow requires approval → plan_ready
    "ready",  # validated, runnable
    "resume",  # INPUT_REQUIRED answered, resume the same A2A task
    "waiting_input",  # specialist returned INPUT_REQUIRED → form
    "done",  # has a tool-result message
]
USER_BLOCKING = {"needs_args", "needs_answer", "waiting_input"}


@dataclass(frozen=True)
class ToolSpec:
    """One tool advertised to the orchestrator LLM."""

    name: str
    kind: ToolKind
    target: str
    label: str
    agent_name: str
    description: str
    parameters: Dict[str, Any]
    input_schema: Dict[str, Any] = field(default_factory=dict)
    user_required: Tuple[str, ...] = ()
    runtime_required: Tuple[str, ...] = ()
    requires_approval: bool = False
    expected_duration_seconds: int = 30
    # Workflow tools only: form metadata per required input path.
    form_fields: Tuple[Dict[str, Any], ...] = ()

    def definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name, description=self.description, parameters=self.parameters)


@dataclass
class LoopOutcome:
    """Where :func:`advance` stopped."""

    kind: Literal["final", "needs_info", "needs_approval", "error"]
    message: str = ""
    questions: List[Dict[str, Any]] = field(default_factory=list)
    plan: Optional[Dict[str, Any]] = None


ASK_USER_SPEC = ToolSpec(
    name=ASK_USER_TOOL,
    kind="ask_user",
    target=ASK_USER_TOOL,
    label="Ask user",
    agent_name="orchestrator",
    description=(
        "Ask the user open clarification questions that no skill parameter captures. "
        "The questions are shown as a form; the answers come back as this tool's result."
    ),
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "snake_case key for the answer."},
                        "question": {"type": "string", "description": "Question shown to the user."},
                        "type": {"type": "string", "enum": ["text", "number", "select", "checkbox"]},
                        "options": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["field", "question"],
                },
            }
        },
        "required": ["questions"],
    },
)


# --------------------------------------------------------------------------- #
# Tool catalog
# --------------------------------------------------------------------------- #


def _tool_name(raw: str) -> str:
    name = _TOOL_NAME_RE.sub("_", str(raw or "")).strip("_") or "tool"
    return name[:64]


def _unique_tool_name(base: str, taken: Mapping[str, Any]) -> str:
    name = base
    index = 2
    while name in taken:
        suffix = f"_{index}"
        name = f"{base[: 64 - len(suffix)]}{suffix}"
        index += 1
    return name


def _clean_schema(node: Any) -> Any:
    """Drop vendor keywords (``x_*`` / ``x-*``) so providers see plain JSON Schema."""
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: Dict[str, Any] = {}
    for key, value in node.items():
        if key in _SCHEMA_MAP_KEYS and isinstance(value, dict):
            cleaned[key] = {name: _clean_schema(sub) for name, sub in value.items()}
        elif key.startswith(("x_", "x-")):
            continue
        else:
            cleaned[key] = _clean_schema(value)
    return cleaned


def _advertised_parameters(input_schema: Dict[str, Any]) -> Dict[str, Any]:
    schema = copy.deepcopy(input_schema) if isinstance(input_schema, dict) else {}
    properties_by_path = flatten_schema_properties(schema)
    for path, mode in extract_artifact_field_paths(schema).items():
        prop = properties_by_path.get(path)
        if prop is None:
            continue
        hint = (
            "List of artifact_ids of existing conversation artifacts."
            if mode == "multiple"
            else "artifact_id of an existing conversation artifact."
        )
        prop["description"] = f"{prop.get('description', '')} {hint}".strip()
    schema = _clean_schema(schema)
    properties = dict(schema.get("properties") or {})
    for name in ORCHESTRATOR_PARAMS:
        properties.pop(name, None)
    schema["type"] = "object"
    schema["properties"] = properties
    required = [name for name in schema.get("required") or [] if name in properties]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    return schema


def _skill_spec(name: str, capability: AgentCapability) -> ToolSpec:
    input_schema = capability.input_schema if isinstance(capability.input_schema, dict) else {}
    # Users never type artifact ids: a missing artifact reference is the model's to fill.
    artifact_paths = extract_artifact_field_paths(input_schema)
    user_required = [
        path for path in extract_required_param_paths(input_schema)
        if path.split(".", 1)[0] not in ORCHESTRATOR_PARAMS and path not in artifact_paths
    ]
    all_required = [
        path for path in extract_required_param_paths(input_schema, include_internal=True)
        if path.split(".", 1)[0] not in ORCHESTRATOR_PARAMS
    ]
    description = capability.description or capability.skill_name
    if capability.usage_notes:
        description = f"{description}\nUsage: {capability.usage_notes}"
    if capability.requires_approval:
        description = f"{description}\nRequires user approval before it runs."
    return ToolSpec(
        name=name,
        kind="skill",
        target=capability.skill_id,
        label=capability.skill_name or capability.skill_id,
        agent_name=capability.agent_name,
        description=description,
        parameters=_advertised_parameters(input_schema),
        input_schema=input_schema,
        user_required=tuple(user_required),
        runtime_required=tuple(path for path in all_required if path not in user_required),
        requires_approval=bool(capability.requires_approval),
        expected_duration_seconds=int(capability.expected_duration_seconds or 30),
    )


def _json_type(field_type: Any) -> str:
    text = str(field_type or "").strip().lower()
    if text in {"number", "float"}:
        return "number"
    if text == "integer":
        return "integer"
    if text in {"boolean", "checkbox"}:
        return "boolean"
    return "string"


def _workflow_spec(
    name: str,
    workflow: Any,
    capabilities_by_skill: Dict[str, AgentCapability],
) -> ToolSpec:
    definition = workflow.definition
    form = get_workflow_registry().build_input_form(
        workflow_id=definition.id,
        version=definition.version,
        capabilities_by_skill=capabilities_by_skill,
    )
    properties: Dict[str, Any] = {}
    for form_field in form.get("fields", []):
        prop: Dict[str, Any] = {
            "type": _json_type(form_field.get("type")),
            "description": str(form_field.get("description") or form_field.get("label") or ""),
        }
        if isinstance(form_field.get("options"), list) and form_field["options"]:
            prop["enum"] = [str(option) for option in form_field["options"]]
        properties[str(form_field["field"])] = prop
    steps = ", ".join(step.skill_id for step in definition.steps)
    description = f"{definition.name}: {definition.description}\nSteps: {steps}"
    if definition.metadata.requires_approval:
        description = f"{description}\nRequires user approval before it runs."
    return ToolSpec(
        name=name,
        kind="workflow",
        target=definition.id,
        label=definition.ui.display_name or definition.name,
        agent_name="workflow",
        description=description,
        parameters={"type": "object", "properties": properties},
        user_required=tuple(workflow.required_input_paths),
        requires_approval=bool(definition.metadata.requires_approval),
        expected_duration_seconds=int(definition.metadata.estimated_duration_seconds or 120),
        form_fields=tuple(form.get("fields", [])),
    )


async def build_tool_catalog() -> Dict[str, ToolSpec]:
    """Advertise every registered skill and workflow template as a tool."""
    capabilities = await get_capability_cache().get_capabilities()
    specs: Dict[str, ToolSpec] = {ASK_USER_TOOL: ASK_USER_SPEC}
    for capability in capabilities:
        name = _unique_tool_name(_tool_name(capability.skill_id), specs)
        specs[name] = _skill_spec(name, capability)
    if runtime.ENABLE_WORKFLOW_LIBRARY:
        capabilities_by_skill = {cap.skill_id: cap for cap in capabilities}
        seen_ids: set[str] = set()
        # list_all() is sorted by (id, version); the last entry per id is the newest.
        for workflow in reversed(get_workflow_registry().list_all()):
            if workflow.definition.id in seen_ids:
                continue
            seen_ids.add(workflow.definition.id)
            name = _unique_tool_name(workflow_tool_name(workflow.definition.id), specs)
            specs[name] = _workflow_spec(name, workflow, capabilities_by_skill)
    return specs


def workflow_tool_for(catalog: Mapping[str, ToolSpec], workflow_id: str) -> Optional[ToolSpec]:
    for spec in catalog.values():
        if spec.kind == "workflow" and spec.target == workflow_id:
            return spec
    return None


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #


def _call_record(call: ToolCall) -> Dict[str, Any]:
    return {
        "id": call.id or f"call_{uuid.uuid4().hex[:16]}",
        "name": call.name,
        "arguments": dict(call.arguments),
        "arguments_error": call.arguments_error,
    }


def begin_user_turn(
    state: Dict[str, Any],
    query: str,
    *,
    uploaded_artifact_ids: Optional[List[str]] = None,
    received_files: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Append a user message and reset per-turn bookkeeping."""
    content = str(query or "").strip()
    catalog = {
        artifact["artifact_id"]: artifact
        for artifact in summarize_artifacts_for_context((state.get("context") or {}).get("artifacts"))
    }
    uploaded = [
        f"{artifact_id} ({catalog[artifact_id]['name']})" if artifact_id in catalog else artifact_id
        for artifact_id in uploaded_artifact_ids or []
    ]
    if uploaded:
        content += "\n\n[Files uploaded with this message: " + ", ".join(uploaded) + "]"
    unstored = [str(item.get("name") or "") for item in received_files or [] if isinstance(item, dict)]
    if any(unstored):
        content += "\n\n[Files received but not stored: " + ", ".join(filter(None, unstored)) + "]"
    messages = state.setdefault("llm_messages", [])
    messages.append({"role": "user", "content": content or "(empty message)"})
    state["llm_messages"] = trim_transcript(messages)
    state["pending_calls"] = []
    state["pending_note"] = ""
    state["turn_tool_results"] = {}
    state["turn_tool_inputs"] = {}


def trim_transcript(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop the oldest turns, cutting only at user messages so no tool result is orphaned."""
    if len(messages) <= MAX_TRANSCRIPT_MESSAGES:
        return messages
    start = len(messages) - MAX_TRANSCRIPT_MESSAGES
    for index in range(start, len(messages)):
        if messages[index].get("role") == "user":
            return messages[index:]
    return messages


def inject_tool_call(
    state: Dict[str, Any],
    catalog: Mapping[str, ToolSpec],
    spec: ToolSpec,
    arguments: Dict[str, Any],
    note: str,
    *,
    workflow_version: Optional[str] = None,
    selection_source: Optional[str] = None,
) -> None:
    """Record a platform-chosen call (explicit workflow start) as if the model made it."""
    call_id = f"call_{uuid.uuid4().hex[:16]}"
    state["llm_messages"].append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": spec.name, "arguments": json.dumps(arguments)},
                }
            ],
        }
    )
    state["pending_note"] = note
    call = _new_call(
        {"id": call_id, "name": spec.name, "arguments": arguments, "arguments_error": None},
        catalog,
        state,
    )
    if workflow_version:
        call["workflow_version"] = workflow_version
    if selection_source:
        call["selection_source"] = selection_source
    state["pending_calls"] = [call]


# Bookkeeping keys conversation_store adds to persisted messages; never sent to the LLM.
_MESSAGE_TAGS = ("turn_id", "turn_started_at")
_SUPERSEDED_RESULT = json.dumps(
    {"status": "not_executed", "message": "This call was superseded by a later turn and never ran."}
)


def llm_view(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The persisted transcript as a provider-valid message list.

    Turns of one conversation can run concurrently and are stored as per-turn blocks
    (``conversation_store``), so a tool result can be separated from its call (a
    turn resumed after another turn ran in between) or never arrive (a superseded
    pending call). Each call gets exactly one result, directly after its assistant
    message: the stored one when it exists, otherwise a "not executed" result.
    Results with no call are dropped. Bookkeeping tags are stripped.
    """
    results: Dict[str, Dict[str, Any]] = {}
    for message in messages:
        if message.get("role") == "tool":
            results.setdefault(str(message.get("tool_call_id") or ""), message)
    view: List[Dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "tool":
            continue
        view.append({key: value for key, value in message.items() if key not in _MESSAGE_TAGS})
        for tool_call in message.get("tool_calls") or []:
            call_id = str(tool_call.get("id") or "")
            stored = results.pop(call_id, None)
            if stored is None:
                view.append(tool_result_message(call_id, _SUPERSEDED_RESULT))
            else:
                view.append({key: value for key, value in stored.items() if key not in _MESSAGE_TAGS})
    return view


def _system_prompt(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> str:
    artifacts = summarize_artifacts_for_context((state.get("context") or {}).get("artifacts"))
    lines = [
        f"- {artifact['artifact_id']}: {artifact['name']}"
        f" ({artifact.get('mime_type') or 'unknown type'})"
        + (f" — {artifact['description']}" if artifact.get("description") else "")
        for artifact in artifacts
    ]
    return (
        SYSTEM_PROMPT_TEMPLATE
        .replace("{artifact_catalog}", "\n".join(lines) or "(none)")
        .replace("{recent_skill_inputs}", "\n".join(recent_skill_inputs(state, catalog)) or "(none)")
        .replace("{llm_model}", cached_llm_model() or "unknown")
    )


def _restrict_to_schema(value: Any, schema: Any) -> Any:
    """Keep only the fields ``schema`` declares; parts without declared properties pass through."""
    if not isinstance(schema, dict):
        return value
    properties = schema.get("properties")
    if isinstance(value, dict) and isinstance(properties, dict):
        return {key: _restrict_to_schema(item, properties[key]) for key, item in value.items() if key in properties}
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_restrict_to_schema(item, schema["items"]) for item in value]
    return value


def recent_skill_inputs(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> List[str]:
    """The newest successful inputs of each skill across the whole conversation.

    The transcript is trimmed (``trim_transcript``), so a follow-up such as "redo
    it with 6 holes" can refer to a call the model no longer sees. The history
    keeps every turn's ``tool_inputs``; the newest entry per skill wins. Entries
    are cut to the skill's current input schema, and skills no longer in the
    catalog are left out, so the model never copies a field a skill dropped.
    """
    schemas = {spec.target: spec.input_schema for spec in catalog.values() if spec.kind == "skill"}
    newest: Dict[str, Dict[str, Any]] = {}
    for entry in reversed(state.get("conversation_history") or []):
        tool_inputs = entry.get("tool_inputs") if isinstance(entry, dict) else None
        if not isinstance(tool_inputs, dict):
            continue
        # Within one turn, the highest repeat (skill#3) is the newest call.
        for key in sorted(tool_inputs, key=_repeat_index, reverse=True):
            skill_id = key.split("#", 1)[0]
            if skill_id not in newest and skill_id in schemas and isinstance(tool_inputs[key], dict):
                inputs = {name: value for name, value in tool_inputs[key].items() if name not in ORCHESTRATOR_PARAMS}
                newest[skill_id] = _restrict_to_schema(inputs, schemas[skill_id])
        if len(newest) >= MAX_DIGEST_SKILLS:
            break
    return [
        f"- {skill_id}: {_truncate(json.dumps(inputs, default=str), DIGEST_INPUT_CHARS)}"
        for skill_id, inputs in list(newest.items())[:MAX_DIGEST_SKILLS]
    ]


def _repeat_index(key: str) -> int:
    _, _, index = key.partition("#")
    return int(index) if index.isdigit() else 1


# --------------------------------------------------------------------------- #
# Call validation and status
# --------------------------------------------------------------------------- #


def _finish(call: Dict[str, Any], payload: Dict[str, Any]) -> None:
    call["status"] = "done"
    call["content"] = json.dumps(payload, default=str)


def _known_artifact_ids(state: Dict[str, Any]) -> List[str]:
    return [
        artifact["artifact_id"]
        for artifact in summarize_artifacts_for_context((state.get("context") or {}).get("artifacts"))
    ]


def _validation_problem(spec: ToolSpec, arguments: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    """Return an error for the model, or None. Missing user inputs are not errors."""
    if spec.kind != "skill":
        return None
    missing_runtime = [path for path in spec.runtime_required if not has_param_path(arguments, path)]
    if missing_runtime:
        return (
            f"Missing required input(s) {', '.join(missing_runtime)}. These are produced by other "
            "skills; call the upstream skill first and pass its result, or pass an artifact_id "
            "from the artifact catalog."
        )
    try:
        errors = list(Draft202012Validator(_clean_schema(spec.input_schema)).iter_errors(arguments))
    except Exception:  # a malformed agent-card schema must not block the call
        errors = []
    problems = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '(root)'}: {error.message}"
        for error in errors
        if error.validator != "required"
    ]
    if problems:
        return "Invalid arguments: " + "; ".join(problems[:5])
    known = set(_known_artifact_ids(state))
    for path, mode in extract_artifact_field_paths(spec.input_schema).items():
        value = get_nested_value(arguments, path)
        if value is None:
            continue
        values = value if mode == "multiple" and isinstance(value, list) else [value]
        unknown = [str(item) for item in values if str(item) not in known]
        if unknown:
            return (
                f"Unknown artifact_id {', '.join(unknown)} for '{path}'. Use an artifact_id from a "
                f"tool result or the artifact catalog. Known: {', '.join(sorted(known)) or 'none'}."
            )
    return None


def _missing_user_inputs(spec: ToolSpec, arguments: Dict[str, Any]) -> List[str]:
    return [path for path in spec.user_required if not has_param_path(arguments, path)]


def _refresh_status(call: Dict[str, Any], spec: ToolSpec) -> None:
    missing = _missing_user_inputs(spec, call["arguments"])
    call["missing"] = missing
    if missing:
        call["status"] = "needs_args"
    elif spec.requires_approval and not call.get("approved"):
        call["status"] = "needs_approval"
    else:
        call["status"] = "ready"


def _normalize_questions(raw: Any) -> List[Dict[str, Any]]:
    questions: List[Dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("field") or "").strip()
        text = str(item.get("question") or "").strip()
        if not name or not text:
            continue
        question: Dict[str, Any] = {"field": name, "question": text, "type": item.get("type") or "text"}
        if isinstance(item.get("options"), list) and item["options"]:
            question["options"] = [str(option) for option in item["options"]]
            question["type"] = "select"
        questions.append(question)
    return questions


def _new_call(
    tool_call: Dict[str, Any],
    catalog: Mapping[str, ToolSpec],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    name = str(tool_call.get("name") or "")
    spec = catalog.get(name)
    call: Dict[str, Any] = {
        "id": tool_call["id"],
        "name": name,
        "kind": spec.kind if spec else None,
        "target": spec.target if spec else None,
        "arguments": dict(tool_call.get("arguments") or {}),
        "status": "ready",
        "content": None,
    }
    if tool_call.get("arguments_error"):
        _finish(call, {"status": "failed", "error": f"Invalid tool-call arguments: {tool_call['arguments_error']}"})
        return call
    if spec is None:
        _finish(call, {"status": "failed", "error": f"Unknown tool '{name}'."})
        return call
    if spec.kind == "ask_user":
        questions = _normalize_questions(call["arguments"].get("questions"))
        if not questions:
            _finish(call, {"status": "failed", "error": "ask_user needs at least one question with field and question."})
            return call
        call["questions"] = questions
        call["status"] = "needs_answer"
        return call
    if spec.kind == "skill":
        call["arguments"] = normalize_params_for_input_schema(call["arguments"], spec.input_schema)
    problem = _validation_problem(spec, call["arguments"], state)
    if problem:
        _finish(call, {"status": "failed", "error": problem})
        return call
    _refresh_status(call, spec)
    return call


# --------------------------------------------------------------------------- #
# User input: forms, free text, approval
# --------------------------------------------------------------------------- #


def coerce_answer(value: Any, value_type: Any) -> Any:
    """Coerce a form-submitted value to the requested type; blank means absent."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    kind = str(value_type or "").strip().lower()
    try:
        if kind in {"number", "float"}:
            return float(value)
        if kind == "integer":
            return int(value)
    except (TypeError, ValueError):
        return None  # unparseable: treat as absent so the form asks again
    if kind in {"boolean", "checkbox"} and not isinstance(value, bool):
        return str(value).strip().lower() in {"true", "yes", "1", "on"}
    return value


def _answer_for(answers: Mapping[str, Any], path: str) -> Any:
    if path in answers:
        return answers[path]
    leaf = path.rsplit(".", 1)[-1]
    return answers.get(leaf)


def apply_answers(
    state: Dict[str, Any],
    catalog: Mapping[str, ToolSpec],
    answers: Mapping[str, Any],
) -> None:
    """Route submitted form values to every pending call that asked for them."""
    context = state.setdefault("context", {})
    for call in state.get("pending_calls") or []:
        spec = catalog.get(call["name"])
        status = call["status"]
        if status == "needs_args" and spec is not None:
            properties = (
                flatten_schema_properties(spec.input_schema)
                if spec.kind == "skill"
                else {str(form_field["field"]): form_field for form_field in spec.form_fields}
            )
            for path in list(call.get("missing") or []):
                value = coerce_answer(_answer_for(answers, path), (properties.get(path) or {}).get("type"))
                if value is None:
                    continue
                if spec.kind == "skill":
                    set_nested_value(call["arguments"], path, value)
                else:
                    call["arguments"][path] = value
            problem = _validation_problem(spec, call["arguments"], state)
            if problem:
                _finish(call, {"status": "failed", "error": problem})
                continue
            _refresh_status(call, spec)
        elif status == "needs_answer":
            provided = {
                question["field"]: answers[question["field"]]
                for question in call.get("questions") or []
                if question["field"] in answers
            }
            if provided:
                _finish(call, {"status": "answered", "answers": provided})
        elif status == "waiting_input":
            provided: Dict[str, Any] = {}
            for item in call.get("missing_inputs") or []:
                name = str(item.get("name") or "").strip()
                if not name or name not in answers:
                    continue
                value = coerce_answer(answers[name], item.get("type"))
                if value is None:
                    continue
                provided[name] = value
                if not item.get("sensitive"):
                    context[name] = value
                    call.setdefault("recorded_inputs", {})[name] = value
            if provided:
                call["provided_inputs"] = provided
                call["status"] = "resume"


def sensitive_fields(state: Dict[str, Any]) -> set[str]:
    """Names of the inputs pending calls asked for as sensitive; never persisted."""
    return {
        str(item.get("name") or "")
        for call in state.get("pending_calls") or []
        for item in call.get("missing_inputs") or []
        if item.get("sensitive")
    }


def apply_reply(state: Dict[str, Any], text: str) -> None:
    """A free-text reply answers ask_user and supersedes every other unfinished call."""
    for call in state.get("pending_calls") or []:
        if call["status"] == "done":
            continue
        if call["status"] == "needs_answer":
            _finish(call, {"status": "answered", "reply": text})
        else:
            _finish(
                call,
                {
                    "status": "not_executed",
                    "message": f"Not executed: the user replied instead: {text}",
                },
            )


def approve_pending(state: Dict[str, Any]) -> None:
    for call in state.get("pending_calls") or []:
        if call["status"] == "needs_approval":
            call["approved"] = True
            call["status"] = "ready"


def reject_pending(state: Dict[str, Any]) -> None:
    for call in state.get("pending_calls") or []:
        if call["status"] != "done":
            _finish(call, {"status": "rejected", "message": "The user rejected this call."})
    commit_batch(state)


def commit_batch(state: Dict[str, Any]) -> None:
    """Append one tool-result message per call, in call order, and clear the batch."""
    for call in state.get("pending_calls") or []:
        state["llm_messages"].append(tool_result_message(call["id"], call.get("content") or ""))
    state["pending_calls"] = []
    state["pending_note"] = ""


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"… [truncated {len(text) - limit} chars]"


def _compact_result(result: Any, status: str) -> Dict[str, Any]:
    """What the model sees of a skill result: summary, artifact ids, bounded payload."""
    payload: Dict[str, Any] = {"status": status}
    artifacts = summarize_artifacts_for_context(result.get("artifacts") if isinstance(result, dict) else None)
    if artifacts:
        payload["artifacts"] = [
            {key: artifact.get(key) for key in ("artifact_id", "name", "mime_type", "description")}
            for artifact in artifacts
        ]
    summary = extract_result_text(result)
    if isinstance(result, dict):
        remainder = {key: value for key, value in result.items() if key not in {"artifacts", "artifact"}}
        encoded = json.dumps(remainder, default=str)
        if summary.strip() != json.dumps(result, indent=2):
            payload["summary"] = _truncate(summary, SUMMARY_CHARS)
        payload["result"] = _truncate(encoded, RESULT_CHARS)
    else:
        payload["summary"] = _truncate(summary, SUMMARY_CHARS)
    return payload


def _result_key(state: Dict[str, Any], base: str) -> str:
    """A turn-unique result key: ``base`` first, then ``base#2``, ``base#3``..."""
    taken = state.setdefault("turn_tool_results", {})
    if base not in taken:
        return base
    index = 2
    while f"{base}#{index}" in taken:
        index += 1
    return f"{base}#{index}"


def _record_result(state: Dict[str, Any], key: str, arguments: Dict[str, Any], result: Any) -> None:
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    state["context"] = merge_artifacts_into_context(state.get("context") or {}, artifacts or [])
    state.setdefault("turn_tool_results", {})[key] = result
    state.setdefault("turn_tool_inputs", {})[key] = copy.deepcopy(arguments)


def _resolve_from_context(
    missing_inputs: List[Dict[str, Any]],
    arguments: Dict[str, Any],
    context: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Answer ``resolvable_from_context`` inputs from the call's arguments or state context."""
    resolved: Dict[str, Any] = {}
    unresolved: List[Dict[str, Any]] = []
    for item in missing_inputs or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value = None
        if item.get("resolvable_from_context"):
            for source in (arguments, context):
                if has_param_path(source, name):
                    value = get_nested_value(source, name)
                    break
        if value is None:
            unresolved.append(item)
        else:
            resolved[name] = value
    return resolved, unresolved


def _a2a_resume_fields(record: Mapping[str, Any]) -> Dict[str, Any]:
    fields = {
        "_a2a_context_id": record.get("a2a_context_id"),
        "_a2a_task_id": record.get("a2a_task_id"),
        "_task_graph_root_id": record.get("task_graph_root_id"),
        "_task_graph_node_id": record.get("task_graph_node_id"),
    }
    return {key: value for key, value in fields.items() if value}


def _blocked_record(skill_id: str, item: Mapping[str, Any], missing: List[Dict[str, Any]], hint: Any) -> Dict[str, Any]:
    return {
        "skill_id": skill_id,
        "a2a_context_id": item.get("_a2a_context_id"),
        "a2a_task_id": item.get("_a2a_task_id"),
        "task_graph_root_id": item.get("_task_graph_root_id"),
        "task_graph_node_id": item.get("_task_graph_node_id"),
        "missing_inputs": missing,
        "hint": hint,
    }


def _invocation_params(call: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    params = copy.deepcopy(call["arguments"])
    artifacts = summarize_artifacts_for_context((state.get("context") or {}).get("artifacts"))
    if artifacts:
        params["artifacts"] = artifacts
    return params


async def _settle_skill_item(
    call: Dict[str, Any],
    item: Dict[str, Any],
    state: Dict[str, Any],
    params: Dict[str, Any],
) -> None:
    """Turn one invoke_skill outcome into a finished call or an INPUT_REQUIRED pause."""
    skill_id = call["target"]
    conversation_id = str(state.get("conversation_id") or "")
    if item.get("input_required"):
        payload = item.get("input_required") or {}
        missing = payload.get("missing_inputs", []) if isinstance(payload, dict) else []
        resolved, unresolved = _resolve_from_context(missing, call["arguments"], state.get("context") or {})
        if resolved and not call.get("auto_resumed"):
            call["auto_resumed"] = True
            call.setdefault("recorded_inputs", {}).update(resolved)
            resumed = await invoke_skill(
                skill_id,
                {**params, "provided_inputs": resolved, **_a2a_resume_fields(_blocked_record(skill_id, item, [], None))},
                conversation_id,
                emit_status=False,
            )
            await _settle_skill_item(call, resumed, state, params)
            return
        hint = payload.get("hint") if isinstance(payload, dict) else None
        call.update(_blocked_record(skill_id, item, unresolved or missing, hint))
        call["status"] = "waiting_input"
        return
    if "error" in item:
        state.setdefault("turn_tool_results", {})[_result_key(state, skill_id)] = {"error": item["error"]}
        _finish(call, {"status": "failed", "error": str(item["error"])})
        return
    result = item.get("result")
    # Inputs given after the call was made (form answers, values resolved from
    # context) belong to the invocation's record, and the model must see them.
    recorded = call.pop("recorded_inputs", {})
    _record_result(state, _result_key(state, skill_id), {**call["arguments"], **recorded}, result)
    payload = _compact_result(result, "succeeded")
    if recorded:
        payload["provided_inputs"] = recorded
    _finish(call, payload)


async def _run_skill(call: Dict[str, Any], state: Dict[str, Any]) -> None:
    params = _invocation_params(call, state)
    conversation_id = str(state.get("conversation_id") or "")
    if call["status"] == "resume":
        item = await invoke_skill(
            call["target"],
            {**params, "provided_inputs": call.pop("provided_inputs", {}), **_a2a_resume_fields(call)},
            conversation_id,
        )
    else:
        item = await invoke_skill(call["target"], params, conversation_id)
    await _settle_skill_item(call, item, state, params)


async def _run_workflow(call: Dict[str, Any], state: Dict[str, Any]) -> None:
    conversation_id = str(state.get("conversation_id") or "")
    workflow = get_workflow_registry().get(call["target"], version=call.get("workflow_version"))
    if workflow is None:
        _finish(call, {"status": "failed", "error": f"Workflow '{call['target']}' is unavailable."})
        return

    # step_id -> outcome of every finished step; a resumed run never invokes them again.
    completed = call.setdefault("completed_steps", {})
    step_keys = call.setdefault("step_result_keys", {})
    if call["status"] == "resume":
        # Finish the blocked specialist tasks first, then continue the template
        # from where it stopped. Non-sensitive answers also reach later steps.
        provided = call.pop("provided_inputs", {})
        sensitive = {str(item.get("name") or "") for item in call.get("missing_inputs") or [] if item.get("sensitive")}
        still_blocked: List[Dict[str, Any]] = []
        for record in call.get("blocked_steps") or []:
            step_id = str(record.get("step_id") or record["skill_id"])
            names = {str(item.get("name") or "") for item in record.get("missing_inputs") or []}
            step_inputs = {name: value for name, value in provided.items() if name in names}
            resumed = await invoke_skill(
                record["skill_id"],
                {**_invocation_params(call, state), "provided_inputs": step_inputs, **_a2a_resume_fields(record)},
                conversation_id,
            )
            if resumed.get("input_required"):
                payload = resumed.get("input_required") or {}
                still_blocked.append(
                    {
                        **_blocked_record(
                            record["skill_id"], resumed, payload.get("missing_inputs") or [], payload.get("hint")
                        ),
                        "step_id": step_id,
                        "params": record.get("params") or {},
                    }
                )
            elif "error" in resumed:
                completed[step_id] = {"status": "failed", "error": str(resumed["error"])}
            else:
                recorded = {name: value for name, value in step_inputs.items() if name not in sensitive}
                params = {**(record.get("params") or {}), **recorded}
                completed[step_id] = {"status": "succeeded", "result": resumed.get("result"), "params": params}
                _record_step(state, step_keys, step_id, record["skill_id"], params, resumed.get("result"))
        call["arguments"].update({name: value for name, value in provided.items() if name not in sensitive})
        if still_blocked:
            _pause_workflow(call, still_blocked)
            return

    health_error = await verify_workflow_source_health(workflow)
    if health_error:
        _finish(call, {"status": "failed", "error": health_error})
        return
    runtime.store_status_update(
        conversation_id,
        f"Running workflow '{workflow.definition.id}' ({len(workflow.definition.steps)} steps).",
    )
    context = dict(state.get("context") or {})
    inputs = normalize_params_for_input_schema(call["arguments"])
    artifacts = summarize_artifacts_for_context(context.get("artifacts"))
    if artifacts:
        inputs["artifacts"] = artifacts
    execution = await execute_workflow(
        workflow=workflow,
        input_params=inputs,
        context=context,
        invoke_skill=invoke_skill,
        conversation_id=conversation_id,
        completed_steps=completed,
    )
    # Siblings in the same batch may have merged artifacts into state meanwhile.
    state["context"] = merge_artifacts_into_context(context, (state.get("context") or {}).get("artifacts") or [])
    for step_id, payload in (execution.get("step_results") or {}).items():
        if isinstance(payload, dict) and step_id not in completed:
            params = payload.get("params") or {}
            completed[step_id] = {"status": "succeeded", "result": payload.get("result"), "params": params}
            _record_step(state, step_keys, step_id, str(payload.get("skill_id") or step_id), params, payload.get("result"))
    for error in execution.get("errors") or []:
        if error.get("step_id") and error["step_id"] not in completed:
            completed[error["step_id"]] = {"status": "failed", "error": error.get("error")}

    blocked = [
        {
            **_blocked_record(
                str(step["skill_id"]),
                step,
                (step.get("input_required") or {}).get("missing_inputs") or [],
                (step.get("input_required") or {}).get("hint"),
            ),
            "step_id": step.get("step_id"),
            "params": step.get("params") or {},
        }
        for step in execution.get("input_required_steps") or []
    ]
    if blocked:
        _pause_workflow(call, blocked)
        return

    statuses = execution.get("step_statuses") or {}
    failed = any(status == "failed" for status in statuses.values())
    _finish(
        call,
        {
            "status": "failed" if failed else "succeeded",
            "step_statuses": statuses,
            "errors": execution.get("errors") or [],
            "summary": _truncate(extract_result_text(execution.get("final_output")), SUMMARY_CHARS),
            "final_output": _truncate(json.dumps(execution.get("final_output"), default=str), RESULT_CHARS),
        },
    )


def _record_step(
    state: Dict[str, Any],
    step_keys: Dict[str, str],
    step_id: str,
    skill_id: str,
    params: Dict[str, Any],
    result: Any,
) -> None:
    """Record one workflow step's result under its skill, keeping the key it got first."""
    key = step_keys.get(step_id) or _result_key(state, skill_id)
    step_keys[step_id] = key
    _record_result(state, key, params, result)


def _pause_workflow(call: Dict[str, Any], blocked: List[Dict[str, Any]]) -> None:
    call["blocked_steps"] = blocked
    call["missing_inputs"] = [item for record in blocked for item in record["missing_inputs"]]
    call["hint"] = next((record["hint"] for record in blocked if record.get("hint")), None)
    call["status"] = "waiting_input"


async def _run_call(call: Dict[str, Any], state: Dict[str, Any]) -> None:
    try:
        if call["kind"] == "workflow":
            await _run_workflow(call, state)
        else:
            await _run_skill(call, state)
    except Exception as exc:  # one failing call must not sink its siblings
        logger.exception("Tool call %s (%s %s) failed", call["id"], call["kind"], call["target"])
        _finish(call, {"status": "failed", "error": str(exc)})


# --------------------------------------------------------------------------- #
# Pauses: forms and approval
# --------------------------------------------------------------------------- #


def _question_type(prop: Mapping[str, Any]) -> str:
    kind = str(prop.get("type") or "string").lower()
    if prop.get("enum"):
        return "select"
    if kind in {"number", "integer"}:
        return "number"
    if kind == "boolean":
        return "checkbox"
    return "text"


def _form_questions(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> List[Dict[str, Any]]:
    """Union of every blocking call's questions; one field answers all calls sharing it."""
    questions: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add(question: Dict[str, Any]) -> None:
        if question["field"] not in seen:
            seen.add(question["field"])
            questions.append(question)

    for call in state.get("pending_calls") or []:
        spec = catalog.get(call["name"])
        if call["status"] == "needs_answer":
            for question in call.get("questions") or []:
                add(question)
        elif call["status"] == "needs_args" and spec is not None:
            if spec.kind == "workflow":
                missing = set(call.get("missing") or [])
                for form_field in spec.form_fields:
                    if form_field["field"] not in missing:
                        continue
                    add(
                        {
                            "field": form_field["field"],
                            "question": form_field.get("label") or form_field["field"],
                            "description": form_field.get("description"),
                            "type": _question_type({"type": form_field.get("type"), "enum": form_field.get("options")}),
                            "options": form_field.get("options"),
                        }
                    )
                continue
            properties = flatten_schema_properties(spec.input_schema)
            for path in call.get("missing") or []:
                prop = properties.get(path) or {}
                question = {
                    "field": path,
                    "question": prop.get("title") or path.replace(".", " ").replace("_", " ").capitalize(),
                    "description": prop.get("description"),
                    "type": _question_type(prop),
                }
                if prop.get("enum"):
                    question["options"] = list(prop["enum"])
                add(question)
        elif call["status"] == "waiting_input":
            for item in call.get("missing_inputs") or []:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                kind = str(item.get("type") or "string").strip().lower()
                add(
                    {
                        "field": name,
                        "question": item.get("user_prompt") or item.get("description") or name,
                        "description": item.get("description"),
                        "type": "select" if kind == "enum" or item.get("options") else _question_type({"type": kind}),
                        "options": item.get("options"),
                        "required": bool(item.get("required", True)),
                        "sensitive": bool(item.get("sensitive")),
                        "value_type": kind,
                    }
                )
    return questions


def _plan(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> Dict[str, Any]:
    calls = [call for call in state.get("pending_calls") or [] if call["status"] != "done"]
    steps: List[Dict[str, Any]] = []
    duration = 0
    for call in calls:
        spec = catalog.get(call["name"])
        if spec is None:
            continue
        duration += spec.expected_duration_seconds
        arguments = ", ".join(
            f"{key}={json.dumps(value, default=str)}"
            for key, value in call["arguments"].items()
        )
        steps.append(
            {
                "name": spec.label,
                "agent": spec.agent_name,
                "description": _truncate(f"{spec.target}({arguments})", 400),
            }
        )
    plan: Dict[str, Any] = {
        "intent": state.get("pending_note") or "Review the next step(s) before they run.",
        "steps": steps,
        "skills": [call["target"] for call in calls],
        "workflow_type": "parallel" if len(calls) > 1 else "single",
        "estimated_duration_seconds": duration,
        "required_params": [],
        "param_metadata": {},
    }
    workflow_call = next((call for call in calls if call.get("kind") == "workflow"), None)
    if workflow_call is not None:
        # PlanViewerElement's details panel shows which workflow runs and who chose it.
        plan["workflow_id"] = workflow_call["target"]
        plan["selection_source"] = workflow_call.get("selection_source") or "model"
        if workflow_call.get("workflow_version"):
            plan["workflow_version"] = workflow_call["workflow_version"]
    return plan


def _pause_message(state: Dict[str, Any], default: str) -> str:
    for call in state.get("pending_calls") or []:
        if call["status"] == "waiting_input" and call.get("hint"):
            return str(call["hint"])
    return state.get("pending_note") or default


async def _drive_batch(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> Optional[LoopOutcome]:
    """Run the pending batch as far as possible; return an outcome when the user is needed."""
    calls = state.get("pending_calls") or []
    if any(call["status"] in USER_BLOCKING for call in calls):
        return LoopOutcome(
            "needs_info",
            message=_pause_message(state, "I need some additional information to proceed:"),
            questions=_form_questions(state, catalog),
        )
    if any(call["status"] == "needs_approval" for call in calls):
        return LoopOutcome(
            "needs_approval",
            message=_pause_message(state, "Please review and approve the next step(s):"),
            plan=_plan(state, catalog),
        )
    runnable = [call for call in calls if call["status"] in {"ready", "resume"}]
    if runnable:
        await asyncio.gather(*(_run_call(call, state) for call in runnable))
    if any(call["status"] == "waiting_input" for call in calls):
        return LoopOutcome(
            "needs_info",
            message=_pause_message(state, "A specialist needs additional information to proceed:"),
            questions=_form_questions(state, catalog),
        )
    return None


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


async def advance(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> LoopOutcome:
    """Drive pending calls and LLM turns until a final answer or a user pause."""
    async with contextlib.AsyncExitStack() as stack:
        return await _advance(state, catalog, stack)


async def _advance(
    state: Dict[str, Any],
    catalog: Mapping[str, ToolSpec],
    stack: contextlib.AsyncExitStack,
) -> LoopOutcome:
    conversation_id = str(state.get("conversation_id") or "")
    llm: Any = None  # created on the first LLM turn, reused for the rest of this advance
    turns = 0
    while True:
        if state.get("pending_calls"):
            paused = await _drive_batch(state, catalog)
            if paused is not None:
                return paused
            commit_batch(state)
        if turns >= MAX_LLM_TURNS:
            return LoopOutcome(
                "error",
                message=f"Stopped after {MAX_LLM_TURNS} orchestration steps without reaching an answer.",
            )
        turns += 1
        runtime.store_status_update(conversation_id, "Deciding the next step.")
        state["llm_messages"] = trim_transcript(state["llm_messages"])
        if llm is None:
            # Warm the cache _system_prompt() reads; None (a failed lookup) leaves "unknown".
            await resolve_llm_model(ORCHESTRATOR_LLM_ALIAS)
        messages = [{"role": "system", "content": _system_prompt(state, catalog)}, *llm_view(state["llm_messages"])]
        if llm is None:
            llm = await stack.enter_async_context(runtime.create_llm())
        # llm.medium is the ORCHESTRATOR_LLM_ALIAS flavor whose provider model the system prompt names.
        response = await llm.medium(
            messages,
            tools=[spec.definition() for spec in catalog.values()],
            tool_choice="auto",
            max_tokens=4096,
        )
        # The absence of tool calls is the only terminator (never finish_reason).
        if not response.tool_calls:
            answer = response.text.strip()
            if not answer:
                return LoopOutcome("error", message="The orchestrator returned an empty answer.")
            state["llm_messages"].append(assistant_message(response))
            return LoopOutcome("final", message=answer)
        records = [_call_record(tool_call) for tool_call in response.tool_calls]
        message = assistant_message(response)
        stored_calls = message.get("tool_calls") or []
        if len(stored_calls) == len(records):
            # Generated ids must match in the transcript, or llm_view drops the real result.
            for stored, record in zip(stored_calls, records):
                if not stored.get("id"):
                    stored["id"] = record["id"]
        state["llm_messages"].append(message)
        state["pending_note"] = response.text.strip()
        state["pending_calls"] = [_new_call(record, catalog, state) for record in records]
        for call in state["pending_calls"]:
            if call["status"] in {"ready", "needs_args", "needs_approval"}:
                runtime.store_status_update(conversation_id, f"Next step: '{call['target']}'.")
