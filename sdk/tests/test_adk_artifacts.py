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

"""Tests for the ADK DeepLynx artifact service.

DeepLynx is a stateful fake of the ``AsyncStorageClient`` surface that the artifact service
and the real ``ProvenancePlugin`` use: it stores items, answers ``search.advanced_query`` by
property, and records every upload, update, create, delete and relation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types

from prometheus_api.adk import artifacts
from prometheus_api.adk.artifacts import ArtifactCallPlugin, DeepLynxArtifactService
from prometheus_api.adk.plugins import provenance
from prometheus_api.adk.plugins.provenance import GENERATED, ProvenancePlugin
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item, ItemCreate, ItemUpdate
from prometheus_api.storage_client.models.pagination import Page, PageInfo
from prometheus_api.storage_client.models.relationship import RelationshipCreate

APP = "artifact-test"
USER = "user-1"
SESSION = "session-1"
FILENAME = "mesh.exo"
MIME_TYPE = "application/x-exodus"
RECORD_ID = 100


class _RecordAgent:
    """The agent surface the service and the provenance plugin read."""

    execution_record_id = RECORD_ID
    _producer_agent_id = "artifact-test-agent"


class _DeepLynx:
    """In-memory DeepLynx: stored items plus a log of every write."""

    def __init__(self) -> None:
        self.items: dict[int, Item] = {}
        self.next_id = 1
        self.uploads: list[tuple[str, bytes]] = []
        self.updates: list[tuple[int, ItemUpdate]] = []
        self.creates: list[ItemCreate] = []
        self.deletes: list[int] = []
        self.edges: list[tuple[int, int, str]] = []
        self.queries: list[dict[str, Any]] = []

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
        # Yield before the item exists, as a real upload does, so that two unserialized saves
        # would both count the same versions.
        await asyncio.sleep(0)
        self._dl.uploads.append((name, data))
        item = self._dl.store(name, {})
        return FileMetadata(id=item.id, name=name, size=len(data))


class _FakeItems:
    def __init__(self, dl: _DeepLynx) -> None:
        self._dl = dl

    async def get(self, item_id: int) -> Item:
        return self._dl.items[item_id]

    async def update(self, item_id: int, update: ItemUpdate) -> Item:
        self._dl.updates.append((item_id, update))
        current = self._dl.items[item_id]
        updated = current.model_copy(update={"properties": dict(update.properties or {})})
        self._dl.items[item_id] = updated
        return updated

    async def create(self, item: ItemCreate) -> Item:
        self._dl.creates.append(item)
        return self._dl.store(item.name, dict(item.properties))

    async def delete(self, item_id: int) -> None:
        self._dl.deletes.append(item_id)
        self._dl.items.pop(item_id, None)

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
    ) -> Page[Item]:
        wanted = json.loads(filters[0]["json"])
        self._dl.queries.append(wanted)
        matches = [
            item
            for item in self._dl.items.values()
            if all(item.properties.get(k) == v for k, v in wanted.items())
        ]
        info = PageInfo(
            page_number=page,
            page_size=page_size,
            total_count=len(matches),
            has_next=False,
            has_previous=False,
        )
        return Page[Item](items=matches, page_info=info)


class _FakeRelationships:
    def __init__(self, dl: _DeepLynx) -> None:
        self._dl = dl

    async def bulk_create(self, relationships: list[RelationshipCreate]) -> list[Any]:
        for rel in relationships:
            self._dl.edges.append((rel.from_item_id, rel.to_item_id, rel.relationship_type))
        return []

    async def get_item_relationships(self, item_id: int) -> list[Any]:
        return []


def _fake_client_class(dl: _DeepLynx) -> type:
    class _FakeClient:
        """The ``AsyncStorageClient`` surface the service and the plugin use."""

        def __init__(self, config: ConnectionConfig) -> None:
            self.config = config
            self.files = _FakeFiles(dl)
            self.items = _FakeItems(dl)
            self.search = _FakeSearch(dl)
            self.relationships = _FakeRelationships(dl)

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    return _FakeClient


@pytest.fixture
def deeplynx(monkeypatch: pytest.MonkeyPatch) -> _DeepLynx:
    dl = _DeepLynx()
    # The per-key save locks bind to the loop that first uses them; each test has its own.
    monkeypatch.setattr(artifacts, "_save_locks", {})

    async def fake_deeplynx_config(agent: Any, user_id: str) -> ConnectionConfig:
        return ConnectionConfig(organization_id=1, project_id=2, jwt_token="t")

    for module in (artifacts, provenance):
        monkeypatch.setattr(module, "deeplynx_config", fake_deeplynx_config)
        monkeypatch.setattr(module, "AsyncStorageClient", _fake_client_class(dl))
    return dl


def _service() -> DeepLynxArtifactService:
    agent = _RecordAgent()
    return DeepLynxArtifactService(
        agent,  # type: ignore[arg-type]
        bridge=None,
        provenance=ProvenancePlugin(agent),  # type: ignore[arg-type]
    )


async def _save(service: DeepLynxArtifactService, data: bytes, filename: str = FILENAME) -> int:
    return await service.save_artifact(
        app_name=APP,
        user_id=USER,
        session_id=SESSION,
        filename=filename,
        artifact=types.Part.from_bytes(data=data, mime_type=MIME_TYPE),
    )


async def _bind_tool_call(invocation_id: str, function_call_id: str) -> None:
    tool_context = SimpleNamespace(invocation_id=invocation_id, function_call_id=function_call_id)
    await ArtifactCallPlugin().before_tool_callback(
        tool=None,  # type: ignore[arg-type]
        tool_args={},
        tool_context=tool_context,  # type: ignore[arg-type]
    )


async def test_artifact_service_one_item_per_save(deeplynx: _DeepLynx) -> None:
    """Covers REQ-016-02."""
    service = _service()
    first_bytes, second_bytes = b"mesh v0", b"mesh v1"

    first_version = await _save(service, first_bytes)
    updates_before_second_save = len(deeplynx.updates)
    second_version = await _save(service, second_bytes)

    assert (first_version, second_version) == (0, 1)
    assert deeplynx.uploads == [(FILENAME, first_bytes), (FILENAME, second_bytes)]
    first_id, second_id = 1, 2
    assert deeplynx.edges == [
        (RECORD_ID, first_id, GENERATED),
        (RECORD_ID, second_id, GENERATED),
    ]
    assert not [e for e in deeplynx.edges if e[2] == "supersedes"], "a supersedes edge was written"
    updated_after_second_save = [i for i, _ in deeplynx.updates[updates_before_second_save:]]
    assert updated_after_second_save == [second_id], (
        "the second save updated an item other than the one it uploaded"
    )
    assert deeplynx.deletes == []

    for item_id, data, version in ((first_id, first_bytes, 0), (second_id, second_bytes, 1)):
        props = deeplynx.items[item_id].properties
        assert props["kind"] == "artifact"
        assert props["version"] == version
        assert props["sha256"] == hashlib.sha256(data).hexdigest()
        assert props["idempotency_key"] is None
        assert props["execution_record_id"] == RECORD_ID
    assert await service.list_versions(
        app_name=APP, user_id=USER, session_id=SESSION, filename=FILENAME
    ) == [0, 1]

    await service.delete_artifact(app_name=APP, user_id=USER, session_id=SESSION, filename=FILENAME)

    assert [c.properties["kind"] for c in deeplynx.creates] == ["tombstone"]
    assert deeplynx.deletes == [], "delete_artifact called items.delete"
    assert {first_id, second_id} <= deeplynx.items.keys()
    assert (
        await service.list_versions(
            app_name=APP, user_id=USER, session_id=SESSION, filename=FILENAME
        )
        == []
    )


async def test_artifact_service_resumed_tool_call_save_is_idempotent(
    deeplynx: _DeepLynx,
) -> None:
    """Covers REQ-016-02 and BEH-016-01."""
    service = _service()

    async def tool_call_save() -> int:
        # A task of its own, as ADK runs each tool call, so the bound call stays in it.
        await _bind_tool_call("inv-1", "fc-1")
        return await _save(service, b"mesh v0")

    first_version = await asyncio.create_task(tool_call_save())
    resumed_version = await asyncio.create_task(tool_call_save())

    assert (first_version, resumed_version) == (0, 0)
    assert len(deeplynx.uploads) == 1, "the resumed save made a second item"
    assert deeplynx.edges == [(RECORD_ID, 1, GENERATED)]
    assert deeplynx.items[1].properties["idempotency_key"] == f"inv-1:fc-1:{FILENAME}"


async def test_artifact_service_concurrent_saves_get_distinct_versions(
    deeplynx: _DeepLynx,
) -> None:
    """Covers REQ-016-02."""
    service = _service()

    versions = await asyncio.gather(_save(service, b"mesh a"), _save(service, b"mesh b"))

    assert sorted(versions) == [0, 1], "two concurrent saves got the same version"
    assert sorted(item.properties["version"] for item in deeplynx.items.values()) == [0, 1]


async def test_artifact_service_list_keys_makes_one_tombstone_search(
    deeplynx: _DeepLynx,
) -> None:
    """Covers REQ-016-02."""
    service = _service()
    for filename in ("a.exo", "b.exo", "c.exo"):
        await _save(service, b"mesh", filename=filename)
    await service.delete_artifact(app_name=APP, user_id=USER, session_id=SESSION, filename="b.exo")
    queries_before_list = len(deeplynx.queries)

    keys = await service.list_artifact_keys(app_name=APP, user_id=USER, session_id=SESSION)

    assert keys == ["a.exo", "c.exo"]
    tombstone_searches = [
        q for q in deeplynx.queries[queries_before_list:] if q == {"kind": "tombstone"}
    ]
    assert len(tombstone_searches) == 1, "list_artifact_keys searched tombstones once per key"
