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

"""Shape a compiled workflow as the backend wire `WorkflowDetail` template (pure, no I/O)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .registry import workflow_source_type
from .schema import CompiledWorkflow, WorkflowStep

if TYPE_CHECKING:
    from capability_cache import AgentCapability
else:
    AgentCapability = Any


def _flatten_params(node: Dict[str, Any], prefix: str = "") -> List[Tuple[str, Dict[str, Any]]]:
    """Return `(port, leaf)` pairs; a leaf is a dict with a `from` or `literal` key.

    Nested dicts without those keys are groups whose keys join with `.` into the port.
    A non-dict value is a bare literal, as the binder resolves it.
    """
    leaves: List[Tuple[str, Dict[str, Any]]] = []
    for key, value in node.items():
        port = f"{prefix}{key}"
        if isinstance(value, dict) and ("from" in value or "literal" in value):
            leaves.append((port, value))
        elif isinstance(value, dict):
            leaves.extend(_flatten_params(value, prefix=f"{port}."))
        else:
            leaves.append((port, {"literal": value}))
    return leaves


def _is_required_input(path: str, required: List[str]) -> bool:
    return any(path == entry or path.startswith(f"{entry}.") for entry in required)


def _step_node(
    step: WorkflowStep,
    required: List[str],
    capabilities_by_skill: Dict[str, AgentCapability],
) -> Dict[str, Any]:
    capability = capabilities_by_skill.get(step.skill_id)
    inputs: List[Dict[str, Any]] = []
    for port, leaf in _flatten_params(step.params):
        raw_source = leaf.get("from")
        source: Optional[str] = str(raw_source) if raw_source is not None else None
        if source is not None and source.startswith("input.") and _is_required_input(source[len("input.") :], required):
            optional = False
        else:
            optional = bool(leaf.get("optional", False))
        inputs.append({"port": port, "source": source, "optional": optional})
    return {
        "node_id": step.id,
        "kind": "skill",
        "skill_id": step.skill_id,
        "label": capability.skill_name if capability else step.id,
        "agent_name": capability.agent_id if capability else None,
        "is_final": step.is_final,
        "inputs": inputs,
    }


def _step_edges(step: WorkflowStep, node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the step's data edges in port order, then its order edges in `depends_on` order."""
    edges: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    referenced: set[str] = set()
    for item in node["inputs"]:
        source = item["source"]
        if source is None or not source.startswith("step."):
            continue
        from_node = source[len("step.") :].split(".", 1)[0]
        referenced.add(from_node)
        if (from_node, item["port"]) in seen:
            continue
        seen.add((from_node, item["port"]))
        edges.append({"from_node": from_node, "to_node": step.id, "kind": "data", "port": item["port"]})
    for dependency in step.depends_on:
        if dependency in referenced:
            continue
        edges.append({"from_node": dependency, "to_node": step.id, "kind": "order", "port": None})
    return edges


def workflow_template(
    workflow: CompiledWorkflow,
    capabilities_by_skill: Dict[str, AgentCapability],
) -> Dict[str, Any]:
    """Return the workflow as the backend wire `WorkflowDetail` dict, every key present.

    Edges are numbered `<workflow_id>-e<n>` from 1: steps in definition order; per step, its
    data edges (one per `step.<id>.*` source, deduplicated per from/to/port) in param-flatten
    order, then its order edges (one per `depends_on` entry no data source references) in
    `depends_on` order.
    """
    definition = workflow.definition
    ui = definition.ui
    metadata = definition.metadata
    required = list(definition.inputs.required)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for step in definition.steps:
        node = _step_node(step, required, capabilities_by_skill)
        nodes.append(node)
        for edge in _step_edges(step, node):
            edges.append({"edge_id": f"{definition.id}-e{len(edges) + 1}", **edge})

    agent_names = {node["agent_name"] for node in nodes if node["kind"] == "skill" and node["agent_name"]}
    return {
        "workflow_id": definition.id,
        "name": ui.display_name or definition.name,
        "summary": ui.summary or definition.description,
        "category": ui.category or "General",
        "version": definition.version,
        "source": workflow_source_type(workflow),
        "owner": metadata.owner or None,
        "complexity": ui.complexity,
        "estimated_runtime_seconds": metadata.estimated_duration_seconds,
        "speedup": ui.speedup,
        "requires_approval": bool(metadata.requires_approval),
        "agent_count": len(agent_names),
        "checkpoint_count": sum(1 for node in nodes if node["kind"] == "checkpoint"),
        "inputs": {"required": required, "optional": list(definition.inputs.optional)},
        "graph": {
            "workflow_id": definition.id,
            "mode": definition.execution.mode,
            "nodes": nodes,
            "edges": edges,
        },
    }
