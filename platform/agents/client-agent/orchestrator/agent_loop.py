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

"""The client agent's tool catalog and its ADK run.

Every registered skill (and workflow template) is a tool of one ADK
``LlmAgent`` (``adk_tools.build_client_agent``). The model sees the whole
conversation and decides the next fully parameterized call after each result
arrives; decomposition, chaining and data flow between steps are ordinary
tool-calling behavior, and there is no up-front plan.

A chat turn is one ADK run (:func:`run_turn`). A pause (an approval, an
``ask_user`` form, a specialist's INPUT_REQUIRED) is a long-running call in the
ADK session; a later request resumes it by ``invocation_id`` with function
responses (``chat_flow``). See ``docs/docs/dev-docs/agent-loop-orchestration.md``.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from google.adk.agents.invocation_context import new_invocation_context_id
from google.adk.models import BaseLlm

from jsonschema import Draft202012Validator
from prometheus_api import load_prompt
from prometheus_api.agent import PrometheusAgent
from prometheus_api.agent.events import context_id as event_context_id
from prometheus_api.agent.events import context_task_id
from google.adk.runners import Runner
from google.adk.utils._function_call_names import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.genai import types
from prometheus_api.adk import CompactionPolicy, build_runner, prometheus_model
from prometheus_api.adk.plugins.bridge import event_text
from prometheus_api.adk.runner import commit_run_to_memory, ensure_session
from prometheus_api.llm_client import ToolDefinition

from artifact_handling import (
    extract_artifact_field_paths,
    summarize_artifacts_for_context,
)
from capability_cache import AgentCapability, get_capability_cache
from param_schema import (
    extract_required_param_paths,
    flatten_schema_properties,
    get_nested_value,
    has_param_path,
)
from workflow_library import get_workflow_registry, workflow_tool_name

from . import adk_tools, runtime
from .utils import extract_result_text

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_TEMPLATE = load_prompt("orchestrator_system.txt", prompts_dir=PROMPTS_DIR)

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


def upload_note(
    state: Dict[str, Any],
    uploaded_artifact_ids: Optional[List[str]] = None,
    received_files: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """The transcript note that names this message's uploads; "" without uploads."""
    note = ""
    catalog = {
        artifact["artifact_id"]: artifact
        for artifact in summarize_artifacts_for_context((state.get("context") or {}).get("artifacts"))
    }
    uploaded = [
        f"{artifact_id} ({catalog[artifact_id]['name']})" if artifact_id in catalog else artifact_id
        for artifact_id in uploaded_artifact_ids or []
    ]
    if uploaded:
        note += "\n\n[Files uploaded with this message: " + ", ".join(uploaded) + "]"
    unstored = [str(item.get("name") or "") for item in received_files or [] if isinstance(item, dict)]
    if any(unstored):
        note += "\n\n[Files received but not stored: " + ", ".join(filter(None, unstored)) + "]"
    return note


def begin_user_turn(
    state: Dict[str, Any],
    query: str,
    *,
    uploaded_artifact_ids: Optional[List[str]] = None,
    received_files: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Append a user message and reset per-turn bookkeeping."""
    content = str(query or "").strip() + upload_note(state, uploaded_artifact_ids, received_files)
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
        .replace("{recent_skill_inputs}", "\n".join(_skill_input_digest(state, catalog)) or "(none)")
    )


def _skill_input_digest(state: Dict[str, Any], catalog: Mapping[str, ToolSpec]) -> List[str]:
    """The recent skill inputs of the prompt: precomputed by chat_flow in an ADK run, else from the history."""
    digest = state.get(adk_tools.RECENT_SKILL_INPUTS_KEY)
    return list(digest) if isinstance(digest, list) else recent_skill_inputs(state, catalog)


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


# --------------------------------------------------------------------------- #
# The turn: one ADK run of the client agent
# --------------------------------------------------------------------------- #

# The orchestrator compacts early: tool results are large and the window is shared.
COMPACTION = CompactionPolicy(trigger_ratio=0.6)


@dataclass
class TurnOutcome:
    """Where one ADK run of the client agent stopped."""

    session_id: str
    invocation_id: str
    final_text: str = ""
    awaiting_approval: bool = False
    needs_input: bool = False
    # The paused long-running calls: {"id", "name", "args"} each.
    pending_calls: List[Dict[str, Any]] = field(default_factory=list)
    # The skill calls of the user turn so far, by result key (skill_id, skill_id#2...).
    tool_results: Dict[str, Any] = field(default_factory=dict)
    tool_inputs: Dict[str, Any] = field(default_factory=dict)

    @property
    def pending_call_ids(self) -> List[str]:
        return [str(call["id"]) for call in self.pending_calls]


async def run_turn(
    agent: PrometheusAgent,
    context: RequestContext,
    event_queue: EventQueue,
    *,
    catalog: Mapping[str, ToolSpec],
    message: str | types.Content | None,
    conversation_id: str = "",
    conversation_context: Optional[Mapping[str, Any]] = None,
    user_id: str = "local",
    invocation_id: Optional[str] = None,
    test: bool = False,
    model: Optional[BaseLlm] = None,
    extra_state: Optional[Mapping[str, Any]] = None,
) -> TurnOutcome:
    """Run (or resume) the client agent for one chat turn.

    A ``str`` message starts a new invocation; a ``types.Content`` of function
    responses (an approval or form answers) with the paused ``invocation_id``
    resumes it, and ``None`` resumes it where it stopped. In test mode the
    runner uses in-memory services and ``model`` (a stub) also summarizes.
    *extra_state* is merged into the session state for the run's tools; its
    ``temp:`` keys last for this run only and are never stored.
    The outcome carries the skill calls the turn has made so far.
    """
    llm = None
    if model is None:
        # Closed with the runner when the turn ends (proxy mode holds an httpx client).
        llm = agent.llm_client(context)
        model = prometheus_model("medium", llm)
    root = adk_tools.build_client_agent(catalog, model)
    runner: Runner = build_runner(
        agent,
        context,
        root,
        event_queue=event_queue,
        compaction=COMPACTION,
        test=test,
        # chat_flow sends the turn's one final JSON status; the bridge emits artifacts only.
        bridge_events=False,
        summarizer_model=model if test else None,
    )
    session_id = event_context_id(context) or context_task_id(context)
    try:
        await ensure_session(runner, user_id, session_id)
        state_delta: Dict[str, Any] = {adk_tools.CONVERSATION_ID_KEY: conversation_id, **dict(extra_state or {})}
        if conversation_context is not None:
            state_delta[adk_tools.CONTEXT_KEY] = dict(conversation_context)
        if isinstance(message, str):
            # A new user turn starts its tool records empty; a resume keeps adding to them.
            state_delta[adk_tools.TOOL_RESULTS_KEY] = {}
            state_delta[adk_tools.TOOL_INPUTS_KEY] = {}
        new_message = types.Content(role="user", parts=[types.Part(text=message)]) if isinstance(message, str) else message
        invocation_id = invocation_id or new_invocation_context_id()

        outcome = TurnOutcome(session_id=session_id, invocation_id=invocation_id)
        calls: Dict[str, Dict[str, Any]] = {}
        pending: List[str] = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            invocation_id=invocation_id,
            new_message=new_message,
            state_delta=state_delta,
        ):
            if event.author == "user" or event.partial:
                continue
            for call in event.get_function_calls():
                if call.id:
                    calls[call.id] = {"id": call.id, "name": call.name, "args": dict(call.args or {})}
            pending.extend(call_id for call_id in event.long_running_tool_ids or () if call_id not in pending)
            text = event_text(event)
            if text:
                outcome.final_text = text
        outcome.pending_calls = [calls[call_id] for call_id in pending if call_id in calls]
        outcome.awaiting_approval = any(
            call["name"] == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME for call in outcome.pending_calls
        )
        outcome.needs_input = any(
            call["name"] != REQUEST_CONFIRMATION_FUNCTION_CALL_NAME for call in outcome.pending_calls
        )
        finished = await runner.session_service.get_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )
        if finished is not None:
            outcome.tool_results = dict(finished.state.get(adk_tools.TOOL_RESULTS_KEY) or {})
            outcome.tool_inputs = dict(finished.state.get(adk_tools.TOOL_INPUTS_KEY) or {})
        if not outcome.pending_calls:
            await commit_run_to_memory(runner, user_id, session_id)
    finally:
        await runner.close()
        if llm is not None:
            await llm.aclose()
    return outcome
