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

"""Tests for artifact reference management."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.protobuf.json_format import MessageToDict

from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext
from prometheus_api.agent.artifacts import ArtifactReference, ArtifactRegistry
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item, ItemUpdate


class _DummyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        return {"ok": True}


class _FakeDeepLynx:
    """In-memory DeepLynx that records file uploads and item updates.

    ``client`` stands in for ``AsyncStorageClient``: every client it builds
    shares this one store, so a test sees the calls of all uploads in order.
    """

    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.upload_descriptions: list[str] = []
        self.item_updates: dict[int, ItemUpdate] = {}
        self._next_id = 100
        self.files = self
        self.items = _FakeDeepLynxItems(self)

    def client(self, config: ConnectionConfig) -> "_FakeDeepLynx":
        return self

    async def __aenter__(self) -> "_FakeDeepLynx":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def upload(self, file_path, *, name: str, description: str) -> FileMetadata:
        self.uploads.append(name)
        self.upload_descriptions.append(description)
        self._next_id += 1
        return FileMetadata(id=self._next_id, name=name, description=description, size=3)


class _FakeDeepLynxItems:
    def __init__(self, store: _FakeDeepLynx) -> None:
        self._store = store

    async def get(self, item_id: int) -> Item:
        now = datetime.now(timezone.utc)
        return Item(id=item_id, name="uploaded", created_at=now, updated_at=now)

    async def update(self, item_id: int, update: ItemUpdate) -> Item:
        self._store.item_updates[item_id] = update
        now = datetime.now(timezone.utc)
        return Item(id=item_id, name=update.name or "", created_at=now, updated_at=now)

    async def add_tags(self, item_id: int, tags: list[str]) -> None:
        return None


@pytest.fixture
def fake_deeplynx(monkeypatch) -> _FakeDeepLynx:
    store = _FakeDeepLynx()
    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", store.client)
    return store


def _deeplynx_config() -> ConnectionConfig:
    return ConnectionConfig(organization_id=1, project_id=2, jwt_token="test-token")


def _extract_text_part(event) -> str:
    part = event.artifact.parts[0]
    if part.WhichOneof("content") == "text":
        return part.text
    raise AssertionError("Unsupported artifact part structure")


def _extract_data_part(event):
    part = event.artifact.parts[0]
    if part.WhichOneof("content") == "data":
        return MessageToDict(part.data)
    raise AssertionError("Unsupported data part structure")


def _extract_file_part(event):
    part = event.artifact.parts[0]
    if part.WhichOneof("content") == "url":
        return part
    raise AssertionError("Unsupported file part structure")


def test_artifact_registry_conversation_scoping():
    registry = ArtifactRegistry(redis_url="redis://localhost:0", ttl_seconds=60)

    ref_a = ArtifactReference(
        artifact_id="a-id",
        conversation_id="conv-a",
        name="CAD Model",
        description="primary model",
        uri="file:///tmp/model.step",
    )
    ref_b = ArtifactReference(
        artifact_id="b-id",
        conversation_id="conv-b",
        name="Mesh",
        description="generated mesh",
        uri="file:///tmp/model.msh",
    )

    registry.register(ref_a)
    registry.register(ref_b)

    assert registry.resolve_by_id("conv-a", "a-id") is not None
    assert registry.resolve_by_id("conv-b", "a-id") is None
    assert registry.resolve_by_name("conv-a", "cad model").artifact_id == "a-id"
    assert len(registry.list("conv-a")) == 1
    assert len(registry.list("conv-b")) == 1


def test_send_json_artifact_does_not_auto_register_uri_payloads():
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-1"
    context.context_id = "conv-auto"
    queue = AsyncMock(spec=EventQueue)

    payload = {
        "name": "CAD Model",
        "description": "Rotor CAD output",
        "uri": "file:///tmp/rotor.step",
        "mime_type": "model/step",
    }

    asyncio.run(
        agent.send_json_artifact(
            context=context,
            event_queue=queue,
            payload=payload,
            name="artifact",
        )
    )

    registered = agent.resolve_artifact_by_name("conv-auto", "cad model")
    assert registered is None

    event = queue.enqueue_event.call_args[0][0]
    payload = _extract_data_part(event)
    assert payload == {
        "name": "CAD Model",
        "description": "Rotor CAD output",
        "uri": "file:///tmp/rotor.step",
        "mime_type": "model/step",
    }


def test_send_json_artifact_catalogs_inline_json_artifact():
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-json"
    context.context_id = "conv-json"
    queue = AsyncMock(spec=EventQueue)

    payload = {"hello": "world"}

    artifact_id = asyncio.run(
        agent.send_json_artifact(
            context=context,
            event_queue=queue,
            payload=payload,
            name="Debug JSON",
            description="Inline debug payload",
            json_type="prometheus.debug.echo.v1",
            catalog_artifact=True,
        )
    )

    registered = agent.resolve_artifact_reference("conv-json", artifact_id)
    assert registered is not None
    assert registered.mime_type == "application/json"
    assert registered.json_type == "prometheus.debug.echo.v1"
    assert registered.json_body == payload

    event = queue.enqueue_event.call_args[0][0]
    assert _extract_data_part(event) == payload


def test_send_artifact_reference_registers_and_emits():
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-2"
    context.context_id = "conv-ref"
    queue = AsyncMock(spec=EventQueue)

    reference = asyncio.run(
        agent.send_artifact_reference(
            context=context,
            event_queue=queue,
            name="Mesh Output",
            description="Hex mesh generated from CAD",
            uri="deeplynx://container/file/mesh-123",
            mime_type="application/octet-stream",
        )
    )

    assert reference.conversation_id == "conv-ref"
    assert reference.name == "Mesh Output"
    resolved = agent.resolve_artifact_reference("conv-ref", reference.artifact_id)
    assert resolved is not None
    assert resolved.uri == "deeplynx://container/file/mesh-123"
    event = queue.enqueue_event.call_args[0][0]
    file_payload = _extract_file_part(event)
    assert file_payload.url == "deeplynx://container/file/mesh-123"

    from_proto = ArtifactReference.from_a2a_artifact(event.artifact)
    assert from_proto is not None
    assert from_proto.uri == "deeplynx://container/file/mesh-123"
    assert from_proto.mime_type == "application/octet-stream"


def test_artifact_reference_from_a2a_file_part():
    payload = {
        "artifactId": "artifact-1",
        "name": "Mesh Output",
        "description": "Hex mesh generated from CAD",
        "parts": [
            {
                "url": "deeplynx://container/file/mesh-123",
                "mediaType": "application/octet-stream",
                "filename": "mesh.exo",
            }
        ],
        "metadata": {
            "conversation_id": "conv-file",
            "producer_agent_id": "artifact-debug-agent",
            "created_at": "2026-03-18T00:00:00+00:00",
            "tags": ["mesh"],
        },
    }

    reference = ArtifactReference.from_a2a_artifact(payload)

    assert reference is not None
    assert reference.artifact_id == "artifact-1"
    assert reference.conversation_id == "conv-file"
    assert reference.uri == "deeplynx://container/file/mesh-123"
    assert reference.mime_type == "application/octet-stream"
    assert reference.tags == ["mesh"]


def test_artifact_reference_from_a2a_data_part():
    payload = {
        "artifactId": "artifact-2",
        "name": "Corrosion Summary",
        "description": "Inline analysis output",
        "parts": [
            {
                "data": {"material_id": "Alloy 600", "finding_count": 3},
                "metadata": {
                    "mime_type": "application/json",
                    "json_type": "prometheus.analysis.corrosion_summary.v1",
                },
            }
        ],
        "metadata": {
            "conversation_id": "conv-data",
            "producer_agent_id": "analysis-agent",
            "created_at": "2026-03-18T00:00:00+00:00",
        },
    }

    reference = ArtifactReference.from_a2a_artifact(payload)

    assert reference is not None
    assert reference.artifact_id == "artifact-2"
    assert reference.conversation_id == "conv-data"
    assert reference.mime_type == "application/json"
    assert reference.json_type == "prometheus.analysis.corrosion_summary.v1"
    assert reference.json_body == {"material_id": "Alloy 600", "finding_count": 3}


def test_artifact_reference_preserves_data_part_metadata():
    payload = {
        "artifactId": "artifact-3",
        "name": "conversation_message",
        "parts": [
            {
                "data": {"message": "Hello"},
                "metadata": {
                    "mime_type": "application/json",
                    "kind": "conversation_message",
                },
            }
        ],
        "metadata": {
            "conversation_id": "conv-data",
            "producer_agent_id": "analysis-agent",
        },
    }

    reference = ArtifactReference.from_a2a_artifact(payload)

    assert reference is not None
    assert reference.metadata["kind"] == "conversation_message"


def test_artifact_reference_from_a2a_text_part():
    payload = {
        "artifactId": "artifact-text",
        "name": "analysis.log",
        "parts": [
            {
                "text": "step 1\nstep 2\n",
                "metadata": {"mime_type": "text/plain"},
            }
        ],
        "metadata": {
            "conversation_id": "conv-text",
            "producer_agent_id": "analysis-agent",
        },
    }

    reference = ArtifactReference.from_a2a_artifact(payload)

    assert reference is not None
    assert reference.artifact_id == "artifact-text"
    assert reference.mime_type == "text/plain"
    assert reference.text_body == "step 1\nstep 2\n"


def test_get_artifact_file_path_materializes_inline_json(tmp_path):
    agent = _DummyAgent(agent_name="Test Agent")
    payload = {"b": 2, "a": 1}
    agent.artifact_registry.register(
        ArtifactReference(
            artifact_id="json-1",
            conversation_id="conv-json",
            name="result",
            description="Inline JSON",
            mime_type="application/json",
            json_body=payload,
        )
    )

    path = asyncio.run(
        agent.get_artifact_file_path(
            "json-1",
            conversation_id="conv-json",
            cache_dir=tmp_path,
        )
    )

    assert path.exists()
    assert path.suffix == ".json"
    assert json.loads(path.read_text()) == payload


def test_get_artifact_file_path_materializes_inline_text_from_catalog(tmp_path):
    agent = _DummyAgent(agent_name="Test Agent")
    catalog = [
        {
            "artifact_id": "text-1",
            "conversation_id": "conv-text",
            "name": "notes",
            "description": "Inline notes",
            "mime_type": "text/plain",
            "text_body": "hello\n",
        }
    ]

    path = asyncio.run(
        agent.get_artifact_file_path(
            "text-1",
            conversation_id="conv-text",
            artifacts=catalog,
            cache_dir=tmp_path,
        )
    )

    assert path.exists()
    assert path.suffix == ".txt"
    assert path.read_text() == "hello\n"
    assert agent.resolve_artifact_reference("conv-text", "text-1") is not None


def test_get_artifact_file_path_allows_configured_local_file_root(tmp_path):
    agent = _DummyAgent(agent_name="Test Agent")
    source_dir = tmp_path / "allowed"
    source_dir.mkdir()
    source_file = source_dir / "mesh.e"
    source_file.write_bytes(b"mesh")
    agent.artifact_registry.register(
        ArtifactReference(
            artifact_id="file-1",
            conversation_id="conv-file",
            name="mesh.e",
            description="Local mesh",
            uri=f"file://{source_file}",
            mime_type="application/octet-stream",
            size_bytes=4,
        )
    )

    path = asyncio.run(
        agent.get_artifact_file_path(
            "file-1",
            conversation_id="conv-file",
            cache_dir=tmp_path / "cache",
            allowed_file_roots=[source_dir],
        )
    )

    assert path == source_file.resolve()


def test_get_artifact_file_path_rejects_local_file_outside_allowed_roots(tmp_path):
    agent = _DummyAgent(agent_name="Test Agent")
    source_file = tmp_path / "secret.txt"
    source_file.write_text("secret")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    agent.artifact_registry.register(
        ArtifactReference(
            artifact_id="file-2",
            conversation_id="conv-file",
            name="secret.txt",
            description="Disallowed local file",
            uri=f"file://{source_file}",
        )
    )

    with pytest.raises(PermissionError):
        asyncio.run(
            agent.get_artifact_file_path(
                "file-2",
                conversation_id="conv-file",
                cache_dir=tmp_path / "cache",
                allowed_file_roots=[allowed],
            )
        )


def test_get_artifact_file_path_downloads_fsspec_uri_to_cache(tmp_path):
    import fsspec

    fs = fsspec.filesystem("memory")
    fs.pipe("source/result.txt", b"hello")

    agent = _DummyAgent(agent_name="Test Agent")
    agent.artifact_registry.register(
        ArtifactReference(
            artifact_id="remote-1",
            conversation_id="conv-remote",
            name="result.txt",
            description="Remote text",
            uri="memory://source/result.txt",
            mime_type="text/plain",
            size_bytes=5,
        )
    )

    path = asyncio.run(
        agent.get_artifact_file_path(
            "remote-1",
            conversation_id="conv-remote",
            cache_dir=tmp_path,
        )
    )

    assert path.exists()
    assert path.read_bytes() == b"hello"


async def test_deeplynx_same_name_artifacts_get_distinct_names(fake_deeplynx, tmp_path):
    """Covers REQ-010-17 and BEH-010-04."""
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-dl"
    context.context_id = "conv-dl"
    queue = AsyncMock(spec=EventQueue)
    file_path = tmp_path / "report.svg"
    file_path.write_text("<svg/>")

    references = [
        await agent.send_deeplynx_artifact(
            context=context,
            event_queue=queue,
            file_path=file_path,
            name="report.svg",
            description="Rendered report",
            storage_config=_deeplynx_config(),
            mime_type="image/svg+xml",
        )
        for _ in range(3)
    ]

    expected = ["report.svg", "report-2.svg", "report-3.svg"]
    assert fake_deeplynx.uploads == expected
    for reference, name in zip(references, expected):
        item_id = reference.metadata["deeplynx_item_id"]
        assert fake_deeplynx.item_updates[item_id].name == name
        assert reference.name == name
    assert len({reference.artifact_id for reference in references}) == 3

    for reference, name in zip(references, expected):
        resolved = agent.artifact_registry.resolve_by_name("conv-dl", name)
        assert resolved is not None, name
        assert resolved.artifact_id == reference.artifact_id

    emitted = [call.args[0].artifact.name for call in queue.enqueue_event.call_args_list]
    assert emitted == expected


class _YieldingFakeDeepLynx(_FakeDeepLynx):
    """``_FakeDeepLynx`` whose upload yields, so concurrent sends interleave."""

    async def upload(self, file_path, *, name: str, description: str) -> FileMetadata:
        await asyncio.sleep(0)
        return await super().upload(file_path, name=name, description=description)


async def test_deeplynx_concurrent_same_name_artifacts_get_distinct_names(monkeypatch, tmp_path):
    """Covers REQ-010-18."""
    store = _YieldingFakeDeepLynx()
    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", store.client)
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-dl-concurrent"
    context.context_id = "conv-dl-concurrent"
    queue = AsyncMock(spec=EventQueue)
    file_path = tmp_path / "report.svg"
    file_path.write_text("<svg/>")

    references = await asyncio.gather(
        *(
            agent.send_deeplynx_artifact(
                context=context,
                event_queue=queue,
                file_path=file_path,
                name="report.svg",
                description="Rendered report",
                storage_config=_deeplynx_config(),
                mime_type="image/svg+xml",
            )
            for _ in range(3)
        )
    )

    expected = {"report.svg", "report-2.svg", "report-3.svg"}
    assert len(store.uploads) == 3
    assert set(store.uploads) == expected
    assert {reference.name for reference in references} == expected
    for name in expected:
        assert agent.artifact_registry.resolve_by_name("conv-dl-concurrent", name) is not None
    assert agent._pending_artifact_names == set()


async def test_deeplynx_requested_name_kept_in_metadata(fake_deeplynx, tmp_path):
    """Covers REQ-010-19."""
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-dl-requested"
    context.context_id = "conv-dl-requested"
    queue = AsyncMock(spec=EventQueue)
    file_path = tmp_path / "report.svg"
    file_path.write_text("<svg/>")

    first, second = [
        await agent.send_deeplynx_artifact(
            context=context,
            event_queue=queue,
            file_path=file_path,
            name="report.svg",
            description="Rendered report",
            storage_config=_deeplynx_config(),
            mime_type="image/svg+xml",
        )
        for _ in range(2)
    ]

    first_properties = fake_deeplynx.item_updates[first.metadata["deeplynx_item_id"]].properties
    assert first.name == "report.svg"
    assert "requested_name" not in first_properties
    assert "requested_name" not in first.metadata

    second_properties = fake_deeplynx.item_updates[second.metadata["deeplynx_item_id"]].properties
    assert second.name == "report-2.svg"
    assert second_properties["requested_name"] == "report.svg"
    assert second.metadata["requested_name"] == "report.svg"


# Each case covers REQ-010-17: a list of (conversation, requested name) sends and the
# effective names the sends get, in order.
@pytest.mark.parametrize(
    ("sends", "expected"),
    [
        pytest.param(
            [("conv-a", "report.svg"), ("conv-a", "Report.svg")],
            ["report.svg", "Report-2.svg"],
            id="REQ-010-17-normalized-collision",
        ),
        pytest.param(
            [("conv-a", "notes"), ("conv-a", "notes")],
            ["notes", "notes-2"],
            id="REQ-010-17-no-extension",
        ),
        pytest.param(
            [("conv-a", "report.svg"), ("conv-b", "report.svg")],
            ["report.svg", "report.svg"],
            id="REQ-010-17-per-conversation",
        ),
        pytest.param(
            [("conv-a", "report.svg"), ("conv-a", "summary.svg")],
            ["report.svg", "summary.svg"],
            id="REQ-010-17-distinct-names",
        ),
    ],
)
async def test_deeplynx_unique_name_rules(fake_deeplynx, tmp_path, sends, expected):
    """Covers REQ-010-17."""
    agent = _DummyAgent(agent_name="Test Agent")
    queue = AsyncMock(spec=EventQueue)
    file_path = tmp_path / "artifact.bin"
    file_path.write_text("abc")

    references = []
    for conversation_id, name in sends:
        context = MagicMock(spec=RequestContext)
        context.task_id = f"task-{conversation_id}"
        context.context_id = conversation_id
        references.append(
            await agent.send_deeplynx_artifact(
                context=context,
                event_queue=queue,
                file_path=file_path,
                name=name,
                description="Rendered artifact",
                storage_config=_deeplynx_config(),
            )
        )

    assert fake_deeplynx.uploads == expected
    assert [reference.name for reference in references] == expected
    for reference, name in zip(references, expected):
        assert fake_deeplynx.item_updates[reference.metadata["deeplynx_item_id"]].name == name
    for (conversation_id, _), reference, name in zip(sends, references, expected):
        resolved = agent.artifact_registry.resolve_by_name(conversation_id, name)
        assert resolved is not None, name
        assert resolved.artifact_id == reference.artifact_id
    emitted = [call.args[0].artifact.name for call in queue.enqueue_event.call_args_list]
    assert emitted == expected


@pytest.mark.parametrize(
    ("length", "capped"),
    [
        pytest.param(600, True, id="REQ-010-20-long-capped"),
        pytest.param(250, False, id="REQ-010-20-at-limit-unchanged"),
    ],
)
async def test_deeplynx_description_capped_to_limit(fake_deeplynx, tmp_path, length, capped):
    """Covers REQ-010-20."""
    agent = _DummyAgent(agent_name="Test Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-dl-description"
    context.context_id = "conv-dl-description"
    queue = AsyncMock(spec=EventQueue)
    file_path = tmp_path / "report.svg"
    file_path.write_text("<svg/>")
    description = ("Rendered report of the reactor run. " * 20)[:length]
    assert len(description) == length

    reference = await agent.send_deeplynx_artifact(
        context=context,
        event_queue=queue,
        file_path=file_path,
        name="report.svg",
        description=description,
        storage_config=_deeplynx_config(),
        mime_type="image/svg+xml",
    )

    [uploaded_description] = fake_deeplynx.upload_descriptions
    update = fake_deeplynx.item_updates[reference.metadata["deeplynx_item_id"]]
    if capped:
        for sent in (uploaded_description, update.description):
            assert len(sent) <= 250
            assert sent.endswith("…")
            assert description.startswith(sent[:-1])
        assert update.properties["full_description"] == description
    else:
        assert uploaded_description == description
        assert update.description == description
        assert "full_description" not in update.properties

    assert reference.description == description
    resolved = agent.artifact_registry.resolve_by_name("conv-dl-description", "report.svg")
    assert resolved is not None
    assert resolved.description == description
    [call] = queue.enqueue_event.call_args_list
    assert call.args[0].artifact.description == description
