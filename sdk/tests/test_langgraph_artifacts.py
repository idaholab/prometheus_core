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

"""Tests for ``save_artifact``, the DeepLynx artifact save of a LangGraph tool."""

from __future__ import annotations

import gc
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.tools import ToolRuntime

from prometheus_api.langgraph import artifacts
from prometheus_api.langgraph.artifacts import (
    PrometheusContext,
    merge_item_properties,
    save_artifact,
)
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item, ItemUpdate
from prometheus_api.storage_client.models.pagination import Page, PageInfo

ORG_ID = 7
PROJECT_ID = 11
THREAD_ID = "thread-1"
AGENT_ID = "report-agent"


class _FakeDeepLynx:
    """In-memory ``AsyncStorageClient`` stand-in: one item per upload, property search."""

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.store: dict[int, Item] = {}
        self.uploaded_ids: list[int] = []
        self.updated_ids: list[int] = []
        self.deleted_ids: list[int] = []
        self._next_id = 100
        self.search = MagicMock(advanced_query=AsyncMock(side_effect=self._advanced_query))
        self.files = MagicMock(upload_bytes=AsyncMock(side_effect=self._upload_bytes))
        self.items = MagicMock(
            get=AsyncMock(side_effect=self._get),
            update=AsyncMock(side_effect=self._update),
            delete=AsyncMock(side_effect=self._delete),
        )

    async def __aenter__(self) -> _FakeDeepLynx:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def _advanced_query(
        self, filters: list[dict[str, Any]], project_ids: list[int], page: int, page_size: int
    ) -> Page[Item]:
        assert project_ids == [PROJECT_ID]
        (wanted,) = filters
        assert wanted["filter"] == "properties" and wanted["operator"] == "KEY_VALUE"
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
        self.uploaded_ids.append(item_id)
        now = datetime.now(timezone.utc)
        self.store[item_id] = Item(
            id=item_id, name=name, properties={}, created_at=now, updated_at=now
        )
        return FileMetadata(id=item_id, name=name, size=len(data))

    def seed(self, item_id: int, name: str, properties: dict[str, Any], **fields: Any) -> None:
        now = datetime.now(timezone.utc)
        self.store[item_id] = Item(
            id=item_id,
            name=name,
            properties=properties,
            created_at=now,
            updated_at=now,
            **fields,
        )

    async def _get(self, item_id: int) -> Item:
        return self.store[item_id]

    async def _update(self, item_id: int, update: ItemUpdate) -> Item:
        self.updated_ids.append(item_id)
        changed = self.store[item_id].model_copy(update=update.model_dump(exclude_none=True))
        self.store[item_id] = changed
        return changed

    async def _delete(self, item_id: int) -> None:
        self.deleted_ids.append(item_id)


@pytest.fixture
def config() -> ConnectionConfig:
    return ConnectionConfig(organization_id=ORG_ID, project_id=PROJECT_ID, jwt_token="test-jwt")


@pytest.fixture
def deeplynx(monkeypatch: pytest.MonkeyPatch, config: ConnectionConfig) -> _FakeDeepLynx:
    fake = _FakeDeepLynx(config)
    monkeypatch.setattr(artifacts, "open_storage", lambda _config: fake)
    return fake


@pytest.fixture
def agent() -> MagicMock:
    agent = MagicMock()
    agent._producer_agent_id = AGENT_ID
    agent.send_artifact_reference = AsyncMock()
    return agent


def _runtime(agent: MagicMock, config: ConnectionConfig, tool_call_id: str | None) -> ToolRuntime:
    context = PrometheusContext(
        agent=agent,
        request=MagicMock(name="request"),
        event_queue=MagicMock(name="event_queue"),
        thread_id=THREAD_ID,
        execution_record_id=None,
        storage=config,
    )
    return ToolRuntime(
        state={},
        context=context,
        config={},
        stream_writer=lambda _chunk: None,
        tool_call_id=tool_call_id,
        store=None,
    )


async def test_two_saves_in_two_tool_calls_make_two_new_versions(deeplynx, agent, config):
    """Covers REQ-017-02."""
    first_data, second_data = b"draft one", b"draft two"

    first = await save_artifact(
        _runtime(agent, config, "call_1"), "report.txt", first_data, "text/plain"
    )
    assert deeplynx.updated_ids == [first.item_id]

    second = await save_artifact(
        _runtime(agent, config, "call_2"), "report.txt", second_data, "text/plain"
    )

    # One new item per save; the second save updates only its own new item.
    assert first.item_id != second.item_id
    assert set(deeplynx.store) == {first.item_id, second.item_id}
    assert deeplynx.updated_ids == [first.item_id, second.item_id]
    assert deeplynx.deleted_ids == []
    deeplynx.items.delete.assert_not_called()

    assert (first.version, second.version) == (0, 1)
    key = f"{AGENT_ID}/{THREAD_ID}/report.txt"
    for saved, data, call_id in (
        (first, first_data, "call_1"),
        (second, second_data, "call_2"),
    ):
        properties = deeplynx.store[saved.item_id].properties
        assert properties["artifact_key"] == key
        assert properties["version"] == saved.version
        assert properties["sha256"] == hashlib.sha256(data).hexdigest()
        assert properties["idempotency_key"] == f"{THREAD_ID}:{call_id}:report.txt"
        assert saved.uri == (
            f"deeplynx://organizations/{ORG_ID}/projects/{PROJECT_ID}/items/{saved.item_id}"
        )

    # The first item keeps its version after the second save.
    assert deeplynx.store[first.item_id].properties["version"] == 0

    # The file id that the backend resolves an artifact by is the upload's id.
    assert deeplynx.uploaded_ids == [first.item_id, second.item_id]
    updates = deeplynx.items.update.await_args_list
    assert [update.args[1].properties["file_id"] for update in updates] == deeplynx.uploaded_ids
    assert [first.file_id, second.file_id] == deeplynx.uploaded_ids

    events = agent.send_artifact_reference.await_args_list
    assert len(events) == 2
    assert [event.kwargs["metadata"]["deeplynx_file_id"] for event in events] == (
        deeplynx.uploaded_ids
    )
    assert [event.kwargs["uri"] for event in events] == [first.uri, second.uri]
    assert [event.kwargs["metadata"]["version"] for event in events] == [0, 1]
    assert all(event.kwargs["name"] == "report.txt" for event in events)
    assert [event.kwargs["description"] for event in events] == [
        "report.txt (version 0)",
        "report.txt (version 1)",
    ]

    # One registry artifact_id per save, on the item, the reference and the result.
    assert first.artifact_id and second.artifact_id and first.artifact_id != second.artifact_id
    for saved, event in zip((first, second), events):
        assert deeplynx.store[saved.item_id].properties["artifact_id"] == saved.artifact_id
        assert event.kwargs["artifact_id"] == saved.artifact_id


async def test_resumed_tool_call_returns_first_version_without_new_item(deeplynx, agent, config):
    """Covers BEH-017-01 and REQ-017-02."""
    data = b'{"status": "done"}'

    first = await save_artifact(
        _runtime(agent, config, "call_slow"), "slow-job.json", data, "application/json"
    )
    resumed = await save_artifact(
        _runtime(agent, config, "call_slow"), "slow-job.json", data, "application/json"
    )

    assert resumed.item_id == first.item_id
    assert resumed.version == first.version == 0
    assert resumed.uri == first.uri
    (event,) = agent.send_artifact_reference.await_args_list
    assert resumed.file_id == first.file_id == event.kwargs["metadata"]["deeplynx_file_id"]
    assert resumed.artifact_id == first.artifact_id == event.kwargs["artifact_id"]
    assert list(deeplynx.store) == [first.item_id]
    deeplynx.files.upload_bytes.assert_awaited_once()
    assert deeplynx.updated_ids == [first.item_id]
    assert agent.send_artifact_reference.await_count == 1


async def test_resumed_tool_call_returns_stored_file_id(deeplynx, agent, config):
    """Covers BEH-017-01 and REQ-017-02."""
    deeplynx.seed(
        42,
        "slow-job.json",
        {
            "artifact_key": f"{AGENT_ID}/{THREAD_ID}/slow-job.json",
            "version": 0,
            "idempotency_key": f"{THREAD_ID}:call_slow:slow-job.json",
            "mime_type": "application/json",
            "file_id": 265,
            "artifact_id": "abc",
        },
    )

    resumed = await save_artifact(
        _runtime(agent, config, "call_slow"), "slow-job.json", b"{}", "application/json"
    )

    assert resumed.item_id == 42
    assert resumed.file_id == 265
    assert resumed.artifact_id == "abc"
    assert resumed.version == 0
    deeplynx.files.upload_bytes.assert_not_called()
    deeplynx.items.update.assert_not_called()
    agent.send_artifact_reference.assert_not_called()


async def test_save_passes_description_json_type_and_metadata_under_reserved_keys(
    deeplynx, agent, config
):
    """Covers REQ-017-02."""
    caller_metadata = {"source": "sweep", "version": 99, "file_id": 1, "deeplynx_item_id": 5}

    saved = await save_artifact(
        _runtime(agent, config, "call_meta"),
        "summary.json",
        b"{}",
        "application/json",
        description="Sweep summary",
        json_type="sweep_summary",
        metadata=caller_metadata,
    )

    (update,) = deeplynx.items.update.await_args_list
    written: ItemUpdate = update.args[1]
    assert written.description == "Sweep summary"
    assert written.properties["json_type"] == "sweep_summary"
    assert written.properties["source"] == "sweep"
    # The artifact keys win over the caller's metadata.
    assert written.properties["version"] == saved.version == 0
    assert written.properties["file_id"] == saved.file_id == saved.item_id

    (event,) = agent.send_artifact_reference.await_args_list
    assert event.kwargs["description"] == "Sweep summary"
    reference = event.kwargs["metadata"]
    assert reference["json_type"] == "sweep_summary"
    assert reference["source"] == "sweep"
    assert reference["version"] == 0
    assert reference["deeplynx_item_id"] == reference["deeplynx_file_id"] == saved.item_id


async def test_save_lock_drops_out_after_the_save(deeplynx, agent, config):
    """Covers REQ-017-02."""
    await save_artifact(_runtime(agent, config, "call_lock"), "report.txt", b"x", "text/plain")
    gc.collect()

    assert f"{AGENT_ID}/{THREAD_ID}/report.txt" not in artifacts._save_locks


async def test_merge_item_properties_keeps_class_and_original_id(deeplynx):
    """Covers REQ-017-02."""
    deeplynx.seed(7, "run.json", {"a": 1}, description="run", class_id=3, original_id="orig-7")

    await merge_item_properties(deeplynx, 7, {"b": 2})

    (update,) = deeplynx.items.update.await_args_list
    item_id, written = update.args
    assert item_id == 7
    assert written == ItemUpdate(
        name="run.json",
        description="run",
        properties={"a": 1, "b": 2},
        class_id=3,
        original_id="orig-7",
    )
