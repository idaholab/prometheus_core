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

"""Tests for ``AdkPrometheusAgent``: skill-to-node mapping and its A2A events.

Each request goes through the agent's real executor with a recording event queue. The
runner is the agent's own test-mode runner (in-memory sessions), with its artifact service
replaced by ``DeepLynxArtifactService`` over an in-memory DeepLynx fake, so a node's
``ctx.save_artifact`` emits a real ``deeplynx://`` artifact reference through the bridge.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent
from google.adk.agents import Context
from google.adk.runners import Runner
from google.adk.workflow import START, BaseNode, FunctionNode, Workflow
from google.genai import types

from prometheus_api.adk import artifacts
from prometheus_api.adk.agent import AdkPrometheusAgent
from prometheus_api.adk.artifacts import DeepLynxArtifactService
from prometheus_api.adk.plugins import provenance
from prometheus_api.adk.plugins.bridge import A2ABridgePlugin
from prometheus_api.adk.plugins.provenance import ProvenancePlugin
from prometheus_api.agent import PrometheusAgent
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item, ItemCreate, ItemUpdate

ORG_ID = 1
PROJECT_ID = 2
ARTIFACT_URI_PREFIX = f"deeplynx://organizations/{ORG_ID}/projects/{PROJECT_ID}/items/"


class _DeepLynx:
    """In-memory DeepLynx items: execution records and uploaded artifacts."""

    def __init__(self) -> None:
        self.items: dict[int, Item] = {}
        self.next_id = 1

    def store(self, name: str, properties: dict[str, Any]) -> Item:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        item = Item(
            id=self.next_id, name=name, properties=properties, created_at=now, updated_at=now
        )
        self.items[item.id] = item
        self.next_id += 1
        return item


class _FakeFiles:
    def __init__(self, dl: _DeepLynx) -> None:
        self._dl = dl

    async def upload_bytes(
        self, data: bytes, name: str, description: str | None = None
    ) -> FileMetadata:
        item = self._dl.store(name, {})
        return FileMetadata(id=item.id, name=name, size=len(data))


class _FakeItems:
    def __init__(self, dl: _DeepLynx) -> None:
        self._dl = dl

    async def get(self, item_id: int) -> Item:
        return self._dl.items[item_id]

    async def update(self, item_id: int, update: ItemUpdate) -> Item:
        current = self._dl.items[item_id]
        updated = current.model_copy(update={"properties": dict(update.properties or {})})
        self._dl.items[item_id] = updated
        return updated

    async def create(self, item: ItemCreate) -> Item:
        return self._dl.store(item.name, dict(item.properties))

    async def add_tags(self, item_id: int, tags: list[str]) -> None:
        return None


class _FakeSearch:
    def __init__(self, dl: _DeepLynx) -> None:
        self._dl = dl

    async def advanced_query(
        self,
        filters: list[dict[str, Any]],
        project_ids: list[int],
        text_search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Any:
        wanted = json.loads(filters[0]["json"])
        matches = [
            item
            for item in self._dl.items.values()
            if all(item.properties.get(k) == v for k, v in wanted.items())
        ]
        return SimpleNamespace(items=matches, page_info=SimpleNamespace(has_next=False))


class _FakeRelationships:
    async def bulk_create(self, relationships: list[Any]) -> list[Any]:
        return []

    async def get_item_relationships(self, item_id: int) -> list[Any]:
        return []


def _fake_client_class(dl: _DeepLynx) -> type:
    class _FakeClient:
        """The ``AsyncStorageClient`` surface the agent, the service and the plugin use."""

        def __init__(self, config: ConnectionConfig) -> None:
            self.config = config
            self.files = _FakeFiles(dl)
            self.items = _FakeItems(dl)
            self.search = _FakeSearch(dl)
            self.relationships = _FakeRelationships()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    return _FakeClient


@pytest.fixture
def deeplynx(monkeypatch: pytest.MonkeyPatch) -> _DeepLynx:
    """Fake DeepLynx for the execution record, the artifact service and provenance."""
    dl = _DeepLynx()

    async def get_credential(self: Any, resource: str, scope: Any = None) -> Any:
        assert resource == "deeplynx"
        return SimpleNamespace(
            value={"org_id": ORG_ID, "project_id": PROJECT_ID, "key": "k", "secret": "s"}
        )

    async def fake_deeplynx_config(agent: Any, user_id: str) -> ConnectionConfig:
        return ConnectionConfig(organization_id=ORG_ID, project_id=PROJECT_ID, jwt_token="t")

    monkeypatch.setattr(PrometheusAgent, "get_credential", get_credential)
    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", _fake_client_class(dl))
    for module in (artifacts, provenance):
        monkeypatch.setattr(module, "deeplynx_config", fake_deeplynx_config)
        monkeypatch.setattr(module, "AsyncStorageClient", _fake_client_class(dl))
    return dl


class _RecordingQueue:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


def _write_card(path: Path, skill_ids: list[str]) -> None:
    payload = {
        "name": "ADK Map Agent",
        "description": "Agent whose skills run as ADK nodes",
        "version": "1.0.0",
        "capabilities": {"streaming": True},
        "skills": [
            {"id": skill_id, "name": skill_id, "description": f"Run {skill_id}."}
            for skill_id in skill_ids
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stub_node(name: str, ran: list[str]) -> BaseNode:
    """A workflow whose one node records its run, saves an artifact and returns its name."""

    async def run(ctx: Context, node_input: Any) -> dict[str, Any]:
        ran.append(name)
        await ctx.save_artifact(f"{name}.txt", types.Part(text=f"output of {name}"))
        return {"node": name}

    return Workflow(name=f"{name}_workflow", edges=[(START, FunctionNode(func=run, name=name))])


class _MapAgent(AdkPrometheusAgent):
    compaction = None
    adk_test_mode = True

    def create_runner(
        self,
        context: RequestContext,
        root: BaseNode,
        *,
        event_queue: EventQueue,
        abort_signal: asyncio.Event,
    ) -> Runner:
        runner = super().create_runner(
            context, root, event_queue=event_queue, abort_signal=abort_signal
        )
        bridge = runner.plugin_manager.get_plugin("a2a_bridge")
        prov = runner.plugin_manager.get_plugin("prometheus_provenance")
        assert isinstance(bridge, A2ABridgePlugin)
        assert isinstance(prov, ProvenancePlugin)
        runner.artifact_service = DeepLynxArtifactService(self, bridge=bridge, provenance=prov)
        return runner


def _context(skill_id: str) -> MagicMock:
    context = MagicMock(spec=RequestContext)
    context.task_id = f"task-{skill_id}"
    context.context_id = f"context-{skill_id}"
    context.current_task = None
    context.message = Message(
        message_id=f"message-{skill_id}",
        role=Role.ROLE_USER,
        parts=[Part(text="{}")],
        context_id=context.context_id,
        metadata={"skillId": skill_id},
    )
    context.get_user_input.return_value = "{}"
    return context


async def test_adk_agent_runs_the_node_of_each_skill_and_emits_a2a_events(
    tmp_path: Path, deeplynx: _DeepLynx
) -> None:
    """Covers REQ-016-11."""
    card_path = tmp_path / "agent_card.json"
    _write_card(card_path, ["alpha", "beta"])
    ran: list[str] = []
    agent = _MapAgent(agent_name="ADK Map Agent", agent_card_path=str(card_path))
    agent.adk_agents = {"alpha": _stub_node("alpha", ran), "beta": _stub_node("beta", ran)}
    agent.load_agent_card()

    for skill_id in ("alpha", "beta"):
        queue = _RecordingQueue()
        await agent.create_executor().execute(_context(skill_id), queue)  # type: ignore[arg-type]

        statuses = [e for e in queue.events if isinstance(e, TaskStatusUpdateEvent)]
        artifact_updates = [e for e in queue.events if isinstance(e, TaskArtifactUpdateEvent)]
        assert statuses[0].status.state == TaskState.TASK_STATE_WORKING
        assert len(artifact_updates) == 1, f"{skill_id}: expected one artifactUpdate"
        artifact = artifact_updates[0].artifact
        assert artifact.name == f"{skill_id}.txt"
        assert artifact.parts[0].url.startswith(ARTIFACT_URI_PREFIX)
        final = statuses[-1]
        assert final.status.state == TaskState.TASK_STATE_COMPLETED
        assert json.loads(final.status.message.parts[0].text) == {"node": skill_id}, (
            f"skill {skill_id!r} did not run its own node"
        )

    assert ran == ["alpha", "beta"]


def test_adk_agent_card_skill_without_node_fails_at_startup(tmp_path: Path) -> None:
    """Covers REQ-016-11."""
    card_path = tmp_path / "agent_card.json"
    _write_card(card_path, ["alpha", "beta", "gamma"])
    ran: list[str] = []
    agent = _MapAgent(agent_name="ADK Map Agent", agent_card_path=str(card_path))
    agent.adk_agents = {"alpha": _stub_node("alpha", ran), "beta": _stub_node("beta", ran)}

    with pytest.raises(ValueError, match=r"card skills without an ADK node: \['gamma'\]"):
        agent.load_agent_card()
