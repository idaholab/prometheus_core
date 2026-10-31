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

"""Tests for the LangGraph middleware of ``prometheus_api.langgraph.middleware``."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain.agents import create_agent
from langchain.tools import ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from prometheus_api.langgraph import artifacts
from prometheus_api.langgraph.artifacts import PrometheusContext, load_artifact, save_artifact
from prometheus_api.langgraph.middleware import ProvenanceMiddleware, summarization
from prometheus_api.llm_client import AsyncLLMClient, ChatResponse
from prometheus_api.storage_client import AsyncStorageClient, StorageClient
from prometheus_api.storage_client.auth import AsyncAuthHandler, AuthHandler
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item, ItemUpdate
from prometheus_api.storage_client.models.pagination import Page, PageInfo
from prometheus_api.storage_client.models.relationship import Relationship, RelationshipCreate

ORG_ID = 7
PROJECT_ID = 11
THREAD_ID = "thread-1"
AGENT_ID = "report-agent"
RECORD_ID = 10
INPUT_ITEM_ID = 50
INPUT_BYTES = b"input dataset"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class _FakeDeepLynx:
    """In-memory ``AsyncStorageClient`` stand-in: items, files, property search, relations.

    ``get_item_relationships`` returns the edges that earlier ``bulk_create`` calls made.
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.store: dict[int, Item] = {}
        self.files_data: dict[int, bytes] = {}
        self.updates: list[tuple[int, ItemUpdate]] = []
        self.relations: list[Relationship] = []
        self.bulk_creates: list[list[RelationshipCreate]] = []
        self._next_id = 100
        self.search = MagicMock(advanced_query=AsyncMock(side_effect=self._advanced_query))
        self.files = MagicMock(
            upload_bytes=AsyncMock(side_effect=self._upload_bytes),
            download=AsyncMock(side_effect=self._download),
        )
        self.items = MagicMock(
            get=AsyncMock(side_effect=self._get),
            update=AsyncMock(side_effect=self._update),
        )
        self.relationships = MagicMock(
            get_item_relationships=AsyncMock(side_effect=self._get_item_relationships),
            bulk_create=AsyncMock(side_effect=self._bulk_create),
        )

    async def __aenter__(self) -> _FakeDeepLynx:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def seed(self, item_id: int, name: str, properties: dict[str, Any], data: bytes = b"") -> None:
        now = datetime.now(timezone.utc)
        self.store[item_id] = Item(
            id=item_id, name=name, properties=properties, created_at=now, updated_at=now
        )
        self.files_data[item_id] = data

    def record_updates(self, record_id: int) -> list[ItemUpdate]:
        return [update for item_id, update in self.updates if item_id == record_id]

    def created_edges(self) -> list[tuple[int, int, str]]:
        return [
            (rel.from_item_id, rel.to_item_id, rel.relationship_type)
            for batch in self.bulk_creates
            for rel in batch
        ]

    async def _advanced_query(
        self, filters: list[dict[str, Any]], project_ids: list[int], page: int, page_size: int
    ) -> Page[Item]:
        (wanted,) = filters
        ((name, value),) = json.loads(wanted["json"]).items()
        hits = [item for item in self.store.values() if item.properties.get(name) == value]
        return Page(
            items=hits,
            page_info=PageInfo(
                page_number=page,
                page_size=page_size,
                total_count=len(hits),
                has_next=False,
                has_previous=False,
            ),
        )

    async def _upload_bytes(self, data: bytes, name: str) -> FileMetadata:
        item_id = self._next_id
        self._next_id += 1
        self.seed(item_id, name, {}, data)
        return FileMetadata(id=item_id, name=name, size=len(data))

    async def _download(self, file_id: int, output_path: Path) -> None:
        output_path.write_bytes(self.files_data[file_id])

    async def _get(self, item_id: int) -> Item:
        return self.store[item_id]

    async def _update(self, item_id: int, update: ItemUpdate) -> Item:
        self.updates.append((item_id, update))
        changed = self.store[item_id].model_copy(update=update.model_dump(exclude_none=True))
        self.store[item_id] = changed
        return changed

    async def _get_item_relationships(self, item_id: int) -> list[Relationship]:
        return [rel for rel in self.relations if item_id in (rel.from_item_id, rel.to_item_id)]

    async def _bulk_create(self, relationships: list[RelationshipCreate]) -> list[Relationship]:
        self.bulk_creates.append(list(relationships))
        made = [
            Relationship(id=len(self.relations) + i + 1, **rel.model_dump())
            for i, rel in enumerate(relationships)
        ]
        self.relations.extend(made)
        return made


class _ScriptedChatModel(BaseChatModel):
    """Chat model that replays one scripted ``AIMessage`` per call; ``bind_tools`` is a no-op.

    ``requests`` holds the messages of each call, in order.
    """

    script: list[AIMessage]
    calls: int = 0
    requests: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> _ScriptedChatModel:  # type: ignore[override]
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.requests.append(list(messages))
        # A fresh copy without an id, so the message reducer appends a repeated reply.
        message = self.script[self.calls].model_copy(update={"id": None})
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def _tool_call(name: str, call_id: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "id": call_id, "args": args}])


@tool
async def save_report(text: str, runtime: ToolRuntime) -> str:
    """Save *text* as the report artifact."""
    saved = await save_artifact(runtime, "report.txt", text.encode(), "text/plain")
    return saved.uri


@tool
async def load_input(item_id: int, runtime: ToolRuntime) -> str:
    """Load the input artifact *item_id*."""
    loaded = await load_artifact(runtime, item_id)
    return loaded.data.decode()


@pytest.fixture
def config() -> ConnectionConfig:
    return ConnectionConfig(organization_id=ORG_ID, project_id=PROJECT_ID, jwt_token="test-jwt")


@pytest.fixture
def deeplynx(monkeypatch: pytest.MonkeyPatch, config: ConnectionConfig) -> _FakeDeepLynx:
    """The fake DeepLynx behind every ``artifacts.open_storage`` call, with a record and input."""
    fake = _FakeDeepLynx(config)
    fake.seed(RECORD_ID, "execution-record", {"status": "running"})
    fake.seed(INPUT_ITEM_ID, "input.csv", {"filename": "input.csv"}, INPUT_BYTES)
    monkeypatch.setattr(artifacts, "open_storage", lambda _config: fake)
    return fake


@pytest.fixture
def agent() -> MagicMock:
    agent = MagicMock()
    agent._producer_agent_id = AGENT_ID
    agent.send_artifact_reference = AsyncMock()
    return agent


def _context(
    agent: MagicMock, config: ConnectionConfig | None, record_id: int | None = RECORD_ID
) -> PrometheusContext:
    return PrometheusContext(
        agent=agent,
        request=MagicMock(name="request"),
        event_queue=MagicMock(name="event_queue"),
        thread_id=THREAD_ID,
        execution_record_id=record_id,
        storage=config,
    )


async def _invoke(graph: Any, context: PrometheusContext, prompt: str) -> dict[str, Any]:
    return await graph.ainvoke(
        {"messages": [HumanMessage(prompt)]},
        config={"configurable": {"thread_id": THREAD_ID}},
        context=context,
    )


async def test_provenance_edges_written_once_and_record_closed_with_digests(
    deeplynx, agent, config
):
    """Covers REQ-017-03."""
    report_text = "secret-report-body"
    save_args = {"text": report_text}
    load_args = {"item_id": INPUT_ITEM_ID}
    # Each run saves and loads with the same tool call IDs, as a resumed run would.
    one_run = [
        _tool_call("save_report", "call_save", save_args),
        _tool_call("load_input", "call_load", load_args),
        AIMessage(content="done"),
    ]
    model = _ScriptedChatModel(script=one_run + one_run)
    graph = create_agent(
        model,
        tools=[save_report, load_input],
        middleware=[ProvenanceMiddleware()],
        context_schema=PrometheusContext,
        checkpointer=InMemorySaver(),
    )

    await _invoke(graph, _context(agent, config), "write the report")

    (saved_id,) = [item_id for item_id in deeplynx.store if item_id >= 100]
    generated = (RECORD_ID, saved_id, artifacts.GENERATED)
    input_to = (INPUT_ITEM_ID, RECORD_ID, artifacts.INPUT_TO)
    assert sorted(deeplynx.created_edges()) == sorted([generated, input_to])

    (close,) = deeplynx.record_updates(RECORD_ID)
    properties = close.properties
    assert properties["status"] == "succeeded"
    assert datetime.fromisoformat(properties["ended_at"]).tzinfo is not None
    tool_calls = properties["tool_calls"]
    assert [(call["tool"], call["tool_call_id"]) for call in tool_calls] == [
        ("save_report", "call_save"),
        ("load_input", "call_load"),
    ]
    for call in tool_calls:
        assert SHA256_HEX.match(call["arguments_sha256"])
        assert SHA256_HEX.match(call["result_sha256"])
        assert set(call) == {
            "tool",
            "tool_call_id",
            "arguments_sha256",
            "result_sha256",
            "duration_ms",
        }
    stored = json.dumps(tool_calls)
    assert report_text not in stored
    assert INPUT_BYTES.decode() not in stored
    assert '"item_id"' not in stored

    # A second run on the same thread repeats both calls and adds no duplicate edge.
    await _invoke(graph, _context(agent, config), "write the report again")

    edges = deeplynx.created_edges()
    assert edges.count(generated) == 1, "REQ-017-03: each (from, to, type) is written once"
    assert edges.count(input_to) == 1, "REQ-017-03: each (from, to, type) is written once"
    assert len(edges) == 2
    second = deeplynx.record_updates(RECORD_ID)[1:]
    assert len(second) == 1
    assert [call["tool_call_id"] for call in second[0].properties["tool_calls"]] == [
        "call_save",
        "call_load",
    ]


class _EchoSummarizerClient(AsyncLLMClient):
    """``AsyncLLMClient`` stand-in for the summary model that echoes the history it is given.

    Like a model that obeys its prompt, it copies the history only when the instruction
    above ``<messages>`` asks it to keep the ``deeplynx://`` URIs and tool call IDs;
    otherwise it answers with a summary that names neither.
    """

    def __init__(self) -> None:  # no config: the fake never reaches a provider
        self.models: list[str | None] = []

    async def chat(self, text_or_messages, model=None, trace_tags=None, **kwargs):  # type: ignore[override]
        self.models.append(model)
        (message,) = text_or_messages
        instruction, _, history = message["content"].partition("<messages>")
        if "deeplynx://" in instruction and "tool_call_id" in instruction:
            text = history
        else:
            text = "The agent saved four reports."
        return ChatResponse(text, "small", "resolved-small", None, {}, (), "stop")


PADDING = "padding " * 30
SUMMARY_URIS = [
    f"deeplynx://organizations/{ORG_ID}/projects/{PROJECT_ID}/items/{item_id}"
    for item_id in (101, 102, 103, 104)
]


def _padded_thread() -> list[BaseMessage]:
    """Four tool turns that each name one URI, then two padded turns without one."""
    messages: list[BaseMessage] = [HumanMessage("write four reports")]
    results = [f"saved {uri} {PADDING}" for uri in SUMMARY_URIS] + [PADDING, PADDING]
    for index, result in enumerate(results):
        call_id = f"call_{index}"
        messages.append(_tool_call("save_report", call_id, {"text": f"report {index}"}))
        messages.append(ToolMessage(result, tool_call_id=call_id))
    return messages


async def _run_on_thread(client: AsyncLLMClient) -> _ScriptedChatModel:
    model = _ScriptedChatModel(script=[AIMessage(content="done")])
    graph = create_agent(
        model,
        tools=[save_report],
        middleware=[summarization(client)],
        checkpointer=InMemorySaver(),
    )
    await graph.ainvoke(
        {"messages": _padded_thread()}, config={"configurable": {"thread_id": THREAD_ID}}
    )
    return model


async def test_summarization_keeps_uris_and_tool_call_ids_in_next_request(monkeypatch):
    """Covers REQ-017-05."""
    monkeypatch.setenv("LANGGRAPH_SUMMARY_TRIGGER_TOKENS", "200")
    monkeypatch.setenv("LANGGRAPH_SUMMARY_KEEP_MESSAGES", "3")
    client = _EchoSummarizerClient()

    model = await _run_on_thread(client)

    assert client.models == ["small"]
    (request,) = model.requests
    # The thread was compacted: the four URI turns are gone from the request as messages.
    assert len(request) < len(_padded_thread())
    text = "\n".join(str(message.content) for message in request)
    for uri in SUMMARY_URIS:
        assert uri in text, f"REQ-017-05: {uri} is kept in the next model request"
    for index in range(4):
        assert f"call_{index}" in text, "REQ-017-05: the tool_call_id is kept"

    # Every kept ToolMessage follows the AIMessage that called it.
    for position, message in enumerate(request):
        if isinstance(message, ToolMessage):
            previous = request[position - 1]
            assert isinstance(previous, AIMessage)
            assert [call["id"] for call in previous.tool_calls] == [message.tool_call_id]


async def test_summarization_waits_for_the_default_trigger(monkeypatch):
    """Covers REQ-017-05."""
    monkeypatch.delenv("LANGGRAPH_SUMMARY_TRIGGER_TOKENS", raising=False)
    monkeypatch.setenv("LANGGRAPH_SUMMARY_KEEP_MESSAGES", "3")
    client = _EchoSummarizerClient()

    model = await _run_on_thread(client)

    # The thread is far below 24000 tokens, so the model sees it whole.
    assert client.models == []
    (request,) = model.requests
    assert [message.content for message in request] == [
        message.content for message in _padded_thread()
    ]


# Real DeepLynx edges, as the storage clients parse them. DeepLynx sends relationship
# ``properties`` as a JSON string, so the parsers decode it into a dict.
DEEPLYNX_URL = "https://deeplynx.test/api/v1"
EDGES_PATH = f"/api/v1/organizations/{ORG_ID}/projects/{PROJECT_ID}/records/{RECORD_ID}/edges"
OTHER_ID = 42


def _wire_config() -> ConnectionConfig:
    return ConnectionConfig(
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        base_url=DEEPLYNX_URL,
        jwt_token="test-jwt",
        data_source_id=3,
    )


def _edges_handler(properties: str, requests: list[httpx.Request]):
    """Serve outgoing edges in the short format (a list) and incoming in the full format."""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":  # edges/bulk echoes the created edges in the full format
            created = [
                {
                    "id": 90 + index,
                    "originId": edge["origin_id"],
                    "destinationId": edge["destination_id"],
                    "name": edge["name"],
                    "properties": "{}",
                }
                for index, edge in enumerate(json.loads(request.content))
            ]
            return httpx.Response(200, json=created)
        assert request.url.path == EDGES_PATH
        if request.url.params["isOrigin"] == "true":
            short = {"id": 7, "relatedRecordId": OTHER_ID, "name": "generated"}
            return httpx.Response(200, json=[{**short, "properties": properties}])
        full = {"id": 8, "originId": OTHER_ID, "destinationId": RECORD_ID, "name": "input_to"}
        return httpx.Response(200, json={"edges": [{**full, "properties": properties}]})

    return handle


def _sync_storage(handler: Any) -> StorageClient:
    # StorageClient has no transport seam, so the test wires its HTTP client the way
    # StorageClient.__enter__ does, with a MockTransport in place of the network.
    client = StorageClient(_wire_config())
    http = httpx.Client(base_url=DEEPLYNX_URL, transport=httpx.MockTransport(handler))
    client._http_client = http
    client._auth_handler = AuthHandler(client.config, http)
    return client


def _async_storage(handler: Any) -> AsyncStorageClient:
    client = AsyncStorageClient(_wire_config())
    http = httpx.AsyncClient(base_url=DEEPLYNX_URL, transport=httpx.MockTransport(handler))
    client._http_client = http
    client._auth_handler = AsyncAuthHandler(client.config, http)
    return client


STRING_PROPERTIES = [
    pytest.param("{}", {}, id="empty-json-string"),
    pytest.param('{"k": 1}', {"k": 1}, id="json-object-string"),
]


def _assert_parsed_edges(relationships: list[Relationship], expected: dict[str, Any]) -> None:
    assert [
        (rel.from_item_id, rel.to_item_id, rel.relationship_type, rel.properties)
        for rel in relationships
    ] == [
        (RECORD_ID, OTHER_ID, "generated", expected),
        (OTHER_ID, RECORD_ID, "input_to", expected),
    ]


def _assert_edge_requests(requests: list[httpx.Request]) -> None:
    assert [(r.url.path, r.url.params["isOrigin"]) for r in requests] == [
        (EDGES_PATH, "true"),
        (EDGES_PATH, "false"),
    ]


@pytest.mark.parametrize(("properties", "expected"), STRING_PROPERTIES)
def test_sync_item_relationships_decode_string_properties(properties, expected):
    """Covers REQ-003-13 and REQ-017-03."""
    requests: list[httpx.Request] = []
    client = _sync_storage(_edges_handler(properties, requests))

    relationships = client.relationships.get_item_relationships(RECORD_ID)

    _assert_edge_requests(requests)
    _assert_parsed_edges(relationships, expected)


@pytest.mark.parametrize(("properties", "expected"), STRING_PROPERTIES)
async def test_async_item_relationships_decode_string_properties(properties, expected):
    """Covers REQ-003-13 and REQ-017-03."""
    requests: list[httpx.Request] = []
    client = _async_storage(_edges_handler(properties, requests))

    relationships = await client.relationships.get_item_relationships(RECORD_ID)

    _assert_edge_requests(requests)
    _assert_parsed_edges(relationships, expected)


async def test_flush_edges_reads_string_properties_and_writes_only_new_edges(monkeypatch, agent):
    """Covers REQ-017-03."""
    requests: list[httpx.Request] = []
    client = _async_storage(_edges_handler("{}", requests))

    class _WiredStorage:
        async def __aenter__(self) -> AsyncStorageClient:
            return client

        async def __aexit__(self, *exc: Any) -> None:
            return None

    monkeypatch.setattr(artifacts, "open_storage", lambda _config: _WiredStorage())
    ctx = _context(agent, _wire_config())
    ctx.provenance.add_generated(RECORD_ID, OTHER_ID)  # already in DeepLynx
    ctx.provenance.add_generated(RECORD_ID, 101)  # new

    await ProvenanceMiddleware().flush_edges(ctx)

    (bulk,) = [r for r in requests if r.method == "POST"]
    assert json.loads(bulk.content) == [
        {"origin_id": RECORD_ID, "destination_id": 101, "name": "generated", "properties": {}}
    ]
    assert ctx.provenance.edges == []
