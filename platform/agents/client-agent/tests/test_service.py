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

"""Service, slash-command, upload, and skill-invocation tests for the client-agent."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)
from prometheus_api.agent import ArtifactReference

import file_upload_handler
from orchestrator import chat_flow, debug_commands, runtime, service, skills
from orchestrator.models import ConversationRequest


def _no_llm(*args, **kwargs):
    raise AssertionError("Slash commands must not invoke the LLM.")


def test_configured_max_upload_bytes_defaults_to_100_mb(monkeypatch) -> None:
    monkeypatch.delenv("PROMETHEUS_MAX_UPLOAD_BYTES", raising=False)
    assert file_upload_handler.configured_max_upload_bytes() == file_upload_handler.DEFAULT_MAX_UPLOAD_BYTES


def test_configured_max_upload_bytes_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("PROMETHEUS_MAX_UPLOAD_BYTES", "4096")
    assert file_upload_handler.configured_max_upload_bytes() == 4096


def test_configured_max_upload_bytes_rejects_invalid_env(monkeypatch) -> None:
    monkeypatch.setenv("PROMETHEUS_MAX_UPLOAD_BYTES", "-1")
    with pytest.raises(ValueError, match="PROMETHEUS_MAX_UPLOAD_BYTES must be positive"):
        file_upload_handler.configured_max_upload_bytes()

def test_runtime_status_stream_emits_store_updates(monkeypatch) -> None:
    emitted = []

    class _Redis:
        def set(self, *args, **kwargs):
            return None

        def rpush(self, *args, **kwargs):
            return None

        def ltrim(self, *args, **kwargs):
            return None

        def expire(self, *args, **kwargs):
            return None

    async def emit_status(message: str) -> None:
        emitted.append(message)

    monkeypatch.setattr(runtime, "_get_status_redis_client", lambda: _Redis())

    async def run_stream():
        with runtime.status_stream(emit_status) as tasks:
            runtime.store_status_update("conv-1", "Streaming status 1.")
            runtime.store_status_update("conv-1", "Streaming status 2.")
            await runtime.wait_for_status_stream(tasks)

    asyncio.run(run_stream())

    assert emitted == ["Streaming status 1.", "Streaming status 2."]


def test_upload_files_to_deeplynx_consumes_staged_upload(monkeypatch, tmp_path) -> None:
    stage_dir = tmp_path / "staged"
    monkeypatch.setenv("PROMETHEUS_STAGED_UPLOAD_DIR", str(stage_dir))

    upload_id = file_upload_handler.new_staged_upload_id()
    data_path, meta_path = file_upload_handler.staged_upload_paths(upload_id)
    data_path.parent.mkdir(parents=True)
    data_path.write_bytes(b"exodus bytes")
    file_upload_handler.write_staged_upload_metadata(
        upload_id,
        {
            "upload_id": upload_id,
            "name": "mesh.e",
            "mime_type": "application/x-exodus",
            "size_bytes": 12,
        },
    )
    captured = {}

    class _Agent:
        async def send_deeplynx_artifact(self, **kwargs):
            captured.update(kwargs)
            captured["bytes"] = Path(kwargs["file_path"]).read_bytes()
            return ArtifactReference(
                artifact_id="artifact-1",
                conversation_id="conv-1",
                name=kwargs["name"],
                description=kwargs["description"],
                uri="deeplynx://file/1",
                metadata={},
            )

    refs = asyncio.run(
        file_upload_handler.upload_files_to_deeplynx(
            _Agent(),
            [
                file_upload_handler.UploadedFile(
                    name="mesh.e",
                    mime_type="application/x-exodus",
                    size_bytes=12,
                    upload_id=upload_id,
                )
            ],
            {"mesh.e": "Uploaded Exodus mesh."},
            context=object(),
            event_queue=object(),
            storage_config=object(),
        )
    )

    assert refs[0].artifact_id == "artifact-1"
    assert captured["bytes"] == b"exodus bytes"
    assert captured["name"] == "mesh.e"
    assert not data_path.exists()
    assert not meta_path.exists()


def test_upload_files_to_deeplynx_rejects_staged_upload_size_mismatch(monkeypatch, tmp_path) -> None:
    stage_dir = tmp_path / "staged"
    monkeypatch.setenv("PROMETHEUS_STAGED_UPLOAD_DIR", str(stage_dir))

    upload_id = file_upload_handler.new_staged_upload_id()
    data_path, meta_path = file_upload_handler.staged_upload_paths(upload_id)
    data_path.parent.mkdir(parents=True)
    data_path.write_bytes(b"abc")
    file_upload_handler.write_staged_upload_metadata(
        upload_id,
        {
            "upload_id": upload_id,
            "name": "mesh.e",
            "mime_type": "application/x-exodus",
            "size_bytes": 3,
        },
    )

    class _Agent:
        async def send_deeplynx_artifact(self, **kwargs):
            raise AssertionError("Mismatched staged upload metadata must not be persisted.")

    refs = asyncio.run(
        file_upload_handler.upload_files_to_deeplynx(
            _Agent(),
            [
                file_upload_handler.UploadedFile(
                    name="mesh.e",
                    mime_type="application/x-exodus",
                    size_bytes=4,
                    upload_id=upload_id,
                )
            ],
            {"mesh.e": "Uploaded Exodus mesh."},
            context=object(),
            event_queue=object(),
            storage_config=object(),
        )
    )

    assert refs == []
    assert not data_path.exists()
    assert not meta_path.exists()



def test_agents_slash_command_lists_registered_agents_without_llm(monkeypatch) -> None:

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

    async def fake_refresh():
        return None

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

    monkeypatch.setattr(runtime, "create_llm", _no_llm)
    monkeypatch.setattr(debug_commands, "discover_agents", fake_discover_agents)
    monkeypatch.setattr(
        debug_commands,
        "get_capability_cache",
        lambda: SimpleNamespace(refresh=fake_refresh, get_capabilities=fake_get_capabilities),
    )
    monkeypatch.setattr(chat_flow, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        chat_flow.chat(
            ConversationRequest(query="/agents", conversation_id="conv-debug")
        )
    )

    assert response.status == "answer"
    assert "**Registered agents (1)**" in response.message
    assert "1. **Mesh Agent**" in response.message
    assert "`inspect_mesh` (Inspect Mesh)" in response.message
    assert "`convert_mesh` (Convert Mesh)" in response.message
    assert response.message_metadata["slash_command"] == "agents"
    assert [entry["agent_id"] for entry in response.message_metadata["agents"]] == ["mesh-agent"]
    assert response.message_metadata["warnings"] == []


def test_artifacts_slash_command_lists_conversation_artifacts_without_llm(monkeypatch) -> None:

    monkeypatch.setattr(runtime, "create_llm", _no_llm)
    monkeypatch.setattr(
        chat_flow,
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
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        chat_flow.chat(
            ConversationRequest(
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


def test_workflows_slash_command_lists_platform_and_agent_workflows(monkeypatch) -> None:

    catalog = [
        {
            "id": "platform.safety_check",
            "version": "1.0.0",
            "display_name": "Platform Safety Check",
            "summary": "Run the platform safety checks.",
            "category": "Safety",
            "requires_approval": True,
            "estimated_duration_seconds": 60,
            "owner": "platform-team",
            "source": "local",
        },
        {
            "id": "thermal.quick_check",
            "version": "2.1.0",
            "display_name": "Quick Thermal Check",
            "summary": "Run the agent's thermal checks.",
            "category": "Thermal",
            "requires_approval": False,
            "estimated_duration_seconds": 30,
            "owner": "thermal-agent",
            "source": "agent_card",
        },
    ]
    registry = SimpleNamespace(get_catalog=lambda: catalog)

    monkeypatch.setattr(runtime, "create_llm", _no_llm)
    monkeypatch.setattr(debug_commands, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(chat_flow, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        chat_flow.chat(
            ConversationRequest(query="/workflows", conversation_id="conv-workflows")
        )
    )

    assert response.status == "answer"
    assert "Registered workflows (2)" in response.message
    assert "Platform-owned workflows (1)" in response.message
    assert "Agent-owned workflows (1)" in response.message
    assert "Platform Safety Check (`/platform_safety_check`)" in response.message
    assert "Quick Thermal Check (`/thermal_quick_check`)" in response.message
    assert "owner: thermal-agent" in response.message
    assert response.message_metadata == {
        "slash_command": "workflows",
        "workflows": catalog,
    }


def test_help_slash_command_lists_builtin_and_workflow_commands(monkeypatch) -> None:

    registry = SimpleNamespace(
        get_catalog=lambda: [
            {
                "id": "thermal.quick_check",
                "version": "2.1.0",
                "display_name": "Quick Thermal Check",
                "summary": "Run the agent's thermal checks.",
                "category": "Thermal",
                "requires_approval": False,
                "estimated_duration_seconds": 30,
                "owner": "thermal-agent",
                "source": "agent_card",
            }
        ]
    )

    monkeypatch.setattr(runtime, "create_llm", _no_llm)
    monkeypatch.setattr(debug_commands, "get_workflow_registry", lambda: registry)
    monkeypatch.setattr(chat_flow, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

    response = asyncio.run(
        chat_flow.chat(
            ConversationRequest(query="/help", conversation_id="conv-help")
        )
    )

    assert response.status == "answer"
    assert "Available commands (7)" in response.message
    for command in ("agents", "artifacts", "forget", "help", "tasks", "workflows"):
        assert f"`/{command}`" in response.message
    assert "Workflow commands (1)" in response.message
    assert "`/thermal_quick_check`" in response.message
    assert response.message_metadata == {
        "slash_command": "help",
        "supported_commands": ["agents", "artifacts", "forget", "help", "tasks", "workflows"],
        "workflow_commands": [
            {
                "command": "thermal_quick_check",
                "workflow_id": "thermal.quick_check",
                "workflow_version": "2.1.0",
                "display_name": "Quick Thermal Check",
            }
        ],
    }




class _NullEventQueue:
    """``_execute`` sends status updates; the base class enqueues them here."""

    async def enqueue_event(self, event):
        pass


def test_execute_slash_command_skips_upload_and_lazy_refresh(monkeypatch) -> None:
    async def should_not_refresh(*args, **kwargs):
        raise AssertionError("Slash commands should not refresh tool caches before handling.")

    async def should_not_upload(*args, **kwargs):
        raise AssertionError("Slash commands should not process uploaded files.")

    monkeypatch.setattr(runtime, "_tools_cache", None)
    monkeypatch.setattr(runtime, "refresh_dynamic_components", should_not_refresh)
    monkeypatch.setattr(service.OrchestratorAgent, "_handle_uploaded_files", should_not_upload)
    monkeypatch.setattr(chat_flow, "get_conversation", lambda conversation_id: None)
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

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
    orchestrator = service.OrchestratorAgent()
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
                        "upload_id": "0" * 32,
                    }
                ],
            },
            SimpleNamespace(context_id="conv-debug"),
            _NullEventQueue(),
        )
    )

    assert payload["status"] == "answer"
    assert "diagram.svg" in payload["message"]
    assert payload["artifacts"][0]["artifact_id"] == "artifact-1"
    assert payload["new_artifacts"] == []


def test_execute_detaches_when_agent_declares_long_running(monkeypatch) -> None:
    """When a dispatched agent calls declare_long_running mid-turn (signalled via
    task_tracking.request_background), _execute detaches and returns a
    backgrounded response — even with the soft deadline disabled.

    """
    import orchestrator.service as service_mod
    import task_graph
    from orchestrator import task_tracking
    from tests.test_task_graph import _FakeRedis

    fake_redis = _FakeRedis()
    monkeypatch.setattr(task_graph, "_client", lambda: fake_redis)
    task_tracking._turn.set(None)
    task_tracking._nested_parent.set(None)

    monkeypatch.delenv("PROMETHEUS_BACKGROUND_DEADLINE_SECONDS", raising=False)  # deadline off
    monkeypatch.setattr(service_mod.runtime, "_tools_cache", [object()])  # skip lazy refresh
    monkeypatch.setattr(service_mod.runtime, "store_status_update", lambda *a, **k: None)
    monkeypatch.setattr(service_mod, "get_conversation", lambda conversation_id: None)

    async def no_upload(self, *args, **kwargs):
        return []

    monkeypatch.setattr(service_mod.OrchestratorAgent, "_handle_uploaded_files", no_upload)

    async def fake_chat(request):
        # Simulate a dispatched agent declaring itself long-running, then keep
        # working (so the race resolves on the background signal, not chat).
        task_tracking.request_background()
        await asyncio.sleep(0.05)
        return service_mod.ConversationResponse(
            conversation_id="conv-bg", status="completed", report="eventually"
        )

    monkeypatch.setattr(service_mod, "chat", fake_chat)

    captured: dict = {}

    def fake_spawn(self, chat_task, conversation_id, root_id, turn):
        captured["root_id"] = root_id
        chat_task.cancel()  # don't leave the slow task running past the test

    monkeypatch.setattr(service_mod.OrchestratorAgent, "_spawn_background_finisher", fake_spawn)

    orchestrator = service_mod.OrchestratorAgent()
    orchestrator.list_artifact_references = lambda *args, **kwargs: []

    payload = asyncio.run(
        orchestrator._execute(
            {"query": "run a long simulation", "conversation_id": "conv-bg"},
            SimpleNamespace(context_id="conv-bg"),
            _NullEventQueue(),
        )
    )

    assert payload["status"] == "backgrounded"
    assert payload["message_metadata"]["task_id"] == captured["root_id"]




def test_find_tool_for_skill_uses_runtime_tool_cache(monkeypatch) -> None:
    tool = SimpleNamespace(name="create_svg_artifact")

    monkeypatch.setattr(runtime, "_tools_cache", [tool])

    result = asyncio.run(
        skills.find_tool_for_skill(
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
        skills,
        "find_tool_for_skill",
        fake_find_tool_for_skill,
    )
    monkeypatch.setattr(
        skills,
        "get_capability_cache",
        lambda: SimpleNamespace(get_capability_by_skill_id=fake_get_capability_by_skill_id),
    )
    monkeypatch.setattr(runtime, "store_status_update", lambda *args, **kwargs: None)

    result = asyncio.run(
        skills.invoke_skill(
            "analyze_thermal",
            {"material_id": "SS316"},
            "conv-1",
        )
    )

    assert result["missing_required_params"] == ["context.temperature_c"]
