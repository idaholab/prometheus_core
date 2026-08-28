"""Tests for strict request decomposition and exhaustive operation coverage."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

CLIENT_AGENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_AGENT_DIR))

import planner  # noqa: E402
from capability_cache import AgentCapability  # noqa: E402
from orchestrator import parameters, runtime  # noqa: E402


def _operation(operation_id: str, description: str, depends_on=None):
    return planner.RequestedOperation(
        operation_id=operation_id,
        description=description,
        depends_on=list(depends_on or []),
    )


CAPABILITIES = {
    "author_equipment_geometry": SimpleNamespace(input_schema={}),
    "mesh_geometry": SimpleNamespace(input_schema={}),
}


def _tools_by_name(draft):
    tools = planner._build_planning_tools(draft, CAPABILITIES, context={})
    return {tool.name: tool.func for tool in tools}


def test_mesh_only_plan_cannot_finalize_when_geometry_update_is_uncovered() -> None:
    draft = planner._PlanDraft(
        operations=[
            _operation("op_1", "Re-author the valve with larger, evenly distributed holes"),
            _operation("op_2", "Mesh the newly authored CAD with tetrahedra", ["op_1"]),
        ]
    )
    tools = _tools_by_name(draft)

    tools["select_capabilities"](
        primary_skill="mesh_geometry",
        workflow_type="single",
    )
    tools["set_operation_coverage"](
        covered=[{"operation_id": "op_2", "skill_id": "mesh_geometry"}],
        unsupported=[],
    )

    result = tools["finalize_plan"]()

    assert result["ok"] is False
    assert result["uncovered_operation_ids"] == ["op_1"]
    assert draft.finalized is False


def test_reauthor_then_mesh_plan_finalizes_in_dependency_order() -> None:
    draft = planner._PlanDraft(
        operations=[
            _operation("op_1", "Re-author the valve with larger, evenly distributed holes"),
            _operation("op_2", "Mesh the newly authored CAD with tetrahedra", ["op_1"]),
        ]
    )
    tools = _tools_by_name(draft)

    tools["select_capabilities"](
        primary_skill="author_equipment_geometry",
        supporting_skills=["mesh_geometry"],
        workflow_type="sequential",
    )
    coverage = tools["set_operation_coverage"](
        covered=[
            {"operation_id": "op_1", "skill_id": "author_equipment_geometry"},
            {"operation_id": "op_2", "skill_id": "mesh_geometry"},
        ],
        unsupported=[],
    )

    assert coverage["ok"] is True
    assert tools["finalize_plan"]()["ok"] is True
    assert draft.finalized is True


def test_registered_dag_workflow_owns_cross_skill_dependency_order() -> None:
    draft = planner._PlanDraft(
        operations=[
            _operation("op_1", "Re-author the valve"),
            _operation("op_2", "Mesh the new CAD", ["op_1"]),
        ]
    )
    candidate = planner.WorkflowPlanningCandidate(
        workflow_id="author_and_mesh",
        workflow_version="1.0.0",
        score=0.0,
        skills=["author_equipment_geometry", "mesh_geometry"],
        execution_mode="dag",
    )
    tools = {
        tool.name: tool.func
        for tool in planner._build_planning_tools(
            draft,
            CAPABILITIES,
            context={},
            workflow_candidates=[candidate],
        )
    }

    tools["select_workflow_template"](workflow_id="author_and_mesh")
    tools["set_operation_coverage"](
        covered=[
            {"operation_id": "op_1", "skill_id": "author_equipment_geometry"},
            {"operation_id": "op_2", "skill_id": "mesh_geometry"},
        ],
        unsupported=[],
    )

    result = tools["finalize_plan"]()

    assert result["ok"] is True
    assert draft.finalized is True


def test_remesh_plan_rejects_unneeded_authoring_capability() -> None:
    draft = planner._PlanDraft(
        operations=[
            _operation(
                "op_1",
                "Remesh the existing valve CAD with half the element size",
            )
        ]
    )
    tools = _tools_by_name(draft)

    tools["select_capabilities"](
        primary_skill="author_equipment_geometry",
        supporting_skills=["mesh_geometry"],
        workflow_type="sequential",
    )
    tools["set_operation_coverage"](
        covered=[{"operation_id": "op_1", "skill_id": "mesh_geometry"}],
        unsupported=[],
    )

    result = tools["finalize_plan"]()

    assert result["ok"] is False
    assert result["unused_selected_skill_ids"] == ["author_equipment_geometry"]
    assert draft.finalized is False


def test_cross_skill_dependency_requires_sequential_selection_order() -> None:
    draft = planner._PlanDraft(
        operations=[
            _operation("op_1", "Re-author the valve"),
            _operation("op_2", "Mesh the new CAD", ["op_1"]),
        ]
    )
    tools = _tools_by_name(draft)

    tools["select_capabilities"](
        primary_skill="mesh_geometry",
        supporting_skills=["author_equipment_geometry"],
        workflow_type="sequential",
    )
    tools["set_operation_coverage"](
        covered=[
            {"operation_id": "op_1", "skill_id": "author_equipment_geometry"},
            {"operation_id": "op_2", "skill_id": "mesh_geometry"},
        ],
        unsupported=[],
    )

    result = tools["finalize_plan"]()

    assert result["ok"] is False
    assert "dependency order" in result["error"]


def test_execution_preserves_validated_operation_dependency_order(monkeypatch) -> None:
    monkeypatch.setattr(
        parameters,
        "get_capability_cache",
        lambda: SimpleNamespace(
            get_by_skill_id=lambda skill_id: SimpleNamespace(
                usage_notes="",
                provides=[],
                derivation_rules=[],
                execution_priority=(
                    "late" if skill_id == "author_equipment_geometry" else "early"
                ),
            )
        ),
    )
    routing = {
        "primary_skill": "author_equipment_geometry",
        "supporting_skills": ["mesh_geometry"],
        "workflow_type": "sequential",
        "operations": [
            {"operation_id": "op_1", "depends_on": []},
            {"operation_id": "op_2", "depends_on": ["op_1"]},
        ],
        "operation_coverage": {
            "op_1": "author_equipment_geometry",
            "op_2": "mesh_geometry",
        },
    }

    assert parameters.order_skills_for_workflow(routing) == [
        "author_equipment_geometry",
        "mesh_geometry",
    ]


def test_any_unsupported_operation_blocks_partial_execution() -> None:
    draft = planner._PlanDraft(
        operations=[
            _operation("op_1", "Create CAD geometry"),
            _operation("op_2", "Mesh the CAD", ["op_1"]),
        ]
    )
    tools = _tools_by_name(draft)

    tools["select_capabilities"](
        primary_skill="mesh_geometry",
        workflow_type="single",
    )
    tools["set_operation_coverage"](
        covered=[{"operation_id": "op_2", "skill_id": "mesh_geometry"}],
        unsupported=[{"operation_id": "op_1", "reason": "No CAD author is registered"}],
    )

    result = tools["finalize_plan"]()

    assert result["ok"] is True
    assert draft.outcome == "unsupported"
    assert draft.primary_skill is None
    assert draft.finalized is True


def test_no_registered_capabilities_marks_every_operation_unsupported() -> None:
    result = asyncio.run(
        planner.compile_plan_with_tools(
            query="Create CAD and mesh it.",
            capabilities=[],
            operations=[
                _operation("op_1", "Create CAD geometry"),
                _operation("op_2", "Mesh the CAD", ["op_1"]),
            ],
        )
    )

    assert result.outcome == "unsupported"
    assert [item.operation_id for item in result.unsupported_operations] == [
        "op_1",
        "op_2",
    ]


class _DecompositionLLM:
    def __init__(self, tool_calls, subsequent_tool_calls=None):
        self.tool_call_responses = [tool_calls, *(subsequent_tool_calls or [])]
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def medium(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        response_index = min(len(self.calls) - 1, len(self.tool_call_responses) - 1)
        return SimpleNamespace(
            raw={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": self.tool_call_responses[response_index],
                        }
                    }
                ]
            }
        )


def _turn_resolution_call(arguments, call_id="resolve-1"):
    kind = arguments["resolution_kind"]
    tool_names = {
        "new_task": "resolve_new_task",
        "repeat_prior_task_with_changes": "resolve_repeat_prior_task_with_changes",
        "discuss_prior_result": "resolve_prior_result_discussion",
        "needs_clarification": "resolve_needs_clarification",
    }
    tool_arguments = {}
    if arguments.get("standalone_request"):
        tool_arguments["standalone_request"] = arguments["standalone_request"]
    if arguments.get("referenced_invocation_id"):
        tool_arguments["referenced_invocation_id"] = arguments[
            "referenced_invocation_id"
        ]
    if arguments.get("message"):
        tool_arguments["message"] = arguments["message"]
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": tool_names[kind],
            "arguments": json.dumps(tool_arguments),
        },
    }


def _decomposition_call(arguments, call_id="decompose-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "decompose_task",
            "arguments": json.dumps(arguments),
        },
    }


def _dependency_call(arguments, call_id="dependencies-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "assign_dependencies",
            "arguments": json.dumps(arguments),
        },
    }


def _planning_call(name, arguments, call_id):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


def _literature_history(result=None):
    if result is None:
        result = {
            "answer": "",
            "papers": ["FULL PAPER PAYLOAD MUST NOT ENTER THE RESOLVER PROMPT"],
        }
    return [
        {
            "role": "user",
            "content": (
                "Perform a literature search on suitable wall materials for "
                "fluoride molten salt reactors"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Found 15 papers, but could not extract answers from the available PDFs."
            ),
            "tool_inputs": {
                "search_literature": {
                    "question": (
                        "Perform a literature search on suitable wall materials for "
                        "fluoride molten salt reactors"
                    )
                }
            },
            "tool_results": {"search_literature": result},
        },
        {"role": "user", "content": "what about chloride salts?"},
    ]


def test_turn_resolution_expands_elliptical_followup_from_actual_invocation(
    monkeypatch,
) -> None:
    standalone_request = (
        "Perform a literature search on suitable wall materials for chloride "
        "molten salt reactors."
    )
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "repeat_prior_task_with_changes",
                    "standalone_request": standalone_request,
                    "referenced_invocation_id": "invocation_1",
                    "message": "",
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    result = asyncio.run(
        planner.resolve_turn(
            query="what about chloride salts?",
            history=_literature_history(),
            context={},
        )
    )

    assert result.resolution_kind == "repeat_prior_task_with_changes"
    assert result.standalone_request == standalone_request
    assert result.referenced_invocation_id == "invocation_1"
    prompt = fake_llm.calls[0][0][1]["content"]
    assert "invocation_1" in prompt
    assert "fluoride molten salt reactors" in prompt
    assert "FULL PAPER PAYLOAD MUST NOT ENTER THE RESOLVER PROMPT" not in prompt
    resolver_tool = next(
        tool
        for tool in fake_llm.calls[0][1]["tools"]
        if tool["function"]["name"] == "resolve_repeat_prior_task_with_changes"
    )
    for tool in fake_llm.calls[0][1]["tools"]:
        parameters = tool["function"]["parameters"]
        assert parameters["type"] == "object"
        assert not (
            {"oneOf", "anyOf", "allOf", "enum", "const", "not"}
            & parameters.keys()
        )
    resolver_schema = resolver_tool["function"]["parameters"]
    reference_schema = resolver_schema["properties"]["referenced_invocation_id"]
    assert reference_schema == {
        "type": "string",
        "enum": ["invocation_1"],
    }
    validator = Draft202012Validator(resolver_schema)
    valid_repeat = {
        "standalone_request": standalone_request,
        "referenced_invocation_id": "invocation_1",
    }
    assert list(validator.iter_errors(valid_repeat)) == []
    assert list(validator.iter_errors({**valid_repeat, "referenced_invocation_id": None}))


def test_turn_resolution_excludes_repeat_without_recorded_invocations(monkeypatch) -> None:
    standalone_request = (
        "Create a 90 cm butterfly valve with four 10 cm holes and an 8 cm rod, "
        "then mesh it."
    )
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "new_task",
                    "standalone_request": standalone_request,
                    "referenced_invocation_id": None,
                    "message": "",
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)
    history = [
        {
            "role": "user",
            "content": (
                "Create a 90 cm butterfly valve with four 5 cm holes and an 8 cm rod, "
                "then mesh it."
            ),
        },
        {
            "role": "assistant",
            "content": "Equipment authoring complete.",
            "tool_results": {
                "author_equipment_geometry": {"message": "Equipment authoring complete."}
            },
        },
    ]

    result = asyncio.run(
        planner.resolve_turn(
            query="Redo the valve with 4 holes at 10cm diameter each and then mesh it",
            history=history,
            context={},
        )
    )

    assert result.resolution_kind == "new_task"
    resolver_tools = fake_llm.calls[0][1]["tools"]
    tool_names = [tool["function"]["name"] for tool in resolver_tools]
    assert "resolve_repeat_prior_task_with_changes" not in tool_names
    for tool in resolver_tools:
        resolver_schema = tool["function"]["parameters"]
        assert resolver_schema["type"] == "object"
        assert not (
            {"oneOf", "anyOf", "allOf", "enum", "const", "not"}
            & resolver_schema.keys()
        )


def test_turn_resolution_can_repeat_failed_prior_invocation(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "repeat_prior_task_with_changes",
                    "standalone_request": (
                        "Perform a literature search on suitable wall materials for "
                        "chloride molten salt reactors."
                    ),
                    "referenced_invocation_id": "invocation_1",
                    "message": "",
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    result = asyncio.run(
        planner.resolve_turn(
            query="what about chloride salts?",
            history=_literature_history({"error": "PDF extraction failed"}),
            context={},
        )
    )

    assert result.resolution_kind == "repeat_prior_task_with_changes"
    prompt = fake_llm.calls[0][0][1]["content"]
    assert '"outcome": "error"' in prompt
    assert "PDF extraction failed" in prompt


def test_turn_resolution_rejects_unknown_invocation_reference(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "repeat_prior_task_with_changes",
                    "standalone_request": "Search the literature for chloride salts.",
                    "referenced_invocation_id": "invocation_99",
                    "message": "",
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    with pytest.raises(
        planner.PlanningContractError,
        match="unavailable prior invocation 'invocation_99'",
    ):
        asyncio.run(
            planner.resolve_turn(
                query="what about chloride salts?",
                history=_literature_history(),
                context={},
            )
        )


def test_turn_resolution_rejects_contradictory_new_task_payload(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "new_task",
                    "standalone_request": "Search the literature for chloride salts.",
                    "referenced_invocation_id": None,
                    "message": "I will search now.",
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    with pytest.raises(
        planner.PlanningContractError,
        match="Turn resolution violates its schema",
    ):
        asyncio.run(
            planner.resolve_turn(
                query="Search the literature for chloride salts.",
                history=[],
                context={},
            )
        )


def test_discussion_resolution_returns_fallback_without_decomposition(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "discuss_prior_result",
                    "standalone_request": "",
                    "referenced_invocation_id": "invocation_1",
                    "message": "The prior search did not produce extractable answers.",
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    result = asyncio.run(
        planner.compile_plan_with_tools(
            query="What did the prior search conclude?",
            capabilities=[],
            history=_literature_history(),
        )
    )

    assert result.outcome == "fallback"
    assert result.resolution_kind == "discuss_prior_result"
    assert result.message == "The prior search did not produce extractable answers."
    assert len(fake_llm.calls) == 1


def test_decomposition_assigns_stable_ids_and_dependencies(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _decomposition_call(
                {
                    "operations": [
                        {
                            "description": "Re-author the valve with twice the hole diameter",
                        },
                        {
                            "description": "Mesh the newly authored CAD with about 30000 tetrahedra",
                        },
                    ],
                }
            )
        ],
        [
            [
                _dependency_call(
                    {
                        "dependencies": {
                            "op_1": [],
                            "op_2": ["op_1"],
                        }
                    }
                )
            ]
        ],
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    result = asyncio.run(
        planner.decompose_task(
            query="Make the holes larger, then mesh the CAD.",
        )
    )

    assert [operation.operation_id for operation in result.operations] == ["op_1", "op_2"]
    assert result.operations[1].depends_on == ["op_1"]
    prompt = fake_llm.calls[0][0][1]["content"]
    assert "Available capabilities" not in prompt
    assert fake_llm.calls[0][1]["tools"][0]["function"]["strict"] is True
    decomposition_schema = fake_llm.calls[0][1]["tools"][0]["function"]["parameters"]
    assert "depends_on" not in json.dumps(decomposition_schema)
    assert fake_llm.calls[1][1]["tools"][0]["function"]["strict"] is True
    dependency_schema = fake_llm.calls[1][1]["tools"][0]["function"]["parameters"]
    dependency_properties = dependency_schema["properties"]["dependencies"]["properties"]
    # maxItems/uniqueItems are stripped from the wire schema for OpenAI strict-mode
    # compatibility; op_1 (no earlier ops) is left with an unconstrained items type.
    assert "maxItems" not in dependency_properties["op_1"]
    assert dependency_properties["op_1"]["items"] == {"type": "string"}
    assert dependency_properties["op_2"]["items"]["enum"] == ["op_1"]


def test_single_operation_decomposition_does_not_ask_for_dependencies(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _decomposition_call(
                {
                    "operations": [{"description": "Remesh the attached CAD"}],
                }
            )
        ]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    result = asyncio.run(
        planner.decompose_task(
            query="Remesh it with half the element size.",
        )
    )

    assert result.operations == [
        _operation("op_1", "Remesh the attached CAD", [])
    ]
    assert len(fake_llm.calls) == 1
    system_prompt = fake_llm.calls[0][0][0]["content"]
    assert "Remeshing reuses the most recent existing CAD" in system_prompt
    assert "mesh controls such as element size" in system_prompt
    decomposition_schema = fake_llm.calls[0][1]["tools"][0]["function"]["parameters"]
    assert "depends_on" not in json.dumps(decomposition_schema)


def test_dependency_assignment_rejects_self_dependencies(monkeypatch) -> None:
    fake_llm = _DecompositionLLM(
        [
            _decomposition_call(
                {
                    "operations": [
                        {"description": "Create CAD geometry"},
                        {"description": "Mesh the created CAD"},
                    ],
                }
            )
        ],
        [
            [
                _dependency_call(
                    {
                        "dependencies": {
                            "op_1": ["op_1"],
                            "op_2": [],
                        }
                    }
                )
            ]
        ],
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    with pytest.raises(
        planner.PlanningContractError,
        match="operation 1 references non-earlier dependencies: op_1",
    ):
        asyncio.run(
            planner.decompose_task(
                query="Create CAD and mesh it.",
            )
        )


def test_decomposition_rejects_more_than_one_tool_call(monkeypatch) -> None:
    arguments = {
        "operations": [{"description": "Mesh CAD", "depends_on": []}],
    }
    fake_llm = _DecompositionLLM(
        [_decomposition_call(arguments, "one"), _decomposition_call(arguments, "two")]
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)

    with pytest.raises(planner.PlanningContractError, match="exactly once"):
        asyncio.run(
            planner.decompose_task(
                query="Mesh the CAD.",
            )
        )


def test_compile_plan_routes_resolved_elliptical_followup(monkeypatch) -> None:
    standalone_request = (
        "Perform a literature search on suitable wall materials for chloride "
        "molten salt reactors."
    )
    fake_llm = _DecompositionLLM(
        [
            _turn_resolution_call(
                {
                    "resolution_kind": "repeat_prior_task_with_changes",
                    "standalone_request": standalone_request,
                    "referenced_invocation_id": "invocation_1",
                    "message": "",
                }
            )
        ],
        [
            [
                _decomposition_call(
                    {
                        "operations": [
                            {
                                "description": (
                                    "Search the literature for suitable wall materials "
                                    "for chloride molten salt reactors"
                                )
                            }
                        ]
                    }
                )
            ],
            [
                _planning_call(
                    "select_capabilities",
                    {
                        "primary_skill": "search_literature",
                        "supporting_skills": [],
                        "workflow_type": "single",
                        "reasoning": "A new literature search is required.",
                        "confidence": 0.98,
                    },
                    "select-1",
                ),
                _planning_call(
                    "set_operation_coverage",
                    {
                        "covered": [
                            {
                                "operation_id": "op_1",
                                "skill_id": "search_literature",
                            }
                        ],
                        "unsupported": [],
                    },
                    "coverage-1",
                ),
                _planning_call("finalize_plan", {}, "finalize-1"),
            ],
        ],
    )
    monkeypatch.setattr(runtime, "create_llm", lambda: fake_llm)
    capability = AgentCapability(
        agent_id="osti-research-agent",
        agent_name="OSTI Research Agent",
        agent_url="http://osti-research-agent:8000",
        skill_id="search_literature",
        skill_name="Search Literature",
        description="Search scientific literature.",
    )

    result = asyncio.run(
        planner.compile_plan_with_tools(
            query="what about chloride salts?",
            capabilities=[capability],
            history=_literature_history(),
        )
    )

    assert result.outcome == "agent_plan"
    assert result.primary_skill == "search_literature"
    assert result.resolved_query == standalone_request
    assert result.resolution_kind == "repeat_prior_task_with_changes"
    routing_prompt = fake_llm.calls[2][0][1]["content"]
    assert f"User query:\n{standalone_request}" in routing_prompt


def test_unfinalized_planner_response_is_a_contract_error(monkeypatch) -> None:
    class _NoToolLLM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def medium(self, messages, **kwargs):
            return SimpleNamespace(
                raw={"choices": [{"message": {"content": "", "tool_calls": []}}]}
            )

    monkeypatch.setattr(runtime, "create_llm", lambda: _NoToolLLM())

    with pytest.raises(planner.PlanningContractError, match="did not finalize"):
        asyncio.run(
            planner.compile_plan_with_tools(
                query="Mesh the CAD.",
                capabilities=[
                    AgentCapability(
                        agent_id="mesh-agent",
                        agent_name="Mesh Agent",
                        agent_url="http://mesh-agent:8000",
                        skill_id="mesh_geometry",
                        skill_name="Mesh Geometry",
                        description="Mesh CAD geometry.",
                    )
                ],
                operations=[_operation("op_1", "Mesh the CAD")],
                max_turns=1,
            )
        )
