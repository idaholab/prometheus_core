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

"""Tests for the workflow templates the client-agent serves at GET /workflows/templates.

`workflow_library.graph.workflow_template` shapes each compiled workflow as the backend
`WorkflowDetail` wire dict; the route serves them under the agent's bearer middleware.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Iterator, List

import httpx
import pytest
import yaml

# Like test_stage_upload_endpoint.py: evict a bare prometheus_api.agent stub that another test
# module may have installed, so build_app() and its real BearerTokenMiddleware are used.
if not getattr(sys.modules.get("prometheus_api.agent"), "__file__", None):
    for name in list(sys.modules):
        if name == "prometheus_api.agent" or name.startswith("prometheus_api.agent."):
            del sys.modules[name]

from capability_cache import AgentCapability  # noqa: E402
from orchestrator import runtime, service  # noqa: E402
from orchestrator.service import OrchestratorAgent  # noqa: E402
from workflow_library.compiler import compile_workflow  # noqa: E402
from workflow_library.graph import workflow_template  # noqa: E402
from workflow_library.registry import WorkflowRegistry  # noqa: E402

CLIENT_AGENT_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = CLIENT_AGENT_DIR.parent
COMPREHENSIVE_YAML = CLIENT_AGENT_DIR / "workflows" / "comprehensive_material_analysis.yaml"
PATRIOTIC_YAML = AGENTS_DIR / "debug-agents" / "artifact-debug-agent" / "workflows" / "patriotic_usa_png.yaml"
COMPREHENSIVE_SKILLS = [
    "get_material_data",
    "analyze_radiation_damage",
    "analyze_corrosion",
    "analyze_thermal",
    "synthesize_material_analysis",
]

BASE_URL = "http://testserver"
AGENT_SECRET = "test-secret"

TEMPLATE_KEYS = {
    "workflow_id",
    "name",
    "summary",
    "category",
    "version",
    "source",
    "owner",
    "complexity",
    "estimated_runtime_seconds",
    "speedup",
    "requires_approval",
    "agent_count",
    "checkpoint_count",
    "inputs",
    "graph",
}
GRAPH_KEYS = {"workflow_id", "mode", "nodes", "edges"}
NODE_KEYS = {"node_id", "kind", "skill_id", "label", "agent_name", "is_final", "inputs"}
NODE_INPUT_KEYS = {"port", "source", "optional"}
EDGE_KEYS = {"edge_id", "from_node", "to_node", "kind", "port"}


def _capability(skill_id: str, agent_id: str | None = None) -> AgentCapability:
    agent_id = agent_id or f"{skill_id}-agent"
    return AgentCapability(
        agent_id=agent_id,
        agent_name=f"{agent_id} name",
        agent_url=f"http://{agent_id}:8000",
        skill_id=skill_id,
        skill_name=f"{skill_id} skill",
        description=f"Skill {skill_id}",
        input_schema={"type": "object", "properties": {}, "required": []},
    )


def _capabilities_by_skill(skill_ids: List[str]) -> Dict[str, AgentCapability]:
    return {skill_id: _capability(skill_id) for skill_id in skill_ids}


def _compile_file(path: Path, capabilities_by_skill: Dict[str, AgentCapability]) -> Any:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return compile_workflow(raw=raw, source_path=path, capabilities_by_skill=capabilities_by_skill, strict=True)


def _all_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_keys(item)


def _edge_tuples(template: Dict[str, Any]) -> set[tuple[str, str, str, str | None]]:
    return {(e["from_node"], e["to_node"], e["kind"], e["port"]) for e in template["graph"]["edges"]}


def _inputs_with_source(template: Dict[str, Any], source: str) -> List[Dict[str, Any]]:
    return [item for node in template["graph"]["nodes"] for item in node["inputs"] if item["source"] == source]


def test_comprehensive_material_analysis_template_shape() -> None:
    capabilities = _capabilities_by_skill(COMPREHENSIVE_SKILLS)
    template = workflow_template(_compile_file(COMPREHENSIVE_YAML, capabilities), capabilities)

    assert set(template) == TEMPLATE_KEYS
    assert set(template["graph"]) == GRAPH_KEYS
    assert "graph_id" not in set(_all_keys(template))

    assert template["workflow_id"] == "comprehensive_material_analysis"
    assert template["source"] == "local"
    assert template["requires_approval"] is True
    assert template["complexity"] is None
    assert template["speedup"] is None
    assert template["agent_count"] == 5
    assert template["checkpoint_count"] == 0
    assert template["graph"]["workflow_id"] == "comprehensive_material_analysis"
    assert template["graph"]["mode"] == "dag"

    nodes = template["graph"]["nodes"]
    assert [node["node_id"] for node in nodes] == [
        "retrieve_material",
        "analyze_radiation",
        "analyze_corrosion",
        "analyze_thermal",
        "synthesize_report",
    ]
    for node in nodes:
        assert set(node) == NODE_KEYS
        for item in node["inputs"]:
            assert set(item) == NODE_INPUT_KEYS

    edges = template["graph"]["edges"]
    for edge in edges:
        assert set(edge) == EDGE_KEYS
    assert _edge_tuples(template) == {
        ("retrieve_material", "analyze_radiation", "order", None),
        ("retrieve_material", "analyze_corrosion", "order", None),
        ("retrieve_material", "analyze_thermal", "order", None),
        ("retrieve_material", "synthesize_report", "data", "tool_results.material_data"),
        ("analyze_radiation", "synthesize_report", "data", "tool_results.radiation"),
        ("analyze_corrosion", "synthesize_report", "data", "tool_results.corrosion"),
        ("analyze_thermal", "synthesize_report", "data", "tool_results.thermal"),
    }
    assert len(edges) == 7
    assert sum(1 for edge in edges if edge["kind"] == "order") == 3
    assert sum(1 for edge in edges if edge["kind"] == "data") == 4
    edge_ids = [edge["edge_id"] for edge in edges]
    assert len(set(edge_ids)) == len(edge_ids)
    assert set(edge_ids) == {f"comprehensive_material_analysis-e{n}" for n in range(1, 8)}

    ports = [edge["port"] for edge in edges] + [item["port"] for node in nodes for item in node["inputs"]]
    assert "after" not in ports

    # temperature_c is under inputs.required, so the YAML's `optional: true` does not make it optional.
    temperature_inputs = _inputs_with_source(template, "input.context.temperature_c")
    assert len(temperature_inputs) == 3
    assert all(item["optional"] is False for item in temperature_inputs)
    pressure_inputs = _inputs_with_source(template, "input.context.pressure_mpa")
    assert len(pressure_inputs) == 3
    assert all(item["optional"] is True for item in pressure_inputs)


def test_patriotic_usa_png_template_has_one_order_edge_and_context_source() -> None:
    capabilities = _capabilities_by_skill(["create_svg_artifact", "convert_svg_to_png"])
    template = workflow_template(_compile_file(PATRIOTIC_YAML, capabilities), capabilities)

    assert template["graph"]["mode"] == "sequential"
    nodes = {node["node_id"]: node for node in template["graph"]["nodes"]}
    assert list(nodes) == ["create_usa_svg", "convert_to_png"]
    assert template["graph"]["edges"] == [
        {
            "edge_id": "artifact_debug.patriotic_usa_png-e1",
            "from_node": "create_usa_svg",
            "to_node": "convert_to_png",
            "kind": "order",
            "port": None,
        }
    ]

    convert_inputs = {item["port"]: item for item in nodes["convert_to_png"]["inputs"]}
    assert convert_inputs["artifact_id"]["source"] == "context.usa_svg_artifact_id"
    assert convert_inputs["name"]["source"] is None
    create_inputs = {item["port"]: item for item in nodes["create_usa_svg"]["inputs"]}
    assert create_inputs["word"]["source"] is None
    assert create_inputs["width"]["source"] is None


def test_agent_card_workflow_template_has_agent_card_source() -> None:
    capabilities = [_capability("analyze_thermal")]
    agent_cards = [
        {
            "agent_id": "thermal-agent",
            "direct_url": "http://thermal-agent:8000",
            "agent_card": {
                "name": "Thermal Agent",
                "workflows": [
                    {
                        "id": "thermal_agent.quick_check",
                        "name": "Quick Thermal Check",
                        "version": "1.0.0",
                        "description": "Run a quick thermal analysis.",
                        "execution": {"mode": "sequential", "on_error": "fail_fast"},
                        "steps": [{"id": "analyze", "skill_id": "analyze_thermal"}],
                    }
                ],
            },
        }
    ]

    with TemporaryDirectory() as tmp_dir:
        registry = WorkflowRegistry(workflows_dir=tmp_dir, strict=True)
        refresh_result = registry.refresh(capabilities, agent_cards=agent_cards)

    assert refresh_result["errors"] == []
    workflow = registry.get("thermal_agent.quick_check")
    assert workflow is not None
    template = workflow_template(workflow, {cap.skill_id: cap for cap in capabilities})
    assert template["source"] == "agent_card"
    assert template["owner"] == "thermal-agent"


def test_template_node_agent_fields_follow_discovered_capabilities() -> None:
    raw = {
        "id": "mixed_skills",
        "name": "Mixed Skills",
        "version": "1.0.0",
        "description": "test",
        "execution": {"mode": "sequential", "on_error": "fail_fast"},
        "steps": [
            {"id": "first", "skill_id": "skill_a"},
            {"id": "second", "skill_id": "skill_b", "depends_on": ["first"]},
            {"id": "third", "skill_id": "skill_unknown", "depends_on": ["second"]},
        ],
    }
    capabilities = {
        "skill_a": _capability("skill_a", agent_id="shared-agent"),
        "skill_b": _capability("skill_b", agent_id="shared-agent"),
    }
    workflow = compile_workflow(
        raw=raw, source_path=Path("mixed.yaml"), capabilities_by_skill=capabilities, strict=False
    )
    template = workflow_template(workflow, capabilities)

    nodes = {node["node_id"]: node for node in template["graph"]["nodes"]}
    assert nodes["first"]["label"] == "skill_a skill"
    assert nodes["first"]["agent_name"] == "shared-agent"
    assert nodes["second"]["agent_name"] == "shared-agent"
    assert nodes["third"]["label"] == "third"
    assert nodes["third"]["agent_name"] is None
    assert template["agent_count"] == 1


def test_ui_complexity_and_speedup_flow_to_template_and_catalog() -> None:
    workflow_yaml = """
id: fast_workflow
name: Fast Workflow
version: "1.0.0"
description: test
execution:
  mode: sequential
  on_error: fail_fast
steps:
  - id: s1
    skill_id: analyze_thermal
ui:
  complexity: moderate
  speedup: 2.5
"""
    capabilities = [_capability("analyze_thermal")]
    with TemporaryDirectory() as tmp_dir:
        (Path(tmp_dir) / "fast_workflow.yaml").write_text(workflow_yaml, encoding="utf-8")
        registry = WorkflowRegistry(workflows_dir=tmp_dir, strict=True)
        registry.refresh(capabilities)

    workflow = registry.get("fast_workflow")
    assert workflow is not None
    template = workflow_template(workflow, {cap.skill_id: cap for cap in capabilities})
    assert template["complexity"] == "moderate"
    assert template["speedup"] == 2.5

    (card,) = registry.get_catalog()
    assert card["complexity"] == "moderate"
    assert card["speedup"] == 2.5


class _FakeCapabilityCache:
    def __init__(self, capabilities: List[AgentCapability]):
        self._capabilities = capabilities

    async def get_capabilities(self) -> List[AgentCapability]:
        return self._capabilities


@pytest.fixture
def templates_app(monkeypatch, tmp_path):
    """The client-agent's real app (build_app, so configure_app and the bearer middleware),
    with a registry holding the shipped comprehensive workflow and a fake capability cache."""
    monkeypatch.setenv("AGENT_SECRET", AGENT_SECRET)
    monkeypatch.setenv("AGENT_SECRET_REQUIRED", "true")
    monkeypatch.setenv("PROMETHEUS_TASK_STORE", "memory")

    capabilities = [_capability(skill_id) for skill_id in COMPREHENSIVE_SKILLS]
    shutil.copy(COMPREHENSIVE_YAML, tmp_path / COMPREHENSIVE_YAML.name)
    registry = WorkflowRegistry(workflows_dir=str(tmp_path), strict=True)
    registry.refresh(capabilities)
    monkeypatch.setattr(service, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(service, "get_capability_cache", lambda: _FakeCapabilityCache(capabilities))

    agent = OrchestratorAgent()
    agent.agent_card_path = str(CLIENT_AGENT_DIR / "agent_card.json")
    return agent.build_app(register_on_startup=False)


async def _get_templates(app, headers: Dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        return await client.get("/workflows/templates", headers=headers or {})


@pytest.mark.asyncio
async def test_templates_route_requires_bearer(templates_app) -> None:
    resp = await _get_templates(templates_app)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_templates_route_returns_templates_with_bearer(templates_app, monkeypatch) -> None:
    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", True)
    resp = await _get_templates(templates_app, {"Authorization": f"Bearer {AGENT_SECRET}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["errors"] == []
    (template,) = body["workflows"]
    assert set(template) == TEMPLATE_KEYS
    assert template["workflow_id"] == "comprehensive_material_analysis"
    assert template["requires_approval"] is True
    assert len(template["graph"]["nodes"]) == 5
    assert len(template["graph"]["edges"]) == 7


@pytest.mark.asyncio
async def test_templates_route_reports_disabled_library(templates_app, monkeypatch) -> None:
    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", False)
    resp = await _get_templates(templates_app, {"Authorization": f"Bearer {AGENT_SECRET}"})

    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "workflows": [], "errors": []}
