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

"""Unit tests for workflow library compile/execute behavior."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict

import pytest

from workflow_library.compiler import WorkflowCompileError, compile_workflow
from workflow_library.executor import execute_workflow
from workflow_library.naming import find_workflow_by_command, workflow_tool_name
from workflow_library.registry import WorkflowRegistry


@dataclass
class _Capability:
    """Minimal capability shape required by workflow compiler/registry."""

    agent_id: str
    agent_name: str
    agent_url: str
    skill_id: str
    skill_name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


def _capability(skill_id: str, input_schema: Dict[str, Any] | None = None) -> _Capability:
    return _Capability(
        agent_id=f"{skill_id}-agent",
        agent_name=f"{skill_id} agent",
        agent_url=f"http://{skill_id}:8000",
        skill_id=skill_id,
        skill_name=skill_id,
        description=f"Skill {skill_id}",
        input_schema=input_schema or {"type": "object", "properties": {}, "required": []},
    )


def _compile(raw: Dict[str, Any]) -> Any:
    capabilities = {step["skill_id"]: _capability(step["skill_id"]) for step in raw.get("steps", [])}
    return compile_workflow(raw=raw, source_path=Path("test.yaml"), capabilities_by_skill=capabilities, strict=True)


def test_compile_detects_dependency_cycles() -> None:
    raw = {
        "id": "cycle_workflow",
        "name": "Cycle",
        "version": "1.0.0",
        "description": "test",
        "matching": {"priority": 1, "patterns": ["cycle"]},
        "execution": {"mode": "dag", "on_error": "fail_fast"},
        "steps": [
            {"id": "a", "skill_id": "s_a", "depends_on": ["b"]},
            {"id": "b", "skill_id": "s_b", "depends_on": ["a"]},
        ],
    }
    with pytest.raises(WorkflowCompileError):
        _compile(raw)


def test_compile_does_not_promote_optional_input_bindings_to_required() -> None:
    workflow = _compile(
        {
            "id": "optional_inputs",
            "name": "Optional Inputs",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["optional"]},
            "inputs": {
                "required": ["material_id"],
                "optional": ["context.temperature_c"],
            },
            "execution": {"mode": "sequential", "on_error": "fail_fast"},
            "steps": [
                {
                    "id": "analyze",
                    "skill_id": "analyze_thermal",
                    "params": {
                        "material_id": {"from": "input.material_id"},
                        "context": {
                            "temperature_c": {
                                "from": "input.context.temperature_c",
                                "optional": True,
                            },
                            "pressure_mpa": {
                                "from": "input.context.pressure_mpa",
                                "optional": True,
                            },
                        },
                    },
                }
            ],
        }
    )

    assert workflow.required_input_paths == ["material_id"]


def test_compile_infers_required_inputs_from_step_skill_requirements() -> None:
    input_schema = {
        "type": "object",
        "properties": {
            "material_id": {"type": "string"},
            "context": {
                "type": "object",
                "properties": {
                    "temperature_c": {"type": "number"},
                    "pressure_mpa": {"type": "number"},
                    "operating_hours": {"type": "integer"},
                },
                "required": ["temperature_c", "pressure_mpa", "operating_hours"],
            },
        },
        "required": ["material_id", "context"],
    }

    capabilities = {
        "analyze_thermal": _capability("analyze_thermal", input_schema=input_schema),
        "get_material_data": _capability("get_material_data"),
    }

    workflow = compile_workflow(
        raw={
            "id": "schema_required_inputs",
            "name": "Schema Required Inputs",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["schema"]},
            "inputs": {"required": ["material_id"], "optional": ["context.temperature_c"]},
            "execution": {"mode": "dag", "on_error": "fail_fast"},
            "steps": [
                {
                    "id": "retrieve",
                    "skill_id": "get_material_data",
                    "params": {"material_id": {"from": "input.material_id"}},
                    "outputs": [{"to_context": "material_data", "from": "result"}],
                },
                {
                    "id": "thermal",
                    "skill_id": "analyze_thermal",
                    "depends_on": ["retrieve"],
                    "params": {
                        "material_id": {"from": "input.material_id"},
                        "context": {
                            "temperature_c": {"from": "input.context.temperature_c", "optional": True},
                            "pressure_mpa": {"from": "input.context.pressure_mpa", "optional": True},
                            "operating_hours": {"from": "input.context.operating_hours", "optional": True},
                        },
                    },
                },
            ],
        },
        source_path=Path("test.yaml"),
        capabilities_by_skill=capabilities,
        strict=True,
    )

    assert workflow.required_input_paths == [
        "context.operating_hours",
        "context.pressure_mpa",
        "context.temperature_c",
        "material_id",
    ]


def test_registry_prefers_highest_semver_default_version() -> None:
    workflow_v12 = """
id: versioned_workflow
name: Versioned Workflow
version: "1.2.0"
description: test
matching:
  patterns: ["versioned"]
execution:
  mode: sequential
  on_error: fail_fast
steps:
  - id: s1
    skill_id: analyze_thermal
"""
    workflow_v110 = workflow_v12.replace('version: "1.2.0"', 'version: "1.10.0"')

    with TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "wf-1.2.0.yaml").write_text(workflow_v12, encoding="utf-8")
        (base / "wf-1.10.0.yaml").write_text(workflow_v110, encoding="utf-8")

        registry = WorkflowRegistry(workflows_dir=str(base), strict=True)
        registry.refresh([_capability("analyze_thermal")])

        selected = registry.get("versioned_workflow")

    assert selected is not None
    assert selected.definition.version == "1.10.0"


def test_registry_loads_agent_card_workflows() -> None:
    capabilities = [_capability("analyze_thermal")]
    agent_cards = [
        {
            "agent_id": "thermal-agent",
            "agent_name": "Thermal Agent",
            "direct_url": "http://thermal-agent:8000",
            "agent_card": {
                "name": "Thermal Agent",
                "workflows": [
                    {
                        "id": "thermal_agent.quick_check",
                        "name": "Quick Thermal Check",
                        "version": "1.0.0",
                        "description": "Run a quick thermal analysis.",
                        "matching": {"patterns": ["quick thermal check"]},
                        "execution": {"mode": "sequential", "on_error": "fail_fast"},
                        "steps": [{"id": "analyze", "skill_id": "analyze_thermal"}],
                        "ui": {
                            "category": "Thermal",
                            "display_name": "Quick Thermal Check",
                            "summary": "Quick thermal analysis",
                        },
                    }
                ],
            },
        }
    ]

    with TemporaryDirectory() as tmp_dir:
        registry = WorkflowRegistry(workflows_dir=tmp_dir, strict=True)
        refresh_result = registry.refresh(capabilities, agent_cards=agent_cards)

    assert refresh_result["count"] == 1
    assert refresh_result["errors"] == []

    workflow = registry.get("thermal_agent.quick_check", version="1.0.0")
    assert workflow is not None
    assert workflow.definition.metadata.owner == "thermal-agent"
    assert workflow.definition.metadata.source_agent_id == "thermal-agent"
    assert workflow.definition.metadata.source_agent_url == "http://thermal-agent:8000"

    catalog = registry.get_catalog()
    assert catalog == [
        {
            "id": "thermal_agent.quick_check",
            "version": "1.0.0",
            "display_name": "Quick Thermal Check",
            "summary": "Quick thermal analysis",
            "category": "Thermal",
            "complexity": None,
            "speedup": None,
            "requires_approval": False,
            "estimated_duration_seconds": None,
            "owner": "thermal-agent",
            "source": "agent_card",
        }
    ]


def test_workflow_command_aliases_resolve_short_names() -> None:
    workflow = _compile(
        {
            "id": "artifact_debug.patriotic_usa_png",
            "name": "Patriotic USA PNG",
            "version": "1.0.0",
            "description": "test",
            "execution": {"mode": "sequential", "on_error": "fail_fast"},
            "steps": [{"id": "s1", "skill_id": "create_svg_artifact"}],
        }
    )

    assert workflow_tool_name(workflow.definition.id) == "workflow_artifact_debug_patriotic_usa_png"
    assert find_workflow_by_command("patriotic_usa_png", [workflow]) is workflow
    assert find_workflow_by_command("artifact_debug_patriotic_usa_png", [workflow]) is workflow
    assert find_workflow_by_command("artifact_debug.patriotic_usa_png", [workflow]) is workflow


def test_registry_keeps_local_workflow_on_agent_card_duplicate_key() -> None:
    workflow_yaml = """
id: duplicate_workflow
name: Local Duplicate Workflow
version: "1.0.0"
description: local
matching:
  patterns: ["duplicate"]
execution:
  mode: sequential
  on_error: fail_fast
steps:
  - id: analyze
    skill_id: analyze_thermal
"""
    agent_cards = [
        {
            "agent_id": "remote-agent",
            "agent_card": {
                "name": "Remote Agent",
                "workflows": [
                    {
                        "id": "duplicate_workflow",
                        "name": "Remote Duplicate Workflow",
                        "version": "1.0.0",
                        "description": "remote",
                        "steps": [{"id": "analyze", "skill_id": "analyze_thermal"}],
                    }
                ],
            },
        }
    ]

    with TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "duplicate_workflow.yaml"
        path.write_text(workflow_yaml, encoding="utf-8")

        registry = WorkflowRegistry(workflows_dir=tmp_dir, strict=True)
        refresh_result = registry.refresh([_capability("analyze_thermal")], agent_cards=agent_cards)

    assert refresh_result["count"] == 1
    assert any("duplicate workflow key 'duplicate_workflow:1.0.0'" in err for err in refresh_result["errors"])

    selected = registry.get("duplicate_workflow", version="1.0.0")
    assert selected is not None
    assert selected.definition.name == "Local Duplicate Workflow"
    assert registry.get_catalog()[0]["source"] == "local"


def test_registry_input_form_uses_overrides_then_agent_metadata() -> None:
    workflow_yaml = """
id: workflow_form_test
name: Workflow Form Test
version: "1.0.0"
description: test
matching:
  patterns: ["test"]
inputs:
  required:
    - context.temperature_c
    - context.pressure_mpa
execution:
  mode: sequential
  on_error: fail_fast
steps:
  - id: analyze
    skill_id: analyze_thermal
ui:
  input_overrides:
    context.temperature_c:
      label: Coolant temperature
      description: Operating coolant temperature in Celsius.
      type: number
      unit: C
"""
    input_schema = {
        "type": "object",
        "properties": {
            "context": {
                "type": "object",
                "properties": {
                    "temperature_c": {
                        "type": "number",
                        "title": "Temperature",
                        "description": "Temperature in Celsius",
                    },
                    "pressure_mpa": {
                        "type": "number",
                        "title": "System pressure",
                        "description": "Primary pressure in MPa",
                    },
                },
                "required": ["temperature_c", "pressure_mpa"],
            }
        },
        "required": ["context"],
    }
    capabilities = [_capability("analyze_thermal", input_schema=input_schema)]

    with TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "workflow_form_test.yaml"
        path.write_text(workflow_yaml, encoding="utf-8")

        registry = WorkflowRegistry(workflows_dir=tmp_dir, strict=True)
        refresh_result = registry.refresh(capabilities)
        assert refresh_result["count"] == 1
        assert refresh_result["errors"] == []

        form = registry.build_input_form(
            workflow_id="workflow_form_test",
            version="1.0.0",
            capabilities_by_skill={cap.skill_id: cap for cap in capabilities},
            params={},
            context={},
        )

    fields = {field["field"]: field for field in form["fields"]}
    assert fields["context.temperature_c"]["label"] == "Coolant temperature"
    assert fields["context.temperature_c"]["source"] == "workflow_override"
    assert fields["context.pressure_mpa"]["label"] == "System pressure"
    assert fields["context.pressure_mpa"]["description"] == "Primary pressure in MPa"
    assert fields["context.pressure_mpa"]["source"] == "agent_card"


def test_registry_input_form_descriptions_include_units() -> None:
    workflow_yaml = """
id: workflow_unit_desc_test
name: Workflow Unit Description Test
version: "1.0.0"
description: test
matching:
  patterns: ["unit test"]
inputs:
  required:
    - context.temperature_c
    - context.pressure_mpa
execution:
  mode: sequential
  on_error: fail_fast
steps:
  - id: analyze
    skill_id: analyze_thermal
ui:
  input_overrides:
    context.temperature_c:
      label: Coolant temperature
      description: Operating coolant temperature.
      type: number
      unit: C
"""
    input_schema = {
        "type": "object",
        "properties": {
            "context": {
                "type": "object",
                "properties": {
                    "temperature_c": {
                        "type": "number",
                        "title": "Temperature",
                        "description": "Temperature",
                    },
                    "pressure_mpa": {
                        "type": "number",
                        "title": "System pressure",
                        "description": "Primary pressure",
                        "unit": "MPa",
                    },
                },
                "required": ["temperature_c", "pressure_mpa"],
            }
        },
        "required": ["context"],
    }
    capabilities = [_capability("analyze_thermal", input_schema=input_schema)]

    with TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "workflow_unit_desc_test.yaml"
        path.write_text(workflow_yaml, encoding="utf-8")

        registry = WorkflowRegistry(workflows_dir=tmp_dir, strict=True)
        refresh_result = registry.refresh(capabilities)
        assert refresh_result["count"] == 1
        assert refresh_result["errors"] == []

        form = registry.build_input_form(
            workflow_id="workflow_unit_desc_test",
            version="1.0.0",
            capabilities_by_skill={cap.skill_id: cap for cap in capabilities},
            params={},
            context={},
        )

    fields = {field["field"]: field for field in form["fields"]}
    assert fields["context.temperature_c"]["description"].endswith("Unit: C.")
    assert fields["context.pressure_mpa"]["description"].endswith("Unit: MPa.")


def test_executor_error_policy_fail_fast_vs_continue_with_partial() -> None:
    async def invoke(skill_id: str, params: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        if skill_id == "fail_skill":
            return {"error": "boom"}
        return {"result": {"ok": skill_id, "conversation_id": conversation_id, "params": params}}

    base_steps = [
        {"id": "first", "skill_id": "fail_skill"},
        {"id": "second", "skill_id": "ok_skill"},
        {"id": "third", "skill_id": "ok_skill_2", "depends_on": ["second"]},
    ]

    fail_fast_workflow = _compile(
        {
            "id": "fail_fast",
            "name": "Fail Fast",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["x"]},
            "execution": {"mode": "sequential", "on_error": "fail_fast"},
            "steps": base_steps,
        }
    )
    continue_workflow = _compile(
        {
            "id": "continue_partial",
            "name": "Continue Partial",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["x"]},
            "execution": {"mode": "sequential", "on_error": "continue_with_partial"},
            "steps": base_steps,
        }
    )

    fail_fast_result = asyncio.run(
        execute_workflow(
            workflow=fail_fast_workflow,
            input_params={},
            context={},
            invoke_skill=invoke,
            conversation_id="conv-1",
        )
    )
    continue_result = asyncio.run(
        execute_workflow(
            workflow=continue_workflow,
            input_params={},
            context={},
            invoke_skill=invoke,
            conversation_id="conv-2",
        )
    )

    assert fail_fast_result["step_statuses"]["first"] == "failed"
    assert fail_fast_result["step_statuses"]["second"] == "blocked"
    assert fail_fast_result["step_statuses"]["third"] == "blocked"

    assert continue_result["step_statuses"]["first"] == "failed"
    assert continue_result["step_statuses"]["second"] == "succeeded"
    assert continue_result["step_statuses"]["third"] == "succeeded"


def test_executor_converts_step_exception_to_failed_status() -> None:
    """A step coroutine raising must not abort concurrently running siblings."""

    async def invoke(skill_id: str, params: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        if skill_id == "raise_skill":
            raise RuntimeError("kaboom")
        return {"result": {"ok": skill_id}}

    workflow = _compile(
        {
            "id": "parallel_exception",
            "name": "Parallel Exception",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["x"]},
            "execution": {"mode": "parallel", "max_concurrency": 2, "on_error": "continue_with_partial"},
            "steps": [
                {"id": "bad", "skill_id": "raise_skill"},
                {"id": "good", "skill_id": "ok_skill"},
            ],
        }
    )

    result = asyncio.run(
        execute_workflow(
            workflow=workflow,
            input_params={},
            context={},
            invoke_skill=invoke,
            conversation_id="conv-1",
        )
    )

    assert result["step_statuses"]["bad"] == "failed"
    assert result["step_statuses"]["good"] == "succeeded"
    assert any("kaboom" in err["error"] for err in result["errors"])


def test_executor_collects_all_parallel_input_required_steps() -> None:
    async def invoke(skill_id: str, params: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        return {
            "input_required": {
                "missing_inputs": [{"name": f"param_for_{skill_id}", "type": "string"}],
            },
            "_a2a_context_id": f"context-{skill_id}",
            "_a2a_task_id": f"task-{skill_id}",
            "_task_graph_root_id": "root-1",
            "_task_graph_node_id": f"node-{skill_id}",
        }

    workflow = _compile(
        {
            "id": "parallel_ir",
            "name": "Parallel Input Required",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["x"]},
            "execution": {"mode": "parallel", "max_concurrency": 2, "on_error": "continue_with_partial"},
            "steps": [
                {"id": "first", "skill_id": "skill_a"},
                {"id": "second", "skill_id": "skill_b"},
            ],
        }
    )

    result = asyncio.run(
        execute_workflow(
            workflow=workflow,
            input_params={},
            context={},
            invoke_skill=invoke,
            conversation_id="conv-1",
        )
    )

    assert len(result["input_required_steps"]) == 2
    assert {entry["step_id"] for entry in result["input_required_steps"]} == {"first", "second"}
    assert {
        (entry["_task_graph_root_id"], entry["_task_graph_node_id"]) for entry in result["input_required_steps"]
    } == {
        ("root-1", "node-skill_a"),
        ("root-1", "node-skill_b"),
    }


def test_executor_stops_sequential_workflow_on_input_required() -> None:
    invoked: list[str] = []

    async def invoke(skill_id: str, params: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        invoked.append(skill_id)
        if skill_id == "author_equipment_geometry":
            return {
                "input_required": {
                    "missing_inputs": [{"name": "input_data", "type": "string"}],
                    "hint": "rod_diameter is required.",
                }
            }
        raise AssertionError("Dependent mesh step must wait for the requested input.")

    workflow = _compile(
        {
            "id": "bim_geometry",
            "name": "BIM Geometry",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["geometry"]},
            "execution": {"mode": "sequential", "on_error": "fail_fast"},
            "steps": [
                {
                    "id": "author",
                    "skill_id": "author_equipment_geometry",
                },
                {
                    "id": "mesh",
                    "skill_id": "mesh_geometry",
                    "depends_on": ["author"],
                },
            ],
        }
    )

    result = asyncio.run(
        execute_workflow(
            workflow=workflow,
            input_params={},
            context={},
            invoke_skill=invoke,
            conversation_id="conv-1",
        )
    )

    assert invoked == ["author_equipment_geometry"]
    assert result["step_statuses"] == {
        "author": "input_required",
        "mesh": "blocked",
    }
    assert result["input_required_steps"][0]["skill_id"] == "author_equipment_geometry"


def test_executor_continues_from_completed_steps() -> None:
    invoked: list[tuple[str, Dict[str, Any]]] = []

    async def invoke(skill_id: str, params: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        invoked.append((skill_id, params))
        return {"result": {"ok": skill_id}}

    workflow = _compile(
        {
            "id": "continue_run",
            "name": "Continue Run",
            "version": "1.0.0",
            "description": "test",
            "matching": {"patterns": ["x"]},
            "execution": {"mode": "dag", "on_error": "continue_with_partial"},
            "steps": [
                {"id": "author", "skill_id": "author_skill", "outputs": [{"from": "result", "to_context": "authored"}]},
                {"id": "broken", "skill_id": "broken_skill"},
                {
                    "id": "mesh",
                    "skill_id": "mesh_skill",
                    "depends_on": ["author"],
                    "params": {"shape": {"from": "context.authored.shape"}},
                },
                {"id": "report", "skill_id": "report_skill", "depends_on": ["broken"]},
            ],
        }
    )

    result = asyncio.run(
        execute_workflow(
            workflow=workflow,
            input_params={},
            context={},
            invoke_skill=invoke,
            conversation_id="conv-1",
            completed_steps={
                "author": {"status": "succeeded", "result": {"shape": "cylinder"}},
                "broken": {"status": "failed", "error": "boom"},
            },
        )
    )

    # Finished steps are not invoked again; their outputs still feed dependents.
    assert [skill for skill, _ in invoked] == ["mesh_skill"]
    assert invoked[0][1]["shape"] == "cylinder"
    assert result["step_results"]["mesh"]["params"] == {"shape": "cylinder"}
    assert result["step_statuses"] == {
        "author": "succeeded",
        "broken": "failed",
        "mesh": "succeeded",
        "report": "blocked",
    }
    assert result["errors"] == [{"step_id": "broken", "skill_id": "broken_skill", "error": "boom"}]
