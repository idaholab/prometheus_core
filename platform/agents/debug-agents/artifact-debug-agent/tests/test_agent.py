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

"""Tests for the Artifact Debug agent.

The first test builds the server, which catches a broken agent_card.json or
workflow file; the rest run `_execute` through each skill's LangGraph graph with
a scripted model that calls the skill's tool and an in-memory DeepLynx fake.
The SVG and PNG skills save through `save_artifact`; the JSON skill stays inline.
Run with `uv run pytest`.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from langgraph.checkpoint.memory import InMemorySaver
from prometheus_api.agent import artifacts as agent_artifacts
from prometheus_api.langgraph import LangGraphPrometheusAgent, artifacts
from prometheus_api.llm_client import AsyncLLMClient, ChatResponse
from prometheus_api.llm_client.tools import ToolCall
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item, ItemUpdate
from prometheus_api.storage_client.models.pagination import Page, PageInfo

from agent import ArtifactDebugAgent

AGENT_DIR = Path(__file__).resolve().parents[1]
ORG_ID = 7
PROJECT_ID = 11
CONVERSATION_ID = "conv-artifacts"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png"
SAVED_RESULT_KEYS = {
    "status",
    "conversation_id",
    "message",
    "artifact",
    "artifact_id",
    "artifact_name",
    "artifact_uri",
    "uri",
    "version",
}


def _make_agent() -> ArtifactDebugAgent:
    # agent_card.json is loaded lazily by run()/build_app(), not by the
    # constructor, so unit tests can instantiate the agent directly. A relative
    # path resolves against the running script, which under pytest isn't this
    # directory, so pass the card's absolute path.
    return ArtifactDebugAgent(agent_name="Artifact Debug Agent", agent_card_path=str(AGENT_DIR / "agent_card.json"))


class _ScriptedClient(AsyncLLMClient):
    """`AsyncLLMClient` stand-in: calls the one bound tool with the request params, then answers.

    Like a real model, it sends only the params that the tool schema declares.
    """

    def __init__(self) -> None:
        # No config: the fake never reaches a provider.
        self.called_tools: list[str] = []

    async def chat(self, text_or_messages, model=None, trace_tags=None, **kwargs):  # type: ignore[override]
        if any(m.get("role") == "tool" for m in text_or_messages):
            return ChatResponse("Done.", "small", "resolved", None, {}, (), "stop")
        (bound,) = kwargs["tools"]
        name = bound["function"]["name"]
        self.called_tools.append(name)
        declared = bound["function"]["parameters"].get("properties") or {}
        user = next(m for m in text_or_messages if m.get("role") == "user")
        arguments = {k: v for k, v in json.loads(user["content"]).items() if k in declared}
        call = ToolCall(id=f"call_{name}", name=name, arguments=arguments)
        return ChatResponse("", "small", "resolved", None, {}, (call,), "tool_calls")

    async def aclose(self) -> None:
        return None


class _FakeDeepLynx:
    """In-memory `AsyncStorageClient` stand-in: one item per upload, property search, download."""

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.store: dict[int, Item] = {}
        self.data: dict[int, bytes] = {}
        self.downloaded_ids: list[int] = []
        self._next_id = 100
        self.search = MagicMock(advanced_query=AsyncMock(side_effect=self._advanced_query))
        self.files = MagicMock(
            upload_bytes=AsyncMock(side_effect=self._upload_bytes),
            download=AsyncMock(side_effect=self._download),
        )
        self.items = MagicMock(get=AsyncMock(side_effect=self._get), update=AsyncMock(side_effect=self._update))

    async def __aenter__(self) -> _FakeDeepLynx:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def _advanced_query(
        self, filters: list[dict[str, Any]], project_ids: list[int], page: int, page_size: int
    ) -> Page[Item]:
        ((name, value),) = json.loads(filters[0]["json"]).items()
        hits = [item for item in self.store.values() if item.properties.get(name) == value]
        return Page(
            items=hits,
            page_info=PageInfo(
                page_number=page, page_size=page_size, total_count=len(hits), has_next=False, has_previous=False
            ),
        )

    async def _upload_bytes(self, data: bytes, name: str) -> FileMetadata:
        item_id = self._next_id
        self._next_id += 1
        now = datetime.now(timezone.utc)
        self.store[item_id] = Item(id=item_id, name=name, properties={}, created_at=now, updated_at=now)
        self.data[item_id] = data
        return FileMetadata(id=item_id, name=name, size=len(data))

    async def _download(self, item_id: int, output_path: Path) -> None:
        self.downloaded_ids.append(item_id)
        output_path.write_bytes(self.data[item_id])

    async def _get(self, item_id: int) -> Item:
        return self.store[item_id]

    async def _update(self, item_id: int, update: ItemUpdate) -> Item:
        changed = self.store[item_id].model_copy(update=update.model_dump(exclude_none=True))
        self.store[item_id] = changed
        return changed


class _ScriptedArtifactDebugAgent(ArtifactDebugAgent):
    """The real agent with a scripted model, an in-memory checkpointer and a DeepLynx connection."""

    def __init__(self, storage: ConnectionConfig | None) -> None:
        super().__init__(agent_name="Artifact Debug Agent", agent_card_path=str(AGENT_DIR / "agent_card.json"))
        self.client = _ScriptedClient()
        self.storage = storage
        self.checkpoint_saver = InMemorySaver()
        self.load_agent_card()

    def llm_client(self, context, **kwargs):
        return self.client

    async def storage_config(self):
        return self.storage


class _RecordingQueue:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


def _context(task_id: str) -> Any:
    return SimpleNamespace(task_id=task_id, context_id=CONVERSATION_ID)


@pytest.fixture
def config() -> ConnectionConfig:
    return ConnectionConfig(organization_id=ORG_ID, project_id=PROJECT_ID, jwt_token="test-jwt")


@pytest.fixture
def deeplynx(monkeypatch: pytest.MonkeyPatch, config: ConnectionConfig) -> _FakeDeepLynx:
    fake = _FakeDeepLynx(config)
    monkeypatch.setattr(artifacts, "open_storage", lambda _config: fake)
    return fake


@pytest.fixture
def no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each agent's artifact registry no Redis client, so it keeps references in its own memory."""
    monkeypatch.setattr(agent_artifacts, "create_redis_client", lambda *args, **kwargs: None)


@pytest.fixture
def converted_sources(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Replace the CairoSVG conversion, which needs native libcairo, and record each source SVG."""
    sources: list[bytes] = []

    def fake_convert(source_svg: Path, target_png: Path) -> str:
        sources.append(source_svg.read_bytes())
        target_png.write_bytes(PNG_BYTES)
        return "fake"

    monkeypatch.setattr(ArtifactDebugAgent, "_convert_svg_to_png", staticmethod(fake_convert))
    return sources


def _item_uri(item_id: int) -> str:
    return f"deeplynx://organizations/{ORG_ID}/projects/{PROJECT_ID}/items/{item_id}"


def _saved_item_id(result: dict[str, Any], deeplynx: _FakeDeepLynx) -> int:
    """Return the fake item that the result's `uri` names; fails when the tool saved nothing."""
    (item_id,) = [item_id for item_id in deeplynx.store if _item_uri(item_id) == result.get("uri")]
    return item_id


async def _create_svg(agent: _ScriptedArtifactDebugAgent) -> dict[str, Any]:
    params = {"skill_id": "create_svg_artifact", "word": "hello"}
    return await agent._execute(params, _context("task-svg"), _RecordingQueue())


def test_build_app_loads_agent_card():
    # Builds the server as run() would, which loads agent_card.json and any
    # workflows/, without starting it or registering with LiteLLM.
    agent = _make_agent()

    assert agent.build_app(register_on_startup=False) is not None
    assert agent.agent_card.skills


def test_cairosvg_installed():
    # agent.py imports cairosvg lazily, so check that pyproject.toml declares it
    assert importlib.util.find_spec("cairosvg") is not None


def test_agent_is_a_langgraph_agent_with_one_tool_per_card_skill():
    agent = _make_agent()
    agent.load_agent_card()

    assert issubclass(ArtifactDebugAgent, LangGraphPrometheusAgent)
    assert agent.model_alias == "small"
    assert {skill_id: [t.name for t in tools] for skill_id, tools in agent.skill_tools().items()} == {
        "create_svg_artifact": ["create_svg_artifact"],
        "convert_svg_to_png": ["convert_svg_to_png"],
        "create_json_artifact": ["create_json_artifact"],
    }


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"skill_id": "create_svg_artifact", "word": "hi"}, id="create_svg_artifact"),
        pytest.param({"skill_id": "convert_svg_to_png", "artifact_id": "missing"}, id="convert_svg_to_png"),
    ],
)
async def test_execute_without_storage_returns_deeplynx_error(params):
    # Outside an identity scope the real storage_config() finds no DeepLynx credential.
    agent = _make_agent()
    agent.load_agent_card()
    agent.checkpoint_saver = InMemorySaver()
    client = _ScriptedClient()
    agent.llm_client = lambda context, **kwargs: client

    result = await agent._execute(dict(params), _context("task-none"), _RecordingQueue())

    assert client.called_tools == [params["skill_id"]]
    assert result["status"] == "error"
    assert "DEEPLYNX_" in result["message"]


async def test_create_svg_artifact_saves_svg_and_returns_its_uri(deeplynx, config):
    agent = _ScriptedArtifactDebugAgent(config)

    result = await _create_svg(agent)

    assert agent.client.called_tools == ["create_svg_artifact"]
    assert result["status"] == "created"
    assert set(result) == SAVED_RESULT_KEYS
    item_id = _saved_item_id(result, deeplynx)
    assert result["artifact_uri"] == result["uri"]
    assert result["version"] == 0
    assert result["artifact_name"] == "hello.svg"
    assert deeplynx.store[item_id].properties["mime_type"] == "image/svg+xml"
    assert b">hello</text>" in deeplynx.data[item_id]
    reference = agent.resolve_artifact_reference(CONVERSATION_ID, result["artifact_id"])
    assert reference is not None
    assert reference.uri == result["uri"]
    assert reference.metadata["deeplynx_item_id"] == item_id


async def test_convert_svg_to_png_loads_svg_item_and_saves_png(deeplynx, config, converted_sources):
    agent = _ScriptedArtifactDebugAgent(config)
    svg = await _create_svg(agent)
    svg_item_id = _saved_item_id(svg, deeplynx)

    params = {"skill_id": "convert_svg_to_png", "artifact_id": svg["artifact_id"]}
    result = await agent._execute(params, _context("task-png"), _RecordingQueue())

    assert agent.client.called_tools == ["create_svg_artifact", "convert_svg_to_png"]
    assert deeplynx.downloaded_ids == [svg_item_id]
    assert converted_sources == [deeplynx.data[svg_item_id]]
    assert result["status"] == "converted"
    assert set(result) == SAVED_RESULT_KEYS | {"source_artifact"}
    png_item_id = _saved_item_id(result, deeplynx)
    assert png_item_id != svg_item_id
    assert result["artifact_name"] == "hello.png"
    assert deeplynx.data[png_item_id] == PNG_BYTES
    assert deeplynx.store[png_item_id].properties["mime_type"] == "image/png"
    assert result["source_artifact"]["artifact_id"] == svg["artifact_id"]


async def test_request_without_skill_id_with_artifact_id_routes_to_convert_svg_to_png(
    deeplynx, config, converted_sources
):
    agent = _ScriptedArtifactDebugAgent(config)
    svg = await _create_svg(agent)

    result = await agent._execute({"artifact_id": svg["artifact_id"]}, _context("task-routed"), _RecordingQueue())

    assert agent.client.called_tools[-1] == "convert_svg_to_png"
    assert result["status"] == "converted"
    png_item_id = _saved_item_id(result, deeplynx)
    assert deeplynx.store[png_item_id].properties["mime_type"] == "image/png"
    assert result["source_artifact"]["artifact_id"] == svg["artifact_id"]


async def test_create_json_artifact_registers_inline_json_without_deeplynx(deeplynx):
    # No storage: the inline JSON skill needs no DeepLynx connection.
    agent = _ScriptedArtifactDebugAgent(None)
    payload = {"answer": 42}

    params = {"skill_id": "create_json_artifact", "json_type": "prometheus.debug.echo.v1", "payload": payload}
    result = await agent._execute(params, _context("task-json"), _RecordingQueue())

    assert agent.client.called_tools == ["create_json_artifact"]
    assert result["status"] == "created"
    assert set(result) == {"status", "conversation_id", "message", "artifact", "artifact_id", "json_type"}
    assert result["json_type"] == "prometheus.debug.echo.v1"
    reference = agent.resolve_artifact_reference(CONVERSATION_ID, result["artifact_id"])
    assert reference is not None
    assert reference.json_type == "prometheus.debug.echo.v1"
    assert reference.json_body == payload
    assert reference.mime_type == "application/json"
    assert reference.metadata["debug"] is True
    assert result["artifact"]["json_body"] == payload
    assert deeplynx.store == {}
    deeplynx.files.upload_bytes.assert_not_called()


def _status_messages(queue: _RecordingQueue) -> list[str]:
    """Return the text of each status update that the agent enqueued."""
    return [
        part.text
        for event in queue.events
        if isinstance(event, TaskStatusUpdateEvent)
        for part in event.status.message.parts
        if part.text
    ]


def _emitted_descriptions(queue: _RecordingQueue) -> dict[str, str]:
    """Return the description of each artifact that the agent emitted, by artifact ID."""
    return {
        event.artifact.artifact_id: event.artifact.description
        for event in queue.events
        if isinstance(event, TaskArtifactUpdateEvent)
    }


async def test_create_svg_artifact_reports_description_in_status_update(deeplynx, config, no_redis):
    agent = _ScriptedArtifactDebugAgent(config)
    queue = _RecordingQueue()

    params = {"skill_id": "create_svg_artifact", "word": "hello", "description": "Greeting card"}
    result = await agent._execute(params, _context("task-described"), queue)

    assert result["status"] == "created"
    assert f"Created artifact {result['artifact_id']}: Greeting card" in _status_messages(queue)
    item = deeplynx.store[_saved_item_id(result, deeplynx)]
    assert item.description == "Greeting card"
    assert item.properties["json_type"] == "prometheus.debug.svg.v1"
    assert item.properties["word"] == "hello"
    assert _emitted_descriptions(queue)[result["artifact_id"]] == "Greeting card"
    reference = agent.resolve_artifact_reference(CONVERSATION_ID, result["artifact_id"])
    assert reference is not None
    assert reference.description == "Greeting card"
    assert reference.metadata["json_type"] == "prometheus.debug.svg.v1"


async def test_convert_svg_to_png_records_source_artifact_and_description(
    deeplynx, config, converted_sources, no_redis
):
    agent = _ScriptedArtifactDebugAgent(config)
    svg = await _create_svg(agent)
    queue = _RecordingQueue()

    params = {"skill_id": "convert_svg_to_png", "artifact_id": svg["artifact_id"], "description": "Raster greeting"}
    result = await agent._execute(params, _context("task-png-described"), queue)

    assert result["status"] == "converted"
    item = deeplynx.store[_saved_item_id(result, deeplynx)]
    assert item.properties["source_artifact_id"] == svg["artifact_id"]
    assert item.description == "Raster greeting"
    assert _emitted_descriptions(queue)[result["artifact_id"]] == "Raster greeting"


async def test_same_name_svgs_in_one_conversation_get_their_own_saved_artifact_ids(deeplynx, config, no_redis):
    agent = _ScriptedArtifactDebugAgent(config)
    params = {"skill_id": "create_svg_artifact", "word": "hello"}

    first = await agent._execute(dict(params), _context("task-first"), _RecordingQueue())
    second = await agent._execute(dict(params), _context("task-second"), _RecordingQueue())

    assert first["artifact_name"] == second["artifact_name"] == "hello.svg"
    assert first["artifact_id"] != second["artifact_id"]
    for result in (first, second):
        item = deeplynx.store[_saved_item_id(result, deeplynx)]
        assert result["artifact_id"] == item.properties["artifact_id"]
        assert result["artifact"]["artifact_id"] == result["artifact_id"]
        assert result["artifact"]["uri"] == result["uri"]

    # A restarted agent (no checkpoint) repeats the first task's tool call: save_artifact
    # returns the first item, while the newest "hello.svg" in the conversation is the second.
    restarted = _ScriptedArtifactDebugAgent(config)
    restarted.artifact_registry = agent.artifact_registry
    resumed = await restarted._execute(dict(params), _context("task-first"), _RecordingQueue())

    assert len(deeplynx.store) == 2
    assert resumed["uri"] == first["uri"]
    assert resumed["artifact_id"] == first["artifact_id"]
    assert resumed["artifact"]["artifact_id"] == first["artifact_id"]


async def test_convert_svg_to_png_resolves_registry_miss_through_artifact_catalog(
    deeplynx, config, converted_sources, no_redis
):
    svg = await _create_svg(_ScriptedArtifactDebugAgent(config))
    svg_item_id = _saved_item_id(svg, deeplynx)
    agent = _ScriptedArtifactDebugAgent(config)
    assert agent.resolve_artifact_reference(CONVERSATION_ID, svg["artifact_id"]) is None

    params = {"skill_id": "convert_svg_to_png", "artifact_id": svg["artifact_id"], "artifacts": [svg["artifact"]]}
    result = await agent._execute(params, _context("task-catalog"), _RecordingQueue())

    assert result["status"] == "converted"
    assert deeplynx.downloaded_ids == [svg_item_id]
    assert converted_sources == [deeplynx.data[svg_item_id]]
    png_item_id = _saved_item_id(result, deeplynx)
    assert png_item_id != svg_item_id
    assert deeplynx.store[png_item_id].properties["mime_type"] == "image/png"
    assert result["source_artifact"]["artifact_id"] == svg["artifact_id"]


@pytest.mark.parametrize(
    "upstream_result",
    [
        pytest.param(lambda svg: {"artifact": {"artifact_id": svg["artifact_id"]}}, id="nested-artifact"),
        pytest.param(lambda svg: {"artifact_id": svg["artifact_id"]}, id="top-level-artifact-id"),
    ],
)
async def test_convert_svg_to_png_without_artifact_id_uses_upstream_results(
    deeplynx, config, converted_sources, no_redis, upstream_result
):
    agent = _ScriptedArtifactDebugAgent(config)
    svg = await _create_svg(agent)
    svg_item_id = _saved_item_id(svg, deeplynx)

    params = {
        "skill_id": "convert_svg_to_png",
        "upstream_results": {"create_svg_artifact": upstream_result(svg)},
        "artifacts": [svg["artifact"]],
    }
    result = await agent._execute(params, _context("task-upstream"), _RecordingQueue())

    assert agent.client.called_tools == ["create_svg_artifact", "convert_svg_to_png"]
    assert result["status"] == "converted"
    assert deeplynx.downloaded_ids == [svg_item_id]
    assert result["source_artifact"]["artifact_id"] == svg["artifact_id"]
    assert deeplynx.data[_saved_item_id(result, deeplynx)] == PNG_BYTES
