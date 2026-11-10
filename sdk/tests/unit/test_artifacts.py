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
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.protobuf.json_format import MessageToDict

from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext
from prometheus_api.agent.artifacts import ArtifactReference, ArtifactRegistry


class _DummyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        return {"ok": True}


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
