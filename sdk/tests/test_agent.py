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

"""Tests for the agent module."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock
from starlette.applications import Starlette
from starlette.responses import JSONResponse

from prometheus_api.agent import (
    AgentEndpoint,
    DelegatingPrometheusAgentExecutor,
    MissingInput,
    PrometheusAgent,
    PrometheusAgentExecutor,
    PrometheusWorker,
    RequestContext,
    EventQueue,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    UserIdentity,
)
from prometheus_api.agent.registry import AgentRegistryClient
from prometheus_api.llm_client import AsyncLLMClient, LLMConfig
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Artifact, Part, Task
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value


@pytest.fixture
def execution_storage(monkeypatch):
    """Provide a successful in-memory DeepLynx execution-record client."""
    created = []

    class FakeItems:
        async def create(self, item):
            created.append(item)
            return SimpleNamespace(id=len(created))

    class FakeStorageClient:
        def __init__(self, config):
            self.config = config
            self.items = FakeItems()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def get_credential(self, resource, scope=None):
        assert resource == "deeplynx"
        return SimpleNamespace(
            value={
                "org_id": 1,
                "project_id": 2,
                "key": "key",
                "secret": "secret",
            }
        )

    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", FakeStorageClient)
    monkeypatch.setattr(PrometheusAgent, "get_credential", get_credential)
    return created


def _test_agent_card() -> AgentCard:
    return AgentCard(
        name="Test Agent",
        description="Agent card used by tests",
        supported_interfaces=[
            AgentInterface(
                url="http://test-agent:8000",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="test_skill",
                name="Test Skill",
                description="Skill used by tests",
                tags=["test"],
            )
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
    )


class TestPrometheusAgentExecutor:
    """Tests for PrometheusAgentExecutor."""

    @pytest.fixture
    def executor(self):
        """Create a test executor."""
        return PrometheusAgentExecutor(agent_name="TestAgent")

    @pytest.fixture
    def mock_context(self):
        """Create a mock RequestContext."""
        context = MagicMock(spec=RequestContext)
        context.task_id = "test-task-123"
        context.context_id = "test-context-456"
        context.current_task = None
        context.message = None
        context.get_user_input.return_value = '{"input": "test data"}'
        return context

    @pytest.fixture
    def mock_event_queue(self):
        """Create a mock EventQueue."""
        queue = AsyncMock(spec=EventQueue)
        return queue

    def test_executor_initialization(self, executor):
        """Test executor initializes with correct name."""
        assert executor.agent_name == "TestAgent"

    def test_extract_params_json(self, executor):
        """Test parameter extraction from JSON input."""
        context = MagicMock(spec=RequestContext)
        context.get_user_input.return_value = '{"key": "value", "number": 42}'

        params = executor._extract_params(context)

        assert params == {"key": "value", "number": 42}

    def test_extract_params_empty(self, executor):
        """Test parameter extraction with empty input."""
        context = MagicMock(spec=RequestContext)
        context.get_user_input.return_value = ""

        params = executor._extract_params(context)

        assert params == {}

    def test_extract_params_plain_text(self, executor):
        """Test parameter extraction with non-JSON text."""
        context = MagicMock(spec=RequestContext)
        context.get_user_input.return_value = "Hello, this is plain text"

        params = executor._extract_params(context)

        assert params == {"message": "Hello, this is plain text"}

    def test_extract_params_wraps_json_non_objects(self, executor):
        """JSON values that are not objects should still produce a params dict."""
        context = MagicMock(spec=RequestContext)
        context.get_user_input.return_value = '["alpha", "beta"]'

        params = executor._extract_params(context)

        assert params == {"value": ["alpha", "beta"]}

    def test_extract_params_logs_keys_without_values(self, executor, caplog):
        """Parameter logging should not expose prompt or credential values."""
        context = MagicMock(spec=RequestContext)
        context.get_user_input.return_value = json.dumps(
            {
                "prompt": "sensitive prompt text",
                "llm_api_key": "secret-key",
            }
        )

        with caplog.at_level(logging.INFO):
            params = executor._extract_params(context)

        assert params["llm_api_key"] == "secret-key"
        assert "llm_api_key" in caplog.text
        assert "secret-key" not in caplog.text
        assert "sensitive prompt text" not in caplog.text

    def test_extract_params_without_message_context(self, executor):
        """_extract_params should tolerate local/debug contexts without .message."""

        class LocalLikeContext:
            def get_user_input(self):
                return '{"skill_id": "demo_skill", "message": "hello"}'

        params = executor._extract_params(LocalLikeContext())

        assert params == {"skill_id": "demo_skill", "message": "hello"}

    def test_execute_calls_enqueue_event(self, executor, mock_context, mock_event_queue):
        """Test that execute uses enqueue_event for status updates."""

        # Create a concrete implementation for testing
        class TestExecutor(PrometheusAgentExecutor):
            async def _execute(self, params, context, event_queue):
                return {"status": "success", "data": params.get("input")}

        test_executor = TestExecutor(agent_name="TestAgent")

        asyncio.run(test_executor.execute(mock_context, mock_event_queue))

        # Verify enqueue_event was called (not put)
        assert mock_event_queue.enqueue_event.called
        calls = mock_event_queue.enqueue_event.call_args_list

        # A2A v1 requires the Task first, followed by working and completed updates.
        assert len(calls) == 3

        initial_task = calls[0][0][0]
        assert isinstance(initial_task, Task)
        assert initial_task.id == "test-task-123"
        assert initial_task.status.state == TaskState.TASK_STATE_SUBMITTED

        # Check the next call is working status
        first_event = calls[1][0][0]
        assert isinstance(first_event, TaskStatusUpdateEvent)
        assert first_event.status.state == TaskState.TASK_STATE_WORKING
        assert first_event.task_id == "test-task-123"
        assert first_event.context_id == "test-context-456"

        # Check second call is completed status with the final response payload
        second_event = calls[2][0][0]
        assert isinstance(second_event, TaskStatusUpdateEvent)
        assert second_event.status.state == TaskState.TASK_STATE_COMPLETED
        payload_text = second_event.status.message.parts[0].text
        assert json.loads(payload_text) == {"status": "success", "data": "test data"}

    def test_execute_emits_heartbeats_during_long_execute(self, mock_context, monkeypatch):
        """A slow _execute should produce periodic non-final keepalive events."""
        monkeypatch.setenv("PROMETHEUS_HEARTBEAT_INTERVAL", "0.01")

        events: list = []

        class RecordingQueue:
            async def enqueue_event(self, event):
                events.append(event)

        def _heartbeats():
            return [
                e
                for e in events
                if isinstance(e, TaskStatusUpdateEvent)
                and MessageToDict(e.metadata).get("heartbeat")
            ]

        class SlowExecutor(PrometheusAgentExecutor):
            async def _execute(self, params, context, event_queue):
                # Wait until at least one keepalive has been emitted, then finish.
                for _ in range(500):
                    if _heartbeats():
                        break
                    await asyncio.sleep(0.01)
                return {"status": "success"}

        asyncio.run(SlowExecutor(agent_name="HB").execute(mock_context, RecordingQueue()))

        heartbeats = _heartbeats()
        assert heartbeats, "expected at least one heartbeat keepalive event"
        for hb in heartbeats:
            assert hb.status.state == TaskState.TASK_STATE_WORKING
            assert not hb.status.HasField("message")  # silent: no UI text

        # The terminal event is the completed status, emitted after heartbeats stop.
        assert isinstance(events[-1], TaskStatusUpdateEvent)
        assert events[-1].status.state == TaskState.TASK_STATE_COMPLETED
        assert not MessageToDict(events[-1].metadata).get("heartbeat")

    def test_heartbeat_interval_rejects_invalid_values(self, monkeypatch):
        """A non-positive or non-numeric PROMETHEUS_HEARTBEAT_INTERVAL is rejected
        (fail-fast) instead of silently defaulting or disabling the keepalive.
        Heartbeats cannot be turned off, so 0/negative are invalid."""
        for bad in ("0", "-5", "abc"):
            monkeypatch.setenv("PROMETHEUS_HEARTBEAT_INTERVAL", bad)
            with pytest.raises(ValueError):
                PrometheusAgentExecutor._heartbeat_interval()

    def test_heartbeat_interval_defaults_to_15(self, monkeypatch):
        """With the env var unset the interval falls back to the 15 s default."""
        monkeypatch.delenv("PROMETHEUS_HEARTBEAT_INTERVAL", raising=False)
        assert PrometheusAgentExecutor._heartbeat_interval() == 15.0

    def test_execute_handles_errors(self, executor, mock_context, mock_event_queue):
        """Test that execute sends failed status on error."""

        class FailingExecutor(PrometheusAgentExecutor):
            async def _execute(self, params, context, event_queue):
                raise ValueError("Test error")

        test_executor = FailingExecutor(agent_name="TestAgent")

        with pytest.raises(ValueError, match="Test error"):
            asyncio.run(test_executor.execute(mock_context, mock_event_queue))

        # Should have sent working status, then failed status
        calls = mock_event_queue.enqueue_event.call_args_list
        assert len(calls) >= 2

        # Last call should be failed status
        last_event = calls[-1][0][0]
        assert isinstance(last_event, TaskStatusUpdateEvent)
        assert last_event.status.state == TaskState.TASK_STATE_FAILED

    def test_execute_skips_auto_finalization_when_agent_finalizes(
        self, mock_context, mock_event_queue
    ):
        """If _execute emits final status, executor should not emit extra terminal events."""

        class FinalizingExecutor(PrometheusAgentExecutor):
            async def _execute(self, params, context, event_queue):
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        task_id=context.task_id,
                        context_id=context.context_id,
                        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
                    )
                )
                return {"status": "handled-by-agent"}

        test_executor = FinalizingExecutor(agent_name="TestAgent")
        asyncio.run(test_executor.execute(mock_context, mock_event_queue))

        calls = mock_event_queue.enqueue_event.call_args_list
        assert len(calls) == 3

        assert isinstance(calls[0][0][0], Task)
        first_event = calls[1][0][0]
        assert isinstance(first_event, TaskStatusUpdateEvent)
        assert first_event.status.state == TaskState.TASK_STATE_WORKING

        second_event = calls[2][0][0]
        assert isinstance(second_event, TaskStatusUpdateEvent)
        assert second_event.status.state == TaskState.TASK_STATE_COMPLETED

    def test_execute_allows_streamed_artifacts_without_adding_extra_result_artifact(
        self, mock_context, mock_event_queue
    ):
        """If _execute emits artifacts, executor should still finalize via status.message only."""

        class ArtifactStreamingExecutor(PrometheusAgentExecutor):
            async def _execute(self, params, context, event_queue):
                await event_queue.enqueue_event(
                    TaskArtifactUpdateEvent(
                        task_id=context.task_id,
                        context_id=context.context_id,
                        artifact=Artifact(
                            artifact_id="streamed-artifact",
                            name="progress",
                            parts=[Part(text='{"partial": true}')],
                        ),
                    )
                )
                return {"status": "done"}

        test_executor = ArtifactStreamingExecutor(agent_name="TestAgent")
        asyncio.run(test_executor.execute(mock_context, mock_event_queue))

        calls = mock_event_queue.enqueue_event.call_args_list
        artifact_events = [
            call[0][0] for call in calls if type(call[0][0]).__name__ == "TaskArtifactUpdateEvent"
        ]
        completed_events = [
            call[0][0]
            for call in calls
            if isinstance(call[0][0], TaskStatusUpdateEvent)
            and call[0][0].status.state == TaskState.TASK_STATE_COMPLETED
        ]

        assert len(artifact_events) == 1
        assert artifact_events[0].artifact.artifact_id == "streamed-artifact"
        assert len(completed_events) == 1
        payload_text = completed_events[0].status.message.parts[0].text
        assert json.loads(payload_text) == {"status": "done"}

    def test_cancel_sends_canceled_status(self, executor, mock_context, mock_event_queue):
        """Test that cancel sends canceled status."""
        asyncio.run(executor.cancel(mock_context, mock_event_queue))

        mock_event_queue.enqueue_event.assert_called_once()
        event = mock_event_queue.enqueue_event.call_args[0][0]

        assert isinstance(event, TaskStatusUpdateEvent)
        assert event.status.state == TaskState.TASK_STATE_CANCELED
        assert event.task_id == "test-task-123"
        assert event.context_id == "test-context-456"

    def test__execute_not_implemented(self, executor, mock_context, mock_event_queue):
        """Test that base executor raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            asyncio.run(executor._execute({}, mock_context, mock_event_queue))


class TestPrometheusAgent:
    """Tests for PrometheusAgent."""

    @staticmethod
    def _write_agent_card(path, *, workflows=None):
        payload = {
            "name": "Workflow Agent",
            "description": "Agent with workflow metadata",
            "version": "1.0.0",
            "capabilities": {"streaming": False},
            "skills": [
                {
                    "id": "analyze_thermal",
                    "name": "Analyze Thermal",
                    "description": "Run thermal analysis.",
                }
            ],
        }
        if workflows is not None:
            payload["workflows"] = workflows
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_agent_initialization(self):
        """Test agent initializes with default values."""
        agent = PrometheusAgent(agent_name="MyAgent")

        assert agent.agent_name == "MyAgent"
        assert agent.agent_card_path == "agent_card.json"
        assert agent.agent_card is None
        assert agent.executor is None

    def test_agent_custom_card_path(self):
        """Test agent accepts custom card path."""
        agent = PrometheusAgent(agent_name="MyAgent", agent_card_path="/custom/path/card.json")

        assert agent.agent_card_path == "/custom/path/card.json"

    def test_registry_url_defaults_and_strips_env(self, monkeypatch):
        """Test registry URL helper centralizes env lookup and the default value."""
        monkeypatch.delenv("REGISTRY_URL", raising=False)
        assert PrometheusAgent.registry_url() == "http://litellm:4000"

        monkeypatch.setenv("REGISTRY_URL", " http://registry:4000 ")
        assert PrometheusAgent.registry_url() == "http://registry:4000"

    def test_register_with_registry_retries_fallback_url_without_registry_url(self, monkeypatch):
        """Unset REGISTRY_URL still retries the built-in LiteLLM service fallback."""
        agent = PrometheusAgent(agent_name="MyAgent")
        attempts = []
        sleep_delays = []

        class DummyAgentCard:
            name = "My Agent"

        def fail_then_succeed(self, agent_card, *, raw_agent_card=None):
            attempts.append((self.registry_url, self.headers))
            if len(attempts) < 3:
                raise RuntimeError("registry unavailable")

        monkeypatch.delenv("REGISTRY_URL", raising=False)
        monkeypatch.delenv("REGISTRY_MAX_RETRIES", raising=False)
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        monkeypatch.setattr(AgentRegistryClient, "register_once", fail_then_succeed)
        monkeypatch.setattr("prometheus_api.agent.registry.time.sleep", sleep_delays.append)

        agent.register_with_registry(DummyAgentCard())

        assert attempts == [
            ("http://litellm:4000", {}),
            ("http://litellm:4000", {}),
            ("http://litellm:4000", {}),
        ]
        assert sleep_delays == [2.0, 4.0]

    def test_register_with_registry_retries_configured_registry(self, monkeypatch):
        """Explicit registry configuration should use the configured retry count."""
        agent = PrometheusAgent(agent_name="MyAgent")
        attempts = []
        sleep_delays = []

        class DummyAgentCard:
            name = "My Agent"

        def fail_registration(self, agent_card, *, raw_agent_card=None):
            attempts.append((self.registry_url, dict(self.headers)))
            raise RuntimeError("registry unavailable")

        monkeypatch.setenv("REGISTRY_URL", " http://registry:4000 ")
        monkeypatch.setenv("REGISTRY_MAX_RETRIES", "2")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "master-key")
        monkeypatch.setattr(AgentRegistryClient, "register_once", fail_registration)
        monkeypatch.setattr("prometheus_api.agent.registry.time.sleep", sleep_delays.append)

        agent.register_with_registry(
            DummyAgentCard(),
            initial_delay=0.5,
            max_delay=0.75,
            backoff_factor=2.0,
        )

        assert attempts == [
            ("http://registry:4000", {"Authorization": "Bearer master-key"}),
            ("http://registry:4000", {"Authorization": "Bearer master-key"}),
            ("http://registry:4000", {"Authorization": "Bearer master-key"}),
        ]
        assert sleep_delays == [0.5, 0.75]

    def test_register_with_registry_ignores_invalid_retry_env(self, monkeypatch, caplog):
        """Bad REGISTRY_MAX_RETRIES should not prevent agent startup."""
        agent = PrometheusAgent(agent_name="MyAgent")
        attempts = []
        sleep_delays = []

        class DummyAgentCard:
            name = "My Agent"

        def fail_then_succeed(self, agent_card, *, raw_agent_card=None):
            attempts.append(self.registry_url)
            if len(attempts) < 3:
                raise RuntimeError("registry unavailable")

        monkeypatch.delenv("REGISTRY_URL", raising=False)
        monkeypatch.setenv("REGISTRY_MAX_RETRIES", "not-an-int")
        monkeypatch.setattr(AgentRegistryClient, "register_once", fail_then_succeed)
        monkeypatch.setattr("prometheus_api.agent.registry.time.sleep", sleep_delays.append)

        with caplog.at_level(logging.WARNING):
            agent.register_with_registry(DummyAgentCard())

        assert attempts == [
            "http://litellm:4000",
            "http://litellm:4000",
            "http://litellm:4000",
        ]
        assert sleep_delays == [2.0, 4.0]
        assert "Invalid REGISTRY_MAX_RETRIES='not-an-int'; using 10" in caplog.text

    def test_registry_client_build_payload_adds_litellm_v1_routing_fields(self):
        """Registry payload keeps extensions plus LiteLLM's upstream routing fields."""
        raw_agent_card = {
            "name": "Test Agent",
            "description": "Raw card",
            "skills": [{"id": "extra", "usage_notes": "Preserved for routing"}],
        }
        client = AgentRegistryClient(
            "http://registry:4000",
            agent_secret="agent-secret",
        )

        agent_name, payload = client.build_payload(
            _test_agent_card(),
            raw_agent_card=raw_agent_card,
        )

        assert agent_name == "test-agent"
        assert payload["agent_card_params"]["skills"] == raw_agent_card["skills"]
        assert payload["agent_card_params"]["url"] == "http://test-agent:8000"
        assert payload["agent_card_params"]["protocolVersion"] == "1.0"
        assert "url" not in raw_agent_card
        assert "protocolVersion" not in raw_agent_card
        assert payload["static_headers"] == {"Authorization": "Bearer agent-secret"}

    def test_get_raw_agent_card_returns_loaded_dict(self):
        agent = PrometheusAgent(agent_name="MyAgent")
        agent.agent_card_dict = {
            "name": "My Agent",
            "skills": [
                {
                    "id": "analyze_thermal",
                    "inputSchema": {"type": "object", "required": ["material_id"]},
                }
            ],
        }

        assert agent.get_raw_agent_card()["skills"][0]["inputSchema"]["required"] == ["material_id"]

    def test_load_agent_card_normalizes_raw_card_for_a2a_validation(self, tmp_path, monkeypatch):
        """Served raw cards should remain valid for strict A2A clients."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(card_path)
        monkeypatch.setenv("EXTERNAL_AGENT_URL", "http://workflow-agent:8000")

        agent = PrometheusAgent(agent_name="Workflow Agent", agent_card_path=str(card_path))
        agent.load_agent_card()

        raw_card = agent.get_raw_agent_card()
        assert raw_card["defaultInputModes"] == ["text"]
        assert raw_card["defaultOutputModes"] == ["text"]
        assert raw_card["skills"][0].get("tags", []) == []
        assert raw_card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        ParseDict(raw_card, AgentCard(), ignore_unknown_fields=True)

    def test_load_agent_card_inserts_default_workflows_directory(self, tmp_path, monkeypatch):
        """Workflow files next to agent_card.json should be inserted into the raw card."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(card_path)
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
        (workflows_dir / "quick_check.yaml").write_text(
            """
id: thermal_agent.quick_check
name: Quick Thermal Check
version: "1.0.0"
description: Run a quick thermal analysis.
steps:
  - id: analyze
    skill_id: analyze_thermal
""",
            encoding="utf-8",
        )
        monkeypatch.delenv("AGENT_WORKFLOWS", raising=False)
        monkeypatch.setenv("EXTERNAL_AGENT_URL", "http://workflow-agent:8000")

        agent = PrometheusAgent(agent_name="Workflow Agent", agent_card_path=str(card_path))
        agent_card = agent.load_agent_card()

        assert agent_card.name == "Workflow Agent"
        assert (
            agent.get_raw_agent_card()["supportedInterfaces"][0]["url"]
            == "http://workflow-agent:8000"
        )
        assert agent.get_raw_agent_card()["workflows"] == [
            {
                "id": "thermal_agent.quick_check",
                "name": "Quick Thermal Check",
                "version": "1.0.0",
                "description": "Run a quick thermal analysis.",
                "steps": [{"id": "analyze", "skill_id": "analyze_thermal"}],
            }
        ]

    def test_load_agent_card_uses_agent_workflows_env_relative_to_card(self, tmp_path, monkeypatch):
        """AGENT_WORKFLOWS should customize the directory and preserve explicit card workflows."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(
            card_path,
            workflows=[
                {
                    "id": "card.workflow",
                    "name": "Card Workflow",
                    "version": "1.0.0",
                    "description": "Declared directly in the card.",
                    "steps": [{"id": "card_step", "skill_id": "analyze_thermal"}],
                }
            ],
        )
        custom_dir = tmp_path / "custom-workflows"
        custom_dir.mkdir()
        (custom_dir / "from_file.json").write_text(
            json.dumps(
                {
                    "id": "file.workflow",
                    "name": "File Workflow",
                    "version": "1.0.0",
                    "description": "Loaded from a workflow file.",
                    "steps": [{"id": "file_step", "skill_id": "analyze_thermal"}],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("AGENT_WORKFLOWS", "custom-workflows")

        agent = PrometheusAgent(agent_name="Workflow Agent", agent_card_path=str(card_path))
        agent.load_agent_card()

        assert [workflow["id"] for workflow in agent.get_raw_agent_card()["workflows"]] == [
            "card.workflow",
            "file.workflow",
        ]

    def test_load_agent_card_ignores_missing_workflows_directory(self, tmp_path, monkeypatch):
        """Agents without workflow files should keep the existing card payload."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(card_path)
        monkeypatch.delenv("AGENT_WORKFLOWS", raising=False)

        agent = PrometheusAgent(agent_name="Workflow Agent", agent_card_path=str(card_path))
        agent.load_agent_card()

        assert "workflows" not in agent.get_raw_agent_card()

    async def test_agent_card_routes_serve_inserted_workflows(self, tmp_path, monkeypatch):
        """Agent-card endpoints should include workflows loaded from files."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(card_path)
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()
        (workflows_dir / "catalog.yaml").write_text(
            """
workflows:
  - id: catalog.workflow
    name: Catalog Workflow
    version: "1.0.0"
    description: Loaded from a workflows wrapper.
    steps:
      - id: analyze
        skill_id: analyze_thermal
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("AGENT_SECRET_REQUIRED", "false")
        monkeypatch.delenv("AGENT_WORKFLOWS", raising=False)

        agent = PrometheusAgent(agent_name="Workflow Agent", agent_card_path=str(card_path))
        app = agent.build_app(register_on_startup=False)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            raw_response = await client.get("/api/agent-card")
            assert raw_response.status_code == 200
            raw_payload = raw_response.json()
            assert raw_payload["workflows"][0]["id"] == "catalog.workflow"

            for path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
                response = await client.get(path)
                assert response.status_code == 200
                payload = response.json()
                assert payload["defaultInputModes"] == ["text"]
                assert payload["defaultOutputModes"] == ["text"]
                assert payload["skills"][0].get("tags", []) == []
                assert "workflows" not in payload
                ParseDict(payload, AgentCard())

    def test_llm_client_helper_inherits_agent_name_and_ignores_request_keys(self):
        """Covers REQ-007-15 and BEH-007-01."""
        agent = PrometheusAgent(agent_name="Trace Agent")
        context = MagicMock(spec=RequestContext)
        context.message.parts = [
            Part(
                data=ParseDict(
                    {
                        "provided_inputs": {"llm_api_key": "request-key"},
                        "llm_api_key": "request-key",
                    },
                    Value(),
                )
            )
        ]

        client = agent.llm_client(context, config=LLMConfig(proxy_url="http://proxy"))

        assert isinstance(client, AsyncLLMClient)
        assert client.config.app_name == "Trace Agent"
        assert client.config.api_key is None

    def test_default_lifespan_is_a_no_op(self):
        agent = PrometheusAgent(agent_name="MyAgent")

        async def run_lifespan():
            async with agent.lifespan(app=None):
                return "ok"

        assert asyncio.run(run_lifespan()) == "ok"

    def test_custom_lifespan_runs_startup_and_shutdown(self):
        events = []

        class TestAgent(PrometheusAgent):
            @asynccontextmanager
            async def lifespan(self, app):
                events.append(("startup", app))
                try:
                    yield
                finally:
                    events.append(("shutdown", app))

        agent = TestAgent(agent_name="MyAgent")
        sentinel_app = object()

        async def run_lifespan():
            async with agent.lifespan(sentinel_app):
                events.append(("running", sentinel_app))

        asyncio.run(run_lifespan())

        assert events == [
            ("startup", sentinel_app),
            ("running", sentinel_app),
            ("shutdown", sentinel_app),
        ]

    def test_application_lifespan_starts_background_registration(self):
        events = []

        class TestAgent(PrometheusAgent):
            @asynccontextmanager
            async def lifespan(self, app):
                events.append("startup")
                try:
                    yield
                finally:
                    events.append("shutdown")

            async def register_with_registry_async(self, agent_card, **kwargs):
                events.append(("register", agent_card.name))

        agent = TestAgent(agent_name="MyAgent")
        app = SimpleNamespace(state=SimpleNamespace())
        agent_card = _test_agent_card()

        async def run_lifespan():
            async with agent._application_lifespan(
                app,
                agent_card,
                register_on_startup=True,
            ):
                events.append("running")
                await asyncio.sleep(0)

        asyncio.run(run_lifespan())

        assert events == ["startup", "running", ("register", "Test Agent"), "shutdown"]
        assert app.state.registry_registration_task.done()

    def test_configure_auth_requires_secret_by_default(self, monkeypatch):
        agent = PrometheusAgent(agent_name="MyAgent")
        app = Starlette()
        monkeypatch.delenv("AGENT_SECRET", raising=False)
        monkeypatch.delenv("AGENT_SECRET_REQUIRED", raising=False)

        with pytest.raises(RuntimeError, match="AGENT_SECRET_REQUIRED=true"):
            agent._configure_auth(app)

    def test_configure_auth_can_be_disabled(self, monkeypatch):
        agent = PrometheusAgent(agent_name="MyAgent")
        app = Starlette()
        monkeypatch.delenv("AGENT_SECRET", raising=False)
        monkeypatch.setenv("AGENT_SECRET_REQUIRED", "false")

        agent._configure_auth(app)

        assert app.user_middleware == []

    def test_build_app_sets_components_and_routes_without_registration(self, monkeypatch):
        class TestAgent(PrometheusAgent):
            async def _execute(self, params, context, event_queue):
                return {"ok": True}

        agent = TestAgent(agent_name="MyAgent")
        agent_card = _test_agent_card()
        monkeypatch.setattr(agent, "load_agent_card", lambda: agent_card)
        monkeypatch.setenv("AGENT_SECRET_REQUIRED", "false")

        app = agent.build_app(register_on_startup=False)

        assert agent.agent_card is agent_card
        assert isinstance(agent.executor, PrometheusAgentExecutor)
        route_paths = {getattr(route, "path", None) for route in app.routes}
        assert "/healthz" in route_paths
        assert "/health" not in route_paths
        assert "/api/chat" in route_paths
        assert "/api/agent-card" in route_paths

    async def test_build_app_health_paths_skip_auth(self, monkeypatch):
        """REQ-008-07, REQ-008-10: /healthz answers without a token; /health is gone."""

        class TestAgent(PrometheusAgent):
            async def _execute(self, params, context, event_queue):
                return {"ok": True}

        agent = TestAgent(agent_name="MyAgent")
        monkeypatch.setattr(agent, "load_agent_card", _test_agent_card)
        monkeypatch.setenv("AGENT_SECRET", "secret")
        monkeypatch.setenv("AGENT_SECRET_REQUIRED", "true")
        app = agent.build_app(register_on_startup=False)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/healthz")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"
            # The old /health route was removed, not left as an unauthenticated alias
            assert (await client.get("/health")).status_code == 401
            # A non-exempt route still needs the token
            assert (await client.post("/", json={})).status_code == 401

    async def test_build_app_debug_chat_route_executes_agent(self, monkeypatch, execution_storage):
        class TestAgent(PrometheusAgent):
            async def _execute(self, params, context, event_queue):
                return {
                    "message": params.get("message"),
                    "context_id": context.context_id,
                }

        agent = TestAgent(agent_name="MyAgent")
        monkeypatch.setattr(agent, "load_agent_card", _test_agent_card)
        monkeypatch.setenv("AGENT_SECRET_REQUIRED", "false")
        app = agent.build_app(register_on_startup=False)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/chat",
                json={
                    "params": {"message": "hello"},
                    "conversation_id": "conv-1",
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["context_id"] == "conv-1"
        assert payload["result"] == {"message": "hello", "context_id": "conv-1"}

    async def test_add_http_endpoint_registers_authenticated_route_and_card_metadata(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Custom HTTP endpoints should inherit auth and appear in the raw card."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(card_path)

        class TestAgent(PrometheusAgent):
            def __init__(self):
                super().__init__(agent_name="Endpoint Agent", agent_card_path=str(card_path))
                endpoint = self.add_http_endpoint(
                    "/api/custom-status",
                    self.custom_status,
                    methods=["GET"],
                    endpoint_id="custom_status",
                    purpose="debug",
                    description="Return custom status for tests.",
                    content_types=["application/json"],
                )
                assert isinstance(endpoint, AgentEndpoint)

            async def custom_status(self, request):
                return JSONResponse({"ok": True, "agent": self.agent_name})

            async def _execute(self, params, context, event_queue):
                return {"ok": True}

        monkeypatch.setenv("AGENT_SECRET", "agent-secret")
        monkeypatch.delenv("AGENT_SECRET_REQUIRED", raising=False)

        agent = TestAgent()
        app = agent.build_app(register_on_startup=False)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.get("/api/custom-status")
            authenticated = await client.get(
                "/api/custom-status",
                headers={"Authorization": "Bearer agent-secret"},
            )
            card_response = await client.get("/api/agent-card")

        assert unauthenticated.status_code == 401
        assert authenticated.status_code == 200
        assert authenticated.json() == {"ok": True, "agent": "Endpoint Agent"}
        assert card_response.status_code == 200
        endpoint_metadata = card_response.json()["endpoints"][0]
        assert endpoint_metadata == {
            "id": "custom_status",
            "path": "/api/custom-status",
            "methods": ["GET"],
            "purpose": "debug",
            "auth_required": True,
            "description": "Return custom status for tests.",
            "content_types": ["application/json"],
        }

    async def test_add_static_endpoint_serves_authenticated_assets_and_card_metadata(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Static endpoints should resolve relative to agent_card.json and use auth."""
        card_path = tmp_path / "agent_card.json"
        self._write_agent_card(card_path)
        assets_dir = tmp_path / "viewer-assets"
        assets_dir.mkdir()
        (assets_dir / "plugin.js").write_text("export const plugin = true;\n", encoding="utf-8")

        class TestAgent(PrometheusAgent):
            def __init__(self):
                super().__init__(agent_name="Static Agent", agent_card_path=str(card_path))
                self.add_static_endpoint(
                    "/viewer",
                    "viewer-assets",
                    endpoint_id="viewer_assets",
                    purpose="viewer_plugin",
                    description="Serve custom viewer assets.",
                    content_types=["text/javascript"],
                )

            async def _execute(self, params, context, event_queue):
                return {"ok": True}

        monkeypatch.setenv("AGENT_SECRET", "agent-secret")
        monkeypatch.delenv("AGENT_SECRET_REQUIRED", raising=False)

        agent = TestAgent()
        app = agent.build_app(register_on_startup=False)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.get("/viewer/plugin.js")
            authenticated = await client.get(
                "/viewer/plugin.js",
                headers={"Authorization": "Bearer agent-secret"},
            )
            card_response = await client.get("/api/agent-card")

        assert unauthenticated.status_code == 401
        assert authenticated.status_code == 200
        assert "export const plugin = true;" in authenticated.text
        endpoint_metadata = card_response.json()["endpoints"][0]
        assert endpoint_metadata == {
            "id": "viewer_assets",
            "path": "/viewer",
            "methods": ["GET", "HEAD"],
            "purpose": "viewer_plugin",
            "auth_required": True,
            "description": "Serve custom viewer assets.",
            "content_types": ["text/javascript"],
        }

    def test_agent__execute_not_implemented(self):
        """Test that base agent raises NotImplementedError for _execute."""
        agent = PrometheusAgent(agent_name="MyAgent")

        mock_context = MagicMock(spec=RequestContext)
        mock_queue = AsyncMock(spec=EventQueue)

        with pytest.raises(NotImplementedError):
            asyncio.run(agent._execute({}, mock_context, mock_queue))

    def test_send_input_required_emits_canonical_data_part(self):
        """Test INPUT_REQUIRED helper emits a final status with structured payload."""
        agent = PrometheusAgent(agent_name="MyAgent")
        context = MagicMock(spec=RequestContext)
        context.task_id = "task-1"
        context.context_id = "ctx-1"
        queue = AsyncMock(spec=EventQueue)

        asyncio.run(
            agent.send_input_required(
                context=context,
                event_queue=queue,
                missing_inputs=[
                    MissingInput(
                        name="temperature_c",
                        description="Operating temperature in Celsius.",
                        user_prompt="What operating temperature should I use?",
                        type="number",
                        resolvable_from_context=True,
                    )
                ],
                hint="Thermal analysis requires a temperature.",
            )
        )

        queue.enqueue_event.assert_called_once()
        event = queue.enqueue_event.call_args[0][0]
        assert isinstance(event, TaskStatusUpdateEvent)
        assert event.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        part = event.status.message.parts[0]
        assert part.WhichOneof("content") == "data"
        data = MessageToDict(part.data)
        assert data["hint"] == "Thermal analysis requires a temperature."
        assert data["missing_inputs"][0]["name"] == "temperature_c"

    def test_create_executor_returns_delegating_executor(self):
        """Test that create_executor returns the standard delegating executor."""

        class TestAgent(PrometheusAgent):
            async def _execute(self, params, context, event_queue):
                return {"result": "test"}

        agent = TestAgent(agent_name="TestAgent")
        executor = agent.create_executor()

        assert isinstance(executor, DelegatingPrometheusAgentExecutor)
        assert isinstance(executor, PrometheusAgentExecutor)
        assert executor.agent_name == "TestAgent"

    def test_execution_record_payload_precedes_work_and_is_request_scoped(self, monkeypatch):
        """Covers REQ-009-16 through REQ-009-19 and BEH-009-04/05."""
        timeline = []
        observed = {}

        class Items:
            async def create(self, item):
                timeline.append("record")
                observed["item"] = item
                return SimpleNamespace(id=73)

        class Client:
            def __init__(self, config):
                observed["config"] = config
                self.items = Items()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class Queue:
            async def enqueue_event(self, event):
                if (
                    isinstance(event, TaskStatusUpdateEvent)
                    and event.status.state == TaskState.TASK_STATE_WORKING
                ):
                    timeline.append("working")

        class Agent(PrometheusAgent):
            async def get_credential(self, resource, scope=None):
                timeline.append("credential")
                assert resource == "deeplynx"
                return SimpleNamespace(
                    value={
                        "org_id": 11,
                        "project_id": 22,
                        "key": "jit-key",
                        "secret": "jit-secret",
                    }
                )

            async def _execute(self, params, context, event_queue):
                timeline.append("execute")
                observed["params"] = params
                observed["record_id"] = self.execution_record_id
                return {"ok": True}

        monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", Client)
        monkeypatch.setattr(
            PrometheusAgentExecutor,
            "_extract_identity",
            lambda self, context: UserIdentity(
                user_id="verified-user",
                claims={},
                raw_token="verified-token",
            ),
        )
        agent = Agent(agent_name="Record Agent")
        context = MagicMock(spec=RequestContext)
        context.task_id = "task-9"
        context.context_id = "context-8"
        context.current_task = None
        context.message = None
        context.get_user_input.return_value = json.dumps(
            {
                "user_id": "forged-user",
                "prompt": "token=hidden",
                "api_key": "also-hidden",
                "nested": {"password": "hidden-too"},
                "artifacts": [
                    {
                        "artifact_id": "svg-1",
                        "metadata": {"source": {"name": "hi.svg"}},
                    }
                ],
            }
        )

        asyncio.run(agent.create_executor().execute(context, Queue()))

        assert timeline[:4] == ["credential", "record", "working", "execute"]
        assert observed["record_id"] == 73
        assert agent.execution_record_id is None
        assert observed["params"]["user_id"] == "verified-user"
        item = observed["item"]
        assert item.name == f"Record Agent execution {item.properties['created_at']}"
        assert item.original_id == "prometheus-execution:record-agent:task-9"
        assert item.tags == ["execution"]
        assert item.properties["schema"] == "prometheus.execution_record.v1"
        assert item.properties["agent_name"] == "Record Agent"
        assert item.properties["producer_agent_id"] == "record-agent"
        assert item.properties["authenticated_user_id"] == "verified-user"
        assert item.properties["task_id"] == "task-9"
        assert item.properties["context_id"] == "context-8"
        assert "parameters" not in item.properties
        parameters = json.loads(item.properties["parameters_json"])
        assert parameters["user_id"] == "verified-user"
        assert parameters["api_key"] == "[REDACTED]"
        assert parameters["nested"]["password"] == "[REDACTED]"
        assert "token=[REDACTED]" in parameters["prompt"]
        assert parameters["artifacts"][0]["metadata"]["source"]["name"] == "hi.svg"
        assert observed["params"]["nested"]["password"] == "hidden-too"
        assert observed["params"]["artifacts"][0]["metadata"]["source"]["name"] == "hi.svg"
        assert all(not isinstance(value, (dict, list)) for value in item.properties.values())
        assert item.properties["created_at"].endswith("+00:00")
        assert observed["config"].organization_id == 11

    async def test_execution_record_name_is_less_than_500_characters(self, execution_storage):
        class Agent(PrometheusAgent):
            async def _execute(self, params, context, event_queue):
                return {"ok": True}

        agent = Agent(agent_name="A" * 600)
        context = MagicMock(spec=RequestContext)
        context.task_id = "task-long-name"
        context.context_id = "context-long-name"
        context.current_task = None
        context.message = None
        context.get_user_input.return_value = "{}"

        await agent.create_executor().execute(context, AsyncMock(spec=EventQueue))

        item = execution_storage[0]
        assert len(item.name) == 499
        assert item.name.endswith(f" execution {item.properties['created_at']}")

    def test_execution_record_failure_prevents_work_and_execute(self, monkeypatch):
        """Covers REQ-009-20 and BEH-009-07."""
        worked = False

        class Agent(PrometheusAgent):
            async def get_credential(self, resource, scope=None):
                raise RuntimeError("credential unavailable")

            async def _execute(self, params, context, event_queue):
                nonlocal worked
                worked = True
                return {"ok": True}

        context = MagicMock(spec=RequestContext)
        context.task_id = "task-fail"
        context.context_id = "context-fail"
        context.current_task = None
        context.message = None
        context.get_user_input.return_value = "{}"
        queue = AsyncMock(spec=EventQueue)
        agent = Agent(agent_name="Fail Agent")

        with pytest.raises(RuntimeError, match="credential unavailable"):
            asyncio.run(agent.create_executor().execute(context, queue))

        assert worked is False
        states = [
            call[0][0].status.state
            for call in queue.enqueue_event.call_args_list
            if isinstance(call[0][0], TaskStatusUpdateEvent)
        ]
        assert TaskState.TASK_STATE_WORKING not in states
        assert states[-1] == TaskState.TASK_STATE_FAILED
        assert agent.execution_record_id is None

    async def test_execution_record_context_is_concurrency_safe(self, monkeypatch):
        """Covers REQ-009-21 and BEH-009-06."""
        entered = asyncio.Event()
        release = asyncio.Event()

        class Items:
            async def create(self, item):
                item_id = 101 if item.properties["task_id"] == "task-a" else 202
                return SimpleNamespace(id=item_id)

        class Client:
            def __init__(self, config):
                self.items = Items()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        seen = {}

        class Agent(PrometheusAgent):
            async def get_credential(self, resource, scope=None):
                return SimpleNamespace(
                    value={"org_id": 1, "project_id": 2, "key": "k", "secret": "s"}
                )

            async def _execute(self, params, context, event_queue):
                seen[context.task_id] = self.execution_record_id
                if context.task_id == "task-a":
                    entered.set()
                    await release.wait()
                else:
                    await entered.wait()
                    release.set()
                assert self.execution_record_id == seen[context.task_id]
                return {"ok": True}

        monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", Client)
        agent = Agent(agent_name="Concurrent Agent")

        def make_context(task_id):
            context = MagicMock(spec=RequestContext)
            context.task_id = task_id
            context.context_id = f"context-{task_id}"
            context.current_task = None
            context.message = None
            context.get_user_input.return_value = "{}"
            return context

        await asyncio.gather(
            agent.create_executor().execute(make_context("task-a"), AsyncMock(spec=EventQueue)),
            agent.create_executor().execute(make_context("task-b"), AsyncMock(spec=EventQueue)),
        )

        assert seen == {"task-a": 101, "task-b": 202}
        assert agent.execution_record_id is None


class TestEventTypes:
    """Tests for A2A event type creation."""

    def test_task_status_update_event_creation(self):
        """Test creating TaskStatusUpdateEvent."""
        event = TaskStatusUpdateEvent(
            task_id="task-123",
            context_id="context-456",
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
        )

        assert event.task_id == "task-123"
        assert event.context_id == "context-456"
        assert event.status.state == TaskState.TASK_STATE_WORKING

    def test_task_status_states(self):
        """Test all task states are accessible."""
        states = [
            TaskState.TASK_STATE_SUBMITTED,
            TaskState.TASK_STATE_WORKING,
            TaskState.TASK_STATE_COMPLETED,
            TaskState.TASK_STATE_CANCELED,
            TaskState.TASK_STATE_FAILED,
        ]

        for state in states:
            status = TaskStatus(state=state)
            assert status.state == state


class TestAgentIntegration:
    """Integration tests for agent components."""

    def test_full_execution_flow(self, execution_storage):
        """Test complete execution flow with a concrete agent."""

        class EchoAgent(PrometheusAgent):
            async def _execute(self, params, context, event_queue):
                # Echo the input back
                return {
                    "echo": params.get("message", "no message"),
                    "task_id": context.task_id,
                }

        agent = EchoAgent(agent_name="EchoAgent")
        executor = agent.create_executor()

        # Create mock context and queue
        context = MagicMock(spec=RequestContext)
        context.task_id = "echo-task-1"
        context.context_id = "echo-context-1"
        context.current_task = None
        context.message = None
        context.get_user_input.return_value = '{"message": "Hello, World!"}'

        queue = AsyncMock(spec=EventQueue)

        # Execute
        asyncio.run(executor.execute(context, queue))

        # Verify the flow
        calls = queue.enqueue_event.call_args_list

        assert isinstance(calls[0][0][0], Task)

        # Working status
        assert calls[1][0][0].status.state == TaskState.TASK_STATE_WORKING

        # Completed status with canonical final payload
        assert calls[2][0][0].status.state == TaskState.TASK_STATE_COMPLETED
        text_content = calls[2][0][0].status.message.parts[0].text
        result = json.loads(text_content)
        assert result["echo"] == "Hello, World!"
        assert result["task_id"] == "echo-task-1"


class TestPrometheusWorker:
    """Tests for PrometheusWorker + PrometheusAgent.run_worker."""

    def _agent(self):
        return PrometheusAgent(agent_name="Worker Agent")

    def _context(self):
        ctx = MagicMock(spec=RequestContext)
        ctx.task_id = "task-1"
        ctx.context_id = "conv-1"
        return ctx

    class _RecordingQueue:
        def __init__(self):
            self.events = []

        async def enqueue_event(self, event):
            self.events.append(event)

    def test_run_worker_forwards_events_and_returns_result(self):
        """Events a worker emits (status updates and JSON artifacts) are forwarded
        to the A2A event queue in order, and run_worker returns the worker's
        run() result. Status updates are non-final; the artifact carries its
        payload as a data part."""
        queue_ = self._RecordingQueue()

        class DemoWorker(PrometheusWorker):
            def run(self):
                self.emit_status_update("step 1")
                self.emit_json_artifact({"k": 1}, name="partial", json_type="demo.v1")
                self.emit_status_update("step 2")
                return {"status": "success", "n": 2}

        agent = self._agent()
        worker = DemoWorker()
        result = asyncio.run(agent.run_worker(worker, self._context(), queue_, poll_interval=0.01))

        assert result == {"status": "success", "n": 2}
        kinds = [type(e).__name__ for e in queue_.events]
        assert kinds == [
            "TaskStatusUpdateEvent",
            "TaskArtifactUpdateEvent",
            "TaskStatusUpdateEvent",
        ]
        # Status text is preserved and non-final (the base executor finalizes).
        assert queue_.events[0].status.message.parts[0].text == "step 1"
        # The JSON artifact carries the payload as a data part.
        artifact = queue_.events[1].artifact
        assert artifact.name == "partial"
        assert MessageToDict(artifact.parts[0].data) == {"k": 1.0}

    def test_run_worker_propagates_worker_exception(self):
        """An exception raised in worker.run() propagates out of run_worker (so the
        base executor still emits a failed status) rather than being swallowed."""
        queue_ = self._RecordingQueue()

        class BoomWorker(PrometheusWorker):
            def run(self):
                raise RuntimeError("boom")

        agent = self._agent()
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(agent.run_worker(BoomWorker(), self._context(), queue_, poll_interval=0.01))

    def test_run_worker_cancellation_signals_worker_cooperatively(self):
        """Cancelling the run_worker task sets the worker's cancel flag so a
        cooperative worker (one that checks self.cancelled) stops, instead of
        being abandoned -- threads cannot be force-killed."""
        import time as _time

        queue_ = self._RecordingQueue()

        class LoopWorker(PrometheusWorker):
            def run(self):
                while not self.cancelled:
                    _time.sleep(0.01)
                return {"status": "cancelled"}

        agent = self._agent()
        worker = LoopWorker()

        async def go():
            task = asyncio.create_task(
                agent.run_worker(worker, self._context(), queue_, poll_interval=0.01)
            )
            await asyncio.sleep(0.05)  # let the worker start
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(go())
        assert worker.cancelled is True

    def test_emit_before_bind_raises(self):
        """Emitting from a worker that hasn't been bound to a request (i.e. not
        run via run_worker) raises a clear error instead of failing obscurely."""
        worker = PrometheusWorker()
        with pytest.raises(RuntimeError, match="not bound"):
            worker.emit_status_update("nope")


class TestDeclareLongRunning:
    """Tests for PrometheusAgent.declare_long_running (proactive detach signal)."""

    def _context(self):
        ctx = MagicMock(spec=RequestContext)
        ctx.task_id = "task-1"
        ctx.context_id = "conv-1"
        return ctx

    class _RecordingQueue:
        def __init__(self):
            self.events = []

        async def enqueue_event(self, event):
            self.events.append(event)

    def test_emits_nonfinal_working_with_background_metadata(self):
        agent = PrometheusAgent(agent_name="Long Agent")
        queue_ = self._RecordingQueue()
        asyncio.run(agent.declare_long_running(self._context(), queue_, estimate_seconds=120))
        assert len(queue_.events) == 1
        event = queue_.events[0]
        assert event.status.state == TaskState.TASK_STATE_WORKING
        assert event.metadata["background"] is True
        assert event.metadata["estimate_seconds"] == 120.0
        # A default message naming the estimate is emitted.
        assert "120" in event.status.message.parts[0].text

    def test_custom_message_and_extra_metadata_merge(self):
        agent = PrometheusAgent(agent_name="Long Agent")
        queue_ = self._RecordingQueue()
        asyncio.run(
            agent.declare_long_running(
                self._context(),
                queue_,
                message="custom",
                metadata={"job_kind": "sim"},
            )
        )
        event = queue_.events[0]
        assert event.metadata["background"] is True
        assert event.metadata["job_kind"] == "sim"
        assert "estimate_seconds" not in event.metadata
        assert event.status.message.parts[0].text == "custom"
