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

"""The orchestrator's tool catalog, call validation, form answers and transcript helpers.

The turn itself is one ADK run of the client agent; ``test_adk_orchestrator.py`` covers it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)
from capability_cache import AgentCapability
from orchestrator import agent_loop, runtime


def _capability(skill_id: str, input_schema: Dict[str, Any], **kwargs: Any) -> AgentCapability:
    return AgentCapability(
        agent_id="test-agent",
        agent_name="Test Agent",
        agent_url="http://litellm:4000/a2a/test-agent",
        skill_id=skill_id,
        skill_name=skill_id.replace("_", " ").title(),
        description=f"{skill_id} skill",
        input_schema=input_schema,
        **kwargs,
    )


CREATE_SVG = _capability(
    "create_svg_artifact",
    {
        "type": "object",
        "properties": {
            "word": {"type": "string"},
            "color": {"type": "string"},
            "background_color": {"type": "string"},
        },
        "required": ["word"],
    },
)
CONVERT_PNG = _capability(
    "convert_svg_to_png",
    {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "description": "SVG to convert.", "x_artifact_ref": "single"},
            "artifacts": {"type": "array"},
        },
        "required": ["artifact_id"],
    },
)
THERMAL = _capability(
    "analyze_thermal",
    {
        "type": "object",
        "properties": {
            "material_id": {"type": "string"},
            "temperature_c": {"type": "number", "description": "Operating temperature."},
        },
        "required": ["material_id", "temperature_c"],
    },
)
REVIEW = _capability(
    "review_document",
    {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
    requires_approval=True,
)
MESH = _capability(
    "generate_mesh",
    {
        "type": "object",
        "properties": {
            "geometry_id": {"type": "string", "x_input_source": "runtime"},
            "element_size": {"type": "number"},
        },
        "required": ["geometry_id", "element_size"],
    },
)
CAPABILITIES = [CREATE_SVG, CONVERT_PNG, THERMAL, REVIEW, MESH]

SVG_ARTIFACT = {
    "artifact_id": "svg-1",
    "name": "popelnase.svg",
    "mime_type": "image/svg+xml",
    "description": "SVG with the word.",
    "uri": "deeplynx://organizations/1/projects/1/items/1",
}
UPLOADED_REPORT = {
    "artifact_id": "up-1",
    "name": "report.csv",
    "description": "Uploaded CSV.",
    "uri": "deeplynx://organizations/1/projects/1/items/9",
    "mime_type": "text/csv",
    "metadata": {"source": "user-upload"},
}


@pytest.fixture
def capabilities(monkeypatch) -> List[AgentCapability]:
    """The capability cache build_tool_catalog reads; the workflow library is off."""
    listed = list(CAPABILITIES)

    async def get_capabilities():
        return listed

    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", False)
    monkeypatch.setattr(agent_loop, "get_capability_cache", lambda: SimpleNamespace(get_capabilities=get_capabilities))
    return listed


def _catalog() -> Dict[str, agent_loop.ToolSpec]:
    return asyncio.run(agent_loop.build_tool_catalog())


def _spec(capability: AgentCapability) -> agent_loop.ToolSpec:
    return agent_loop._skill_spec(capability.skill_id, capability)


def _state(*artifacts: Dict[str, Any]) -> Dict[str, Any]:
    return {"context": {"artifacts": list(artifacts)}}


# --------------------------------------------------------------------------- #
# Tool catalog
# --------------------------------------------------------------------------- #


def test_catalog_advertises_plain_schemas(capabilities) -> None:
    catalog = _catalog()

    convert = catalog["convert_svg_to_png"]
    properties = convert.parameters["properties"]
    assert set(properties) == {"artifact_id"}
    assert "x_artifact_ref" not in properties["artifact_id"]
    assert "artifact_id of an existing conversation artifact" in properties["artifact_id"]["description"]
    assert convert.parameters["required"] == ["artifact_id"]
    assert "Requires user approval" in catalog["review_document"].description
    assert catalog["review_document"].requires_approval is True
    assert catalog[agent_loop.ASK_USER_TOOL] is agent_loop.ASK_USER_SPEC


def test_catalog_gives_colliding_skill_ids_unique_tool_names(capabilities) -> None:
    capabilities.append(_capability("create.svg artifact", {"type": "object"}))
    capabilities.append(_capability("create svg.artifact", {"type": "object"}))

    catalog = _catalog()

    assert catalog["create_svg_artifact"].target == "create_svg_artifact"
    assert catalog["create_svg_artifact_2"].target == "create.svg artifact"
    assert catalog["create_svg_artifact_3"].target == "create svg.artifact"


def test_skill_spec_splits_user_inputs_from_runtime_inputs() -> None:
    # Users type plain values; artifact references and runtime inputs are the model's to fill.
    assert _spec(THERMAL).user_required == ("material_id", "temperature_c")
    assert _spec(THERMAL).runtime_required == ()
    assert _spec(CONVERT_PNG).user_required == ()
    assert _spec(CONVERT_PNG).runtime_required == ("artifact_id",)
    assert _spec(MESH).user_required == ("element_size",)
    assert _spec(MESH).runtime_required == ("geometry_id",)


def test_catalog_advertises_the_newest_workflow_version_as_a_tool(capabilities, monkeypatch) -> None:
    def workflow(version: str) -> SimpleNamespace:
        definition = SimpleNamespace(
            id="thermal.quick_check",
            version=version,
            name="Quick Thermal Check",
            description="Thermal screening.",
            steps=[SimpleNamespace(id="s1", skill_id="analyze_thermal")],
            metadata=SimpleNamespace(requires_approval=True, estimated_duration_seconds=60),
            ui=SimpleNamespace(display_name=f"Quick Thermal Check {version}"),
        )
        return SimpleNamespace(definition=definition, required_input_paths=["material_id"])

    form_field = {
        "field": "material_id",
        "label": "Material",
        "description": "Material id",
        "type": "select",
        "options": ["SS316", "A36"],
    }
    forms: List[Dict[str, Any]] = []

    def build_input_form(**kwargs: Any) -> Dict[str, Any]:
        forms.append(kwargs)
        return {"fields": [form_field]}

    registry = SimpleNamespace(
        list_all=lambda: [workflow("1.0.0"), workflow("2.0.0")], build_input_form=build_input_form
    )
    monkeypatch.setattr(runtime, "ENABLE_WORKFLOW_LIBRARY", True)
    monkeypatch.setattr(agent_loop, "get_workflow_registry", lambda: registry)

    catalog = _catalog()
    workflows = [spec for spec in catalog.values() if spec.kind == "workflow"]

    assert len(workflows) == 1
    spec = workflows[0]
    assert agent_loop.workflow_tool_for(catalog, "thermal.quick_check") is spec
    assert [form["version"] for form in forms] == ["2.0.0"]
    assert spec.label == "Quick Thermal Check 2.0.0"
    assert spec.parameters == {
        "type": "object",
        "properties": {"material_id": {"type": "string", "description": "Material id", "enum": ["SS316", "A36"]}},
    }
    assert spec.user_required == ("material_id",)
    assert spec.requires_approval is True
    assert "Steps: analyze_thermal" in spec.description
    assert spec.form_fields == (form_field,)


# --------------------------------------------------------------------------- #
# Call validation
# --------------------------------------------------------------------------- #


def test_valid_call_has_no_problem() -> None:
    assert agent_loop._validation_problem(_spec(CREATE_SVG), {"word": "valve"}, _state()) is None
    assert agent_loop._validation_problem(_spec(CONVERT_PNG), {"artifact_id": "svg-1"}, _state(SVG_ARTIFACT)) is None


def test_unknown_artifact_reference_is_a_problem() -> None:
    problem = agent_loop._validation_problem(_spec(CONVERT_PNG), {"artifact_id": "nope"}, _state(SVG_ARTIFACT))

    assert problem is not None
    assert "Unknown artifact_id nope" in problem
    assert "Known: svg-1" in problem


def test_missing_artifact_reference_sends_the_model_to_the_artifact_catalog() -> None:
    problem = agent_loop._validation_problem(_spec(CONVERT_PNG), {}, _state())

    assert problem is not None
    assert "artifact_id" in problem and "artifact catalog" in problem


def test_missing_runtime_input_sends_the_model_upstream() -> None:
    problem = agent_loop._validation_problem(_spec(MESH), {"element_size": 0.5}, _state())

    assert problem is not None
    assert "geometry_id" in problem
    assert "call the upstream skill first" in problem


def test_schema_violation_is_a_problem() -> None:
    problem = agent_loop._validation_problem(_spec(THERMAL), {"material_id": "SS316", "temperature_c": "hot"}, _state())

    assert problem is not None
    assert problem.startswith("Invalid arguments: ")
    assert "temperature_c" in problem


def test_missing_user_input_is_not_a_validation_problem() -> None:
    spec = _spec(THERMAL)
    arguments = {"material_id": "SS316"}

    assert agent_loop._validation_problem(spec, arguments, _state()) is None
    assert agent_loop._missing_user_inputs(spec, arguments) == ["temperature_c"]
    assert agent_loop._missing_user_inputs(spec, {**arguments, "temperature_c": 550}) == []


# --------------------------------------------------------------------------- #
# Form answers
# --------------------------------------------------------------------------- #


def test_coerce_answer_treats_unparseable_values_as_absent() -> None:
    assert agent_loop.coerce_answer("550", "number") == 550.0
    assert agent_loop.coerce_answer("ten", "number") is None
    assert agent_loop.coerce_answer("2.5", "integer") is None
    assert agent_loop.coerce_answer("3", "integer") == 3


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "files, expected",
    [
        (
            {"uploaded_artifact_ids": ["up-1"]},
            "Summarize this\n\n[Files uploaded with this message: up-1 (report.csv)]",
        ),
        ({"received_files": [{"name": "big.bin"}]}, "Summarize this\n\n[Files received but not stored: big.bin]"),
        ({}, "Summarize this"),
    ],
    ids=["uploaded", "received-not-stored", "no-files"],
)
def test_begin_user_turn_appends_the_query_with_its_upload_note(files, expected) -> None:
    state: Dict[str, Any] = {
        "context": {"artifacts": [UPLOADED_REPORT]},
        "llm_messages": [{"role": "user", "content": "earlier"}],
        "pending_calls": [{"id": "old"}],
        "pending_note": "note",
        "turn_tool_results": {"x": {}},
        "turn_tool_inputs": {"x": {}},
    }

    agent_loop.begin_user_turn(state, "  Summarize this ", **files)

    assert state["llm_messages"][-1] == {"role": "user", "content": expected}
    assert state["pending_calls"] == []
    assert state["pending_note"] == ""
    assert state["turn_tool_results"] == {}
    assert state["turn_tool_inputs"] == {}


def test_trim_transcript_cuts_only_at_a_user_message() -> None:
    limit = agent_loop.MAX_TRANSCRIPT_MESSAGES
    short = [{"role": "user", "content": "q"}]
    assert agent_loop.trim_transcript(short) is short

    turns = [
        message
        for index in range(limit)
        for message in (
            {"role": "user", "content": f"q{index}"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{index}"}]},
            {"role": "tool", "tool_call_id": f"c{index}", "content": "{}"},
        )
    ]

    trimmed = agent_loop.trim_transcript(turns)

    assert len(trimmed) <= limit
    assert trimmed[0]["role"] == "user"
    assert trimmed == turns[len(turns) - len(trimmed) :]


def test_recent_skill_inputs_keeps_the_newest_call_per_skill(capabilities) -> None:
    state = {
        "conversation_history": [
            {"role": "assistant", "tool_inputs": {"create_svg_artifact": {"word": "old"}}},
            {"role": "user", "content": "again"},
            {
                "role": "assistant",
                "tool_inputs": {
                    "create_svg_artifact": {"word": "first"},
                    "create_svg_artifact#2": {"word": "second", "artifacts": [{"artifact_id": "a"}]},
                    "analyze_thermal": {"material_id": "SS316"},
                },
            },
        ]
    }

    assert agent_loop.recent_skill_inputs(state, _catalog()) == [
        '- create_svg_artifact: {"word": "second"}',
        '- analyze_thermal: {"material_id": "SS316"}',
    ]


def test_recent_skill_inputs_keep_only_fields_the_current_schema_declares(capabilities) -> None:
    capabilities.append(
        _capability(
            "mesh_part",
            {
                "type": "object",
                "properties": {
                    "geometry": {"type": "object", "properties": {"radius": {"type": "number"}}},
                    "holes": {"type": "array", "items": {"type": "object", "properties": {"d": {"type": "number"}}}},
                    "options": {"type": "object"},
                },
            },
        )
    )
    state = {
        "conversation_history": [
            {
                "role": "assistant",
                "tool_inputs": {
                    # The skill has since dropped step_artifact_id.
                    "convert_svg_to_png": {"artifact_id": "svg-1", "step_artifact_id": "svg-0"},
                    "retired_skill": {"x": 1},
                    "mesh_part": {
                        "geometry": {"radius": 2, "units": "mm"},
                        "holes": [{"d": 1, "depth": 3}],
                        "options": {"refine": True},
                    },
                },
            },
        ]
    }

    assert agent_loop.recent_skill_inputs(state, _catalog()) == [
        '- convert_svg_to_png: {"artifact_id": "svg-1"}',
        '- mesh_part: {"geometry": {"radius": 2}, "holes": [{"d": 1}], "options": {"refine": true}}',
    ]
