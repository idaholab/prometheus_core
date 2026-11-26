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

"""The orchestrator's tool catalog: one ``ToolSpec`` per advertised tool.

Shared by every orchestration level. It turns an agent skill (an
``AgentCapability``) into the JSON-Schema tool definition the LLM sees and
keeps the metadata the loop needs to validate, pause and dispatch the call.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Mapping, Tuple

from prometheus_api.llm_client import ToolDefinition

from .artifact_handling import extract_artifact_field_paths
from .param_schema import extract_required_param_paths, flatten_schema_properties

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
        # Both helpers walk the schema the same way, so every artifact path has a
        # property; the guard only protects against a future divergence.
        if prop is None:  # pragma: no cover
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


def _skill_spec(name: str, capability: Any) -> ToolSpec:
    """The tool for one skill; ``capability`` is an ``AgentCapability``."""
    input_schema = capability.input_schema if isinstance(capability.input_schema, dict) else {}
    # Users never type artifact ids: a missing artifact reference is the model's to fill.
    artifact_paths = extract_artifact_field_paths(input_schema)
    user_required = [
        path
        for path in extract_required_param_paths(input_schema)
        if path.split(".", 1)[0] not in ORCHESTRATOR_PARAMS and path not in artifact_paths
    ]
    all_required = [
        path
        for path in extract_required_param_paths(input_schema, include_internal=True)
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
