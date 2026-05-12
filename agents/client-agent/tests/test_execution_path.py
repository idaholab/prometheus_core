"""Targeted tests for orchestrator execution-path selection."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
import types

CLIENT_AGENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_AGENT_DIR))
PROMETHEUS_API_DIR = Path(__file__).resolve().parents[3] / "prometheus_api"
if str(PROMETHEUS_API_DIR) not in sys.path:
    sys.path.insert(0, str(PROMETHEUS_API_DIR))

if "langchain_anthropic" not in sys.modules:
    langchain_anthropic = types.ModuleType("langchain_anthropic")
    langchain_anthropic.ChatAnthropic = object
    sys.modules["langchain_anthropic"] = langchain_anthropic

if "langchain_core.messages" not in sys.modules:
    langchain_core = sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    messages_module = types.ModuleType("langchain_core.messages")
    messages_module.HumanMessage = object
    messages_module.SystemMessage = object
    messages_module.ToolMessage = object
    sys.modules["langchain_core.messages"] = messages_module
    langchain_core.messages = messages_module

if "langchain_core.tools" not in sys.modules:
    tools_module = types.ModuleType("langchain_core.tools")

    class _StructuredTool:
        @staticmethod
        def from_function(*args, **kwargs):
            return SimpleNamespace(name=kwargs.get("name", "tool"), invoke=lambda tool_args: {})

    tools_module.StructuredTool = _StructuredTool
    sys.modules["langchain_core.tools"] = tools_module

if "prometheus_api.agent" not in sys.modules:
    prometheus_api_module = types.ModuleType("prometheus_api")
    agent_api_module = types.ModuleType("prometheus_api.agent")

    class _ArtifactReference:
        def __init__(self, **kwargs):
            self.artifact_id = kwargs.get("artifact_id")
            self.conversation_id = kwargs.get("conversation_id")
            self.name = kwargs.get("name")
            self.description = kwargs.get("description")
            self.uri = kwargs.get("uri")
            self.metadata = kwargs.get("metadata") or {}
            self.json_type = kwargs.get("json_type")
            self.json_body = kwargs.get("json_body")

        @classmethod
        def from_any(cls, artifact, conversation_id=None):
            if not isinstance(artifact, dict):
                return None
            metadata = dict(artifact.get("metadata") or {})
            parts = artifact.get("parts") or []
            uri = artifact.get("uri")
            json_type = artifact.get("json_type")
            json_body = artifact.get("json_body")
            for part in parts:
                if not isinstance(part, dict):
                    continue
                kind = str(part.get("kind") or "").strip().lower()
                if kind == "file":
                    file_payload = part.get("file") or {}
                    uri = file_payload.get("uri") or uri
                elif kind == "data":
                    json_body = part.get("data")
                    part_meta = dict(part.get("metadata") or {})
                    json_type = part_meta.get("json_type") or json_type
                    metadata = {**part_meta, **metadata}
            return cls(
                artifact_id=artifact.get("artifact_id") or artifact.get("artifactId"),
                conversation_id=conversation_id or metadata.get("conversation_id"),
                name=artifact.get("name"),
                description=artifact.get("description"),
                uri=uri,
                metadata=metadata,
                json_type=json_type,
                json_body=json_body,
            )

        def to_dict(self):
            payload = {
                "artifact_id": self.artifact_id,
                "conversation_id": self.conversation_id,
                "name": self.name,
                "description": self.description,
                "uri": self.uri,
                "metadata": self.metadata,
            }
            if self.json_type is not None:
                payload["json_type"] = self.json_type
            if self.json_body is not None:
                payload["json_body"] = self.json_body
            return payload

    class _PrometheusAgent:
        def __init__(self, *args, **kwargs):
            self.artifact_registry = SimpleNamespace(register=lambda reference: None)

        @staticmethod
        def pending_hint(pending_requests, hint):
            return hint

        def list_artifact_references(self, *args, **kwargs):
            return []

        async def send_status_update(self, *args, **kwargs):
            return None

    agent_api_module.ArtifactReference = _ArtifactReference
    agent_api_module.EventQueue = object
    agent_api_module.PrometheusAgent = _PrometheusAgent
    agent_api_module.RequestContext = object
    prometheus_api_module.agent = agent_api_module
    sys.modules["prometheus_api"] = prometheus_api_module
    sys.modules["prometheus_api.agent"] = agent_api_module

import agent as agent_module


def test_execute_current_plan_routes_templates_through_workflow_engine(monkeypatch) -> None:
    workflow = SimpleNamespace(
        definition=SimpleNamespace(
            id="wf",
            version="1.0.0",
            steps=[SimpleNamespace(id="step-1", skill_id="convert_svg_to_png")],
        )
    )
    registry = SimpleNamespace(get=lambda workflow_id, version=None: workflow)
    calls = {"workflow": 0, "direct": 0}

    async def fake_execute_workflow(**kwargs):
        calls["workflow"] += 1
        return {
            "final_output": "render complete",
            "step_statuses": {"step-1": "succeeded"},
            "step_results": {
                "step-1": {
                    "skill_id": "convert_svg_to_png",
                    "result": {"answer": "render complete"},
                }
            },
        }

    async def fake_invoke_agent_generic(state):
        calls["direct"] += 1
        return {}

    monkeypatch.setattr(agent_module, "ENABLE_WORKFLOW_LIBRARY", True)
    monkeypatch.setattr(agent_module, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(agent_module, "execute_workflow", fake_execute_workflow)
    monkeypatch.setattr(agent_module, "invoke_agent_generic", fake_invoke_agent_generic)

    state = {
        "conversation_id": "conv-1",
        "routing_decision": {
            "workflow_type": "workflow_template",
            "workflow_id": "wf",
            "workflow_version": "1.0.0",
            "extracted_params": {},
        },
        "conversation_history": [],
        "context": {},
        "tool_results": {},
    }

    result = asyncio.run(agent_module.execute_current_plan(state, start_message="go"))

    assert calls == {"workflow": 1, "direct": 0}
    assert result["final_report"] == "render complete"


def test_chat_asks_followup_when_required_params_are_missing_on_initial_turn(monkeypatch) -> None:
    async def fake_compile_query_plan(state, **kwargs):
        return {
            "routing_decision": {
                "primary_skill": "analyze_thermal",
                "supporting_skills": [],
                "workflow_type": "single",
                "extracted_params": {"material_id": "SS316"},
                "requires_approval": True,
                "required_params": ["material_id", "context.temperature_c"],
                "missing_required_params": ["context.temperature_c"],
            },
            "plan": {
                "intent": "Perform a thermal analysis of ss316",
                "workflow_type": "single",
                "skills": ["analyze_thermal"],
                "required_params": ["material_id", "context.temperature_c"],
                "steps": ["Invoke analyze_thermal"],
                "missing_info": ["context.temperature_c"],
                "estimated_duration_seconds": 5,
                "param_metadata": {},
            },
            "missing_info": ["context.temperature_c"],
            "context": {},
            "material_id": "SS316",
        }

    async def fake_ask_followup_dynamic(state):
        return {
            "conversation_history": state.get("conversation_history", []) + [
                {
                    "role": "assistant",
                    "type": "followup_questions",
                    "questions": [
                        {
                            "field": "context.temperature_c",
                            "question": "Operating temperature in Celsius",
                            "type": "number",
                        }
                    ],
                }
            ],
            "missing_info": ["context.temperature_c"],
            "awaiting_approval": False,
        }

    async def should_not_extract(*args, **kwargs):
        raise AssertionError("Initial turn should not auto-extract missing follow-up answers from the query.")

    monkeypatch.setattr(agent_module, "compile_query_plan", fake_compile_query_plan)
    monkeypatch.setattr(agent_module, "ask_followup_dynamic", fake_ask_followup_dynamic)
    monkeypatch.setattr(agent_module, "extract_followup_answers_from_query", should_not_extract)
    monkeypatch.setattr(agent_module, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(agent_module, "store_conversation", lambda conversation_id, state: None)
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        agent_module.chat(
            agent_module.ConversationRequest(
                query="Perform a thermal analysis of ss316",
                conversation_id="conv-1",
            )
        )
    )

    assert response.status == "needs_info"
    assert response.followup_questions == [
        {
            "field": "context.temperature_c",
            "question": "Operating temperature in Celsius",
            "type": "number",
        }
    ]


def test_chat_exposes_received_files_to_planner_context(monkeypatch) -> None:
    seen = {}

    async def fake_compile_query_plan(state, **kwargs):
        seen["context"] = state.get("context")
        return {
            "is_fallback": True,
            "fallback_message": "ok",
        }

    monkeypatch.setattr(agent_module, "compile_query_plan", fake_compile_query_plan)
    monkeypatch.setattr(agent_module, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(agent_module, "store_conversation", lambda conversation_id, state: None)
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        agent_module.chat(
            agent_module.ConversationRequest(
                query="What can you do with this?",
                conversation_id="conv-uploads",
                received_files=[
                    {
                        "name": "model.ifc",
                        "mime_type": "application/ifc",
                        "size_bytes": 12,
                    }
                ],
            )
        )
    )

    assert response.status == "answer"
    assert seen["context"]["received_files"] == [
        {
            "name": "model.ifc",
            "mime_type": "application/ifc",
            "size_bytes": 12,
        }
    ]


def test_agents_slash_command_lists_registered_agents_without_planner(monkeypatch) -> None:
    async def should_not_compile(*args, **kwargs):
        raise AssertionError("Slash commands must not invoke the planner LLM.")

    async def fake_discover_agents():
        return [
            {
                "agent_id": "mesh-agent",
                "name": "Mesh Agent",
                "url": "http://mesh-agent:8000",
                "agent_card_params": {
                    "skills": [{"id": "inspect_mesh", "name": "Inspect Mesh"}],
                },
            }
        ]

    async def fake_get_capabilities():
        return [
            SimpleNamespace(
                agent_id="mesh-agent",
                agent_name="Mesh Agent",
                agent_url="http://litellm:4000/a2a/mesh-agent",
                skill_id="convert_mesh",
                skill_name="Convert Mesh",
            )
        ]

    monkeypatch.setattr(agent_module, "compile_query_plan", should_not_compile)
    monkeypatch.setattr(agent_module, "discover_agents", fake_discover_agents)
    monkeypatch.setattr(
        agent_module,
        "get_capability_cache",
        lambda: SimpleNamespace(get_capabilities=fake_get_capabilities),
    )
    monkeypatch.setattr(agent_module, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        agent_module.chat(
            agent_module.ConversationRequest(query="/agents", conversation_id="conv-debug")
        )
    )

    assert response.status == "answer"
    assert "Registered agents (1)" in response.message
    assert "Mesh Agent (mesh-agent)" in response.message
    assert "inspect_mesh (Inspect Mesh)" in response.message
    assert "convert_mesh (Convert Mesh)" in response.message
    assert response.message_metadata["slash_command"] == "agents"


def test_artifacts_slash_command_lists_conversation_artifacts_without_planner(monkeypatch) -> None:
    async def should_not_compile(*args, **kwargs):
        raise AssertionError("Slash commands must not invoke the planner LLM.")

    monkeypatch.setattr(agent_module, "compile_query_plan", should_not_compile)
    monkeypatch.setattr(
        agent_module,
        "get_conversation",
        lambda conversation_id: {
            "missing_info": ["context.temperature_c"],
            "context": {
                "artifacts": [
                    {
                        "artifact_id": "older-1",
                        "name": "older-result.json",
                        "description": "Earlier analysis output.",
                        "json_body": {"ok": True},
                    }
                ]
            },
        },
    )
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        agent_module.chat(
            agent_module.ConversationRequest(
                query="/artifacts",
                conversation_id="conv-debug",
                artifacts=[
                    {
                        "artifact_id": "svg-1",
                        "name": "diagram.svg",
                        "description": "Uploaded SVG.",
                        "uri": "deeplynx://container/file/123",
                        "mime_type": "image/svg+xml",
                        "metadata": {
                            "source": "user-upload",
                            "deeplynx_file_id": 123,
                        },
                    }
                ],
            )
        )
    )

    assert response.status == "answer"
    assert "Conversation artifacts (2)" in response.message
    assert "diagram.svg" in response.message
    assert "deeplynx_file_id: 123" in response.message
    assert "older-result.json" in response.message
    assert [artifact["artifact_id"] for artifact in response.artifacts] == ["svg-1", "older-1"]


def test_execute_slash_command_skips_upload_and_lazy_refresh(monkeypatch) -> None:
    async def should_not_refresh(*args, **kwargs):
        raise AssertionError("Slash commands should not refresh tool caches before handling.")

    async def should_not_upload(*args, **kwargs):
        raise AssertionError("Slash commands should not process uploaded files.")

    monkeypatch.setattr(agent_module, "_tools_cache", None)
    monkeypatch.setattr(agent_module, "refresh_dynamic_components", should_not_refresh)
    monkeypatch.setattr(agent_module.OrchestratorAgent, "_handle_uploaded_files", should_not_upload)
    monkeypatch.setattr(agent_module, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)

    artifact = SimpleNamespace(
        artifact_id="artifact-1",
        to_dict=lambda: {
            "artifact_id": "artifact-1",
            "conversation_id": "conv-debug",
            "name": "diagram.svg",
            "description": "Registered SVG.",
            "uri": "deeplynx://container/file/123",
            "mime_type": "image/svg+xml",
        },
    )
    orchestrator = agent_module.OrchestratorAgent()
    orchestrator.list_artifact_references = lambda *args, **kwargs: [artifact]

    payload = asyncio.run(
        orchestrator._execute(
            {
                "query": "/artifacts",
                "conversation_id": "conv-debug",
                "uploaded_files": [
                    {
                        "name": "ignored.svg",
                        "mime_type": "image/svg+xml",
                        "size_bytes": 12,
                        "content_b64": "PHN2Zy8+",
                    }
                ],
            },
            SimpleNamespace(context_id="conv-debug"),
            object(),
        )
    )

    assert payload["status"] == "answer"
    assert "diagram.svg" in payload["message"]
    assert payload["artifacts"][0]["artifact_id"] == "artifact-1"
    assert payload["new_artifacts"] == []


def test_invoke_agent_generic_passes_artifact_catalog_to_skill(monkeypatch) -> None:
    captured = {}

    async def fake_invoke_skill(skill_id, params, conversation_id, emit_status=True):
        captured["skill_id"] = skill_id
        captured["params"] = params
        captured["conversation_id"] = conversation_id
        return {"skill_id": skill_id, "result": {"message": "converted"}}

    async def fake_get_capability_by_skill_id(skill_id):
        return None

    monkeypatch.setattr(agent_module, "invoke_skill", fake_invoke_skill)
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agent_module,
        "get_capability_cache",
        lambda: SimpleNamespace(get_capability_by_skill_id=fake_get_capability_by_skill_id),
    )

    state = {
        "conversation_id": "conv-1",
        "routing_decision": {
            "primary_skill": "convert_svg_to_png",
            "supporting_skills": [],
            "workflow_type": "single",
            "extracted_params": {"artifact_id": "svg-1"},
        },
        "context": {
            "artifacts": [
                {
                    "artifact_id": "svg-1",
                    "name": "diagram.svg",
                    "uri": "deeplynx://organizations/1/projects/1/items/99",
                    "metadata": {"deeplynx_file_id": 123},
                }
            ]
        },
        "conversation_history": [],
    }

    result = asyncio.run(agent_module.invoke_agent_generic(state))

    assert result["tool_results"]["convert_svg_to_png"] == {"message": "converted"}
    assert captured["conversation_id"] == "conv-1"
    assert captured["params"]["artifact_id"] == "svg-1"
    assert captured["params"]["artifacts"] == [
        {
            "artifact_id": "svg-1",
            "name": "diagram.svg",
            "description": "",
            "uri": "deeplynx://organizations/1/projects/1/items/99",
            "mime_type": None,
            "size_bytes": None,
            "producer_agent_id": None,
            "created_at": None,
            "tags": [],
            "metadata": {"deeplynx_file_id": 123},
        }
    ]


def test_find_tool_for_skill_uses_runtime_tool_cache(monkeypatch) -> None:
    tool = SimpleNamespace(name="create_svg_artifact")

    monkeypatch.setattr(agent_module._runtime, "_tools_cache", [tool])

    result = asyncio.run(
        agent_module.find_tool_for_skill(
            "create_svg_artifact",
            refresh_on_miss=False,
        )
    )

    assert result is tool


def test_invoke_skill_validates_nested_required_paths(monkeypatch) -> None:
    capability = SimpleNamespace(
        input_schema={
            "type": "object",
            "properties": {
                "material_id": {"type": "string"},
                "context": {
                    "type": "object",
                    "properties": {
                        "temperature_c": {"type": "number"},
                    },
                    "required": ["temperature_c"],
                },
            },
            "required": ["material_id", "context"],
        }
    )

    class _UnexpectedTool:
        async def ainvoke(self, params):
            raise AssertionError("Tool should not be invoked when nested required params are missing.")

    async def fake_find_tool_for_skill(*args, **kwargs):
        return _UnexpectedTool()

    async def fake_get_capability_by_skill_id(skill_id):
        return capability

    monkeypatch.setattr(
        agent_module,
        "find_tool_for_skill",
        fake_find_tool_for_skill,
    )
    monkeypatch.setattr(
        agent_module,
        "get_capability_cache",
        lambda: SimpleNamespace(get_capability_by_skill_id=fake_get_capability_by_skill_id),
    )
    monkeypatch.setattr(agent_module, "store_status_update", lambda *args, **kwargs: None)

    result = asyncio.run(
        agent_module.invoke_skill(
            "analyze_thermal",
            {"material_id": "SS316"},
            "conv-1",
        )
    )

    assert result["missing_required_params"] == ["context.temperature_c"]


def test_ask_followup_dynamic_uses_pending_subagent_request() -> None:
    state = {
        "conversation_history": [],
        "pending_subagent_requests": [
            {
                "skill_id": "analyze_thermal",
                "missing_inputs": [
                    {
                        "name": "temperature_c",
                        "description": "Operating temperature in Celsius at which the material should be evaluated.",
                        "user_prompt": "What operating temperature should I use for the thermal analysis (in Celsius)?",
                        "type": "number",
                        "resolvable_from_context": True,
                    }
                ],
                "hint": "Thermal analysis requires an operating temperature before it can proceed.",
            },
        ],
    }

    result = asyncio.run(agent_module.ask_followup_dynamic(state))

    question = result["conversation_history"][-1]["questions"][0]
    assert question["field"] == "temperature_c"
    assert question["type"] == "number"
    assert result["missing_info"] == ["temperature_c"]
