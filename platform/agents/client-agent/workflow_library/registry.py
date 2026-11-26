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

"""Workflow registry with compile-time validation and atomic refresh."""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import yaml

from orchestration.param_schema import flatten_schema_properties, has_param_path
from .compiler import WorkflowCompileError, compile_workflow
from .schema import CompiledWorkflow

if TYPE_CHECKING:
    from capability_cache import AgentCapability
else:
    AgentCapability = Any


def _version_key(raw_version: str) -> tuple[int, tuple[Any, ...]]:
    text = str(raw_version or "").strip()
    parts = re.split(r"[.-]", text)
    parsed: List[Any] = []
    numeric = True
    for part in parts:
        if part.isdigit():
            parsed.append(int(part))
        else:
            numeric = False
            parsed.append(part)
    return (1 if numeric else 0, tuple(parsed))


def _append_unit_to_description(description: str, unit: Optional[str]) -> str:
    """Ensure UI description consistently includes unit hints when available."""
    text = str(description or "").strip()
    normalized_unit = str(unit or "").strip()
    if not normalized_unit:
        return text

    if text:
        try:
            # Detect standalone unit mentions like "MPa", "n/cm^2/s", "(C)".
            unit_pattern = rf"(?<!\w){re.escape(normalized_unit)}(?!\w)"
            if re.search(unit_pattern, text, flags=re.IGNORECASE):
                return text
            if re.search(rf"unit\s*:\s*{re.escape(normalized_unit)}", text, flags=re.IGNORECASE):
                return text
        except re.error:
            if normalized_unit.lower() in text.lower():
                return text

        return f"{text} Unit: {normalized_unit}."

    return f"Unit: {normalized_unit}."


def _safe_source_segment(value: str) -> str:
    """Return a stable virtual path segment for non-filesystem workflow sources."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    return text.strip("-") or "unknown"


def _agent_card_from_record(record: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return `(agent_id, agent_card)` from a cached card record or raw card."""
    if isinstance(record.get("agent_card"), dict):
        agent_id = str(record.get("agent_id") or record.get("agent_name") or "").strip()
        return agent_id, record["agent_card"]

    agent_id = str(record.get("agent_id") or record.get("name") or "").strip()
    return agent_id, record


@dataclass
class WorkflowSnapshot:
    """Immutable registry snapshot."""

    by_key: Dict[str, CompiledWorkflow]
    by_id: Dict[str, List[CompiledWorkflow]]
    checksum: str
    loaded_at: str
    errors: List[str]


class WorkflowRegistry:
    """Runtime registry for versioned workflow templates."""

    def __init__(self, workflows_dir: str, strict: bool = False):
        self.workflows_dir = Path(workflows_dir)
        self.strict = strict
        self._snapshot = WorkflowSnapshot(
            by_key={},
            by_id={},
            checksum="",
            loaded_at="",
            errors=[],
        )

    @property
    def snapshot(self) -> WorkflowSnapshot:
        return self._snapshot

    def list_all(self) -> List[CompiledWorkflow]:
        values = list(self._snapshot.by_key.values())
        values.sort(key=lambda item: (item.definition.id, _version_key(item.definition.version)))
        return values

    def get(self, workflow_id: str, version: Optional[str] = None) -> Optional[CompiledWorkflow]:
        candidates = self._snapshot.by_id.get(workflow_id, [])
        if not candidates:
            return None
        if version is None:
            return sorted(candidates, key=lambda wf: _version_key(wf.definition.version), reverse=True)[0]
        for item in candidates:
            if item.definition.version == version:
                return item
        return None

    def get_catalog(self) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        for workflow in self.list_all():
            ui = workflow.definition.ui
            metadata = workflow.definition.metadata
            source_type = (
                "agent_card"
                if workflow.source_path.parts and workflow.source_path.parts[0] == "agent_cards"
                else "local"
            )
            cards.append(
                {
                    "id": workflow.definition.id,
                    "version": workflow.definition.version,
                    "display_name": ui.display_name or workflow.definition.name,
                    "summary": ui.summary or workflow.definition.description,
                    "category": ui.category or "General",
                    "requires_approval": bool(metadata.requires_approval),
                    "estimated_duration_seconds": metadata.estimated_duration_seconds,
                    "owner": metadata.owner,
                    "source": source_type,
                }
            )
        cards.sort(key=lambda item: (item["category"], item["display_name"], item["id"]))
        return cards

    def build_input_form(
        self,
        workflow_id: str,
        version: Optional[str],
        capabilities_by_skill: Dict[str, AgentCapability],
        params: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        workflow = self.get(workflow_id, version=version)
        if workflow is None:
            raise KeyError(f"Workflow '{workflow_id}' not found")

        merged = dict(params or {})
        ctx = dict(context or {})
        if ctx:
            merged.setdefault("context", {})
            if isinstance(merged["context"], dict):
                for key, value in ctx.items():
                    merged["context"].setdefault(key, value)

        # Aggregate schema metadata from all referenced capabilities.
        properties: Dict[str, Dict[str, Any]] = {}
        for step in workflow.definition.steps:
            cap = capabilities_by_skill.get(step.skill_id)
            if not cap:
                continue
            properties.update(flatten_schema_properties(cap.input_schema))

        fields: List[Dict[str, Any]] = []
        for path in workflow.required_input_paths:
            if has_param_path(merged, path):
                continue

            override = workflow.definition.ui.input_overrides.get(path)
            prop = properties.get(path)
            if not prop and "." in path:
                prop = properties.get(path.split(".", 1)[1])
            prop = prop or {}

            label = (
                (override.label if override else None)
                or prop.get("title")
                or path.split(".")[-1].replace("_", " ").title()
            )
            description = (
                (override.description if override else None) or prop.get("description") or f"Provide value for {path}"
            )
            unit = (
                (override.unit if override and override.unit else None)
                or prop.get("unit")
                or prop.get("x_unit")
                or prop.get("x-unit")
            )
            description = _append_unit_to_description(description, unit)
            field_type = (override.type if override else None) or prop.get("type") or "text"
            enum = prop.get("enum") if isinstance(prop, dict) else None
            source = (
                "workflow_override"
                if override and (override.label or override.description or override.type)
                else ("agent_card" if prop else "fallback")
            )
            fields.append(
                {
                    "field": path,
                    "label": label,
                    "description": description,
                    "type": field_type,
                    "required": True,
                    "options": (override.options if override and override.options else enum),
                    "unit": unit,
                    "source": source,
                }
            )

        return {
            "workflow_id": workflow.definition.id,
            "workflow_version": workflow.definition.version,
            "fields": fields,
        }

    def refresh(
        self,
        capabilities: List[AgentCapability],
        *,
        agent_cards: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        capabilities_by_skill = {cap.skill_id: cap for cap in capabilities}

        files = sorted(self.workflows_dir.glob("*.yaml")) + sorted(self.workflows_dir.glob("*.yml"))
        by_key: Dict[str, CompiledWorkflow] = {}
        by_id: Dict[str, List[CompiledWorkflow]] = {}
        errors: List[str] = []

        def add_compiled(compiled: CompiledWorkflow, source_label: str) -> None:
            key = compiled.key
            if key in by_key:
                errors.append(f"{source_label}: duplicate workflow key '{key}'")
                return
            by_key[key] = compiled
            by_id.setdefault(compiled.definition.id, []).append(compiled)

        checksum_parts: List[str] = []
        for path in files:
            raw_text = path.read_text(encoding="utf-8")
            stat = path.stat()
            checksum_parts.append(f"{path}:{stat.st_mtime_ns}:{hashlib.sha256(raw_text.encode('utf-8')).hexdigest()}")
            try:
                data = yaml.safe_load(raw_text) or {}
                compiled = compile_workflow(
                    raw=data,
                    source_path=path,
                    capabilities_by_skill=capabilities_by_skill,
                    strict=self.strict,
                )
            except (WorkflowCompileError, Exception) as exc:
                errors.append(f"{path.name}: {exc}")
                continue

            add_compiled(compiled, path.name)

        for record in agent_cards or []:
            if not isinstance(record, dict):
                errors.append("agent_card: expected agent-card record object")
                continue

            agent_id, card = _agent_card_from_record(record)
            if not isinstance(card, dict):
                errors.append(f"agent_card:{agent_id or 'unknown'}: expected agent card object")
                continue

            workflows = card.get("workflows", [])
            source_agent = agent_id or str(card.get("name") or "unknown")
            source_agent_url = str(record.get("direct_url") or card.get("url") or "").strip()
            source_prefix = f"agent_card:{source_agent}"
            if workflows in (None, ""):
                continue
            if not isinstance(workflows, list):
                errors.append(f"{source_prefix}: workflows must be a list")
                continue

            for index, raw_workflow in enumerate(workflows):
                source_label = f"{source_prefix}:workflows[{index}]"
                if not isinstance(raw_workflow, dict):
                    errors.append(f"{source_label}: workflow definition must be an object")
                    continue

                data = deepcopy(raw_workflow)
                metadata = data.setdefault("metadata", {})
                if isinstance(metadata, dict):
                    metadata.setdefault("owner", source_agent)
                    metadata.setdefault("source_agent_id", source_agent)
                    if source_agent_url:
                        metadata.setdefault("source_agent_url", source_agent_url)

                serialized = json.dumps(data, sort_keys=True, default=str)
                checksum_parts.append(f"{source_label}:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}")

                try:
                    compiled = compile_workflow(
                        raw=data,
                        source_path=(
                            Path("agent_cards") / _safe_source_segment(source_agent) / f"workflow-{index}.json"
                        ),
                        capabilities_by_skill=capabilities_by_skill,
                        strict=self.strict,
                    )
                except (WorkflowCompileError, Exception) as exc:
                    errors.append(f"{source_label}: {exc}")
                    continue

                add_compiled(compiled, source_label)

        for workflow_id, items in by_id.items():
            by_id[workflow_id] = sorted(items, key=lambda wf: _version_key(wf.definition.version), reverse=True)

        checksum = hashlib.sha256("\n".join(sorted(checksum_parts)).encode("utf-8")).hexdigest()
        next_snapshot = WorkflowSnapshot(
            by_key=by_key,
            by_id=by_id,
            checksum=checksum,
            loaded_at=datetime.now(timezone.utc).isoformat(),
            errors=errors,
        )
        self._snapshot = next_snapshot

        return {
            "count": len(by_key),
            "errors": errors,
            "checksum": checksum,
        }


_workflow_registry: Optional[WorkflowRegistry] = None


def get_workflow_registry() -> WorkflowRegistry:
    global _workflow_registry
    if _workflow_registry is None:
        workflows_dir = os.getenv("WORKFLOW_LIBRARY_DIR", "/app/workflows")
        strict = os.getenv("WORKFLOW_LIBRARY_STRICT", "false").lower() in {"1", "true", "yes"}
        _workflow_registry = WorkflowRegistry(workflows_dir=workflows_dir, strict=strict)
    return _workflow_registry
