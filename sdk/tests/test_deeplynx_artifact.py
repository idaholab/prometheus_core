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

"""Unit tests for PrometheusAgent.send_deeplynx_artifact with a fake DeepLynx client."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item
from prometheus_api.storage_client.models.pagination import Page, PageInfo


class _DummyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        return {"ok": True}


def make_item(item_id: int, properties: dict) -> Item:
    """Build a minimal DeepLynx Item model."""
    now = datetime.now(timezone.utc)
    return Item(
        id=item_id,
        name=f"item-{item_id}",
        description=None,
        properties=properties,
        class_id=None,
        original_id=f"orig-{item_id}",
        created_at=now,
        updated_at=now,
        tags=[],
        metatype_id=None,
        metatype_name=None,
        data_source_id=None,
    )


def make_page(items) -> Page:
    """Build a single-page Page object from an iterable of items."""
    item_list = list(items)
    return Page(
        items=item_list,
        page_info=PageInfo(
            page_number=1,
            page_size=25,
            total_count=len(item_list),
            has_next=False,
            has_previous=False,
        ),
    )


@pytest.fixture
def storage_config() -> ConnectionConfig:
    return ConnectionConfig(organization_id=1, project_id=2, jwt_token="unit-test-token")


@pytest.fixture
def fake_client(monkeypatch) -> SimpleNamespace:
    """Replace AsyncStorageClient in agent.base with an async fake.

    The fake's ``files``, ``items`` and ``search`` are ``AsyncMock``s; by default the
    content-hash lookup finds nothing and the upload creates item 101.
    """
    client = SimpleNamespace(
        files=AsyncMock(),
        items=AsyncMock(),
        search=AsyncMock(),
    )
    client.search.advanced_query.return_value = make_page([])
    client.files.upload.return_value = FileMetadata(id=101, name="mesh.e", size=9)
    client.items.get.return_value = make_item(101, {"existing": "value"})

    class FakeAsyncStorageClient:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", FakeAsyncStorageClient)
    return client


@pytest.fixture
def agent() -> _DummyAgent:
    """An agent whose send_artifact_reference is captured, not registered or emitted."""
    instance = _DummyAgent(agent_name="Test Agent")
    instance.send_artifact_reference = AsyncMock(return_value=SimpleNamespace())
    return instance


@pytest.fixture
def context() -> MagicMock:
    ctx = MagicMock(spec=RequestContext)
    ctx.task_id = "task-1"
    ctx.context_id = "conv-1"
    return ctx


@pytest.fixture
def local_file(tmp_path):
    path = tmp_path / "mesh.e"
    path.write_bytes(b"mesh-data")
    return path


async def test_upload_stores_content_hash(agent, context, fake_client, storage_config, local_file):
    """Covers REQ-010-12."""
    expected_digest = hashlib.sha256(local_file.read_bytes()).hexdigest()

    await agent.send_deeplynx_artifact(
        context,
        AsyncMock(spec=EventQueue),
        file_path=local_file,
        name="Mesh Output",
        description="Hex mesh",
        storage_config=storage_config,
        tags=["mesh", "cad"],
    )

    fake_client.search.advanced_query.assert_awaited_once()
    fake_client.files.upload.assert_awaited_once()

    update_call = fake_client.items.update.await_args
    assert update_call is not None
    assert update_call.args[0] == 101
    properties = update_call.args[1].properties
    assert properties["checksum"] == expected_digest
    assert properties["existing"] == "value"

    fake_client.items.add_tags.assert_awaited_once_with(101, ["mesh", "cad"])

    reference_kwargs = agent.send_artifact_reference.await_args.kwargs
    assert reference_kwargs["uri"] == "deeplynx://organizations/1/projects/2/items/101"
    metadata = reference_kwargs["metadata"]
    assert metadata["deeplynx_item_id"] == 101
    assert metadata["deeplynx_file_id"] == 101
    assert metadata["checksum"] == expected_digest
    assert metadata["deeplynx_deduplicated"] is False


async def test_duplicate_upload_reuses_item(
    agent, context, fake_client, storage_config, local_file
):
    """Covers REQ-010-17 and BEH-010-04."""
    digest = hashlib.sha256(local_file.read_bytes()).hexdigest()
    fake_client.search.advanced_query.return_value = make_page(
        [make_item(42, {"checksum": digest})]
    )

    await agent.send_deeplynx_artifact(
        context,
        AsyncMock(spec=EventQueue),
        file_path=local_file,
        name="Mesh Output",
        description="Hex mesh",
        storage_config=storage_config,
        tags=["mesh"],
    )

    lookup = fake_client.search.advanced_query.await_args
    assert lookup is not None
    (lookup_filter,) = lookup.kwargs["filters"]
    assert json.loads(lookup_filter["json"]) == {"checksum": digest}
    assert lookup.kwargs["project_ids"] == [storage_config.project_id]

    fake_client.files.upload.assert_not_awaited()
    fake_client.items.update.assert_not_awaited()
    fake_client.items.add_tags.assert_not_awaited()

    reference_kwargs = agent.send_artifact_reference.await_args.kwargs
    assert reference_kwargs["uri"].endswith("/items/42")
    assert reference_kwargs["size_bytes"] == local_file.stat().st_size
    metadata = reference_kwargs["metadata"]
    assert metadata["deeplynx_item_id"] == 42
    assert metadata["checksum"] == digest
    assert metadata["deeplynx_deduplicated"] is True


async def test_lookup_hit_with_other_digest_is_not_reused(
    agent, context, fake_client, storage_config, local_file
):
    """Covers REQ-010-17."""
    fake_client.search.advanced_query.return_value = make_page(
        [make_item(42, {"checksum": "0" * 64})]
    )

    await agent.send_deeplynx_artifact(
        context,
        AsyncMock(spec=EventQueue),
        file_path=local_file,
        name="Mesh Output",
        description="Hex mesh",
        storage_config=storage_config,
    )

    fake_client.files.upload.assert_awaited_once()
    reference_kwargs = agent.send_artifact_reference.await_args.kwargs
    assert reference_kwargs["uri"].endswith("/items/101")
    assert reference_kwargs["metadata"]["deeplynx_deduplicated"] is False


async def test_dedup_lookup_failure_uploads(
    agent, context, fake_client, storage_config, local_file
):
    """Covers REQ-010-18."""
    fake_client.search.advanced_query.side_effect = RuntimeError("search unavailable")

    await agent.send_deeplynx_artifact(
        context,
        AsyncMock(spec=EventQueue),
        file_path=local_file,
        name="Mesh Output",
        description="Hex mesh",
        storage_config=storage_config,
    )

    fake_client.search.advanced_query.assert_awaited_once()
    fake_client.files.upload.assert_awaited_once()
    reference_kwargs = agent.send_artifact_reference.await_args.kwargs
    assert reference_kwargs["uri"] == "deeplynx://organizations/1/projects/2/items/101"
    assert reference_kwargs["metadata"]["deeplynx_item_id"] == 101
    assert reference_kwargs["metadata"]["deeplynx_deduplicated"] is False


async def test_dedup_disabled_always_uploads(
    agent, context, fake_client, storage_config, local_file
):
    """Covers REQ-010-19."""
    digest = hashlib.sha256(local_file.read_bytes()).hexdigest()
    fake_client.search.advanced_query.return_value = make_page(
        [make_item(42, {"checksum": digest})]
    )

    await agent.send_deeplynx_artifact(
        context,
        AsyncMock(spec=EventQueue),
        file_path=local_file,
        name="Mesh Output",
        description="Hex mesh",
        storage_config=storage_config,
        deduplicate=False,
    )

    fake_client.search.advanced_query.assert_not_awaited()
    fake_client.files.upload.assert_awaited_once()
    reference_kwargs = agent.send_artifact_reference.await_args.kwargs
    assert reference_kwargs["uri"] == "deeplynx://organizations/1/projects/2/items/101"
    assert reference_kwargs["metadata"]["deeplynx_item_id"] == 101
    assert reference_kwargs["metadata"]["deeplynx_deduplicated"] is False
