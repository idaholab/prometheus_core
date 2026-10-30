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
"""DeepLynx artifacts for LangGraph tools: one immutable item per save (REQ-017-02).

A tool that declares ``runtime: ToolRuntime[PrometheusContext]`` calls ``save_artifact`` to
upload bytes as a new DeepLynx item and ``load_artifact`` to read an item back. A save never
updates or deletes an earlier item: the versions of an artifact are the items that share its
``artifact_key`` property.

Idempotency (BEH-017-01): a save inside a tool call carries the key
``thread_id:tool_call_id:filename``. LangGraph checkpoints the tool call ID with the model
message, so a resumed run that calls the same tool again gets the first version back and no
second item is made. A save outside a tool call has no key and always makes a new item.

DeepLynx errors propagate after the storage client's retries; there is no local fallback.
"""

import asyncio
import hashlib
import json
import shutil
import tempfile
import uuid
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from langchain.tools import ToolRuntime

from ..agent.base import PrometheusAgent
from ..storage_client.async_client import AsyncStorageClient
from ..storage_client.connection import ConnectionConfig
from ..storage_client.models.item import Item, ItemUpdate

GENERATED = "generated"
INPUT_TO = "input_to"

_SEARCH_PAGE_SIZE = 500
# One lock per artifact_key, so concurrent saves in this process count versions one at a time.
# Each saver holds its lock while it waits or saves; an unused lock drops out of the map.
_save_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


@dataclass
class ProvenanceLedger:
    """The provenance of one run that ``ProvenanceMiddleware`` still has to write.

    ``edges`` holds each pending ``(from_id, to_id, type)`` relation once; ``tool_calls``
    holds the tool-call log that closes the execution record.
    """

    edges: list[tuple[int, int, str]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def add_generated(self, record_id: int | None, item_id: int) -> None:
        """Add the ``generated`` edge from the execution record to a saved item."""
        if record_id is not None:
            self._add((record_id, item_id, GENERATED))

    def add_input_to(self, record_id: int | None, item_id: int) -> None:
        """Add the ``input_to`` edge from a loaded item to the execution record."""
        if record_id is not None:
            self._add((item_id, record_id, INPUT_TO))

    def _add(self, edge: tuple[int, int, str]) -> None:
        if edge not in self.edges:
            self.edges.append(edge)


@dataclass
class PrometheusContext:
    """The ``create_agent`` context schema of a Prometheus LangGraph run."""

    agent: PrometheusAgent
    request: RequestContext
    event_queue: EventQueue
    thread_id: str
    execution_record_id: int | None
    storage: ConnectionConfig | None
    provenance: ProvenanceLedger = field(default_factory=ProvenanceLedger)


@dataclass(frozen=True)
class SavedArtifact:
    """The DeepLynx item of a saved artifact."""

    item_id: int
    file_id: int
    version: int
    uri: str
    filename: str
    mime_type: str
    artifact_id: str | None


@dataclass(frozen=True)
class LoadedArtifact:
    """The bytes and DeepLynx item of a loaded artifact."""

    item_id: int
    uri: str
    filename: str
    mime_type: str
    data: bytes


def open_storage(config: ConnectionConfig) -> AsyncStorageClient:
    """Return the storage client of a call; tests replace it with a fake."""
    return AsyncStorageClient(config)


def _storage(runtime: ToolRuntime[PrometheusContext]) -> ConnectionConfig:
    if runtime.context.storage is None:
        raise RuntimeError("DeepLynx is not configured")
    return runtime.context.storage


def _item_uri(config: ConnectionConfig, item_id: int) -> str:
    return (
        f"deeplynx://organizations/{config.organization_id}"
        f"/projects/{config.project_id}"
        f"/items/{item_id}"
    )


async def _find_by_property(dl: AsyncStorageClient, name: str, value: Any) -> list[Item]:
    """Return every item whose ``properties[name]`` equals *value*."""
    filters = [{"filter": "properties", "operator": "KEY_VALUE", "json": json.dumps({name: value})}]
    items: list[Item] = []
    page = 1
    while True:
        result = await dl.search.advanced_query(
            filters=filters,
            project_ids=[dl.config.project_id],
            page=page,
            page_size=_SEARCH_PAGE_SIZE,
        )
        items.extend(result.items)
        if not result.page_info.has_next:
            return items
        page += 1


async def merge_item_properties(
    dl: AsyncStorageClient,
    item_id: int,
    properties: Mapping[str, Any],
    *,
    name: str | None = None,
    description: str | None = None,
) -> Item:
    """Merge *properties* into the properties of an item and write the item back.

    The name and description stay unless given; ``class_id`` and ``original_id`` stay.
    """
    existing = await dl.items.get(item_id)
    return await dl.items.update(
        item_id,
        ItemUpdate(
            name=name if name is not None else existing.name,
            description=description if description is not None else existing.description,
            properties={**(existing.properties or {}), **properties},
            class_id=existing.class_id,
            original_id=existing.original_id,
        ),
    )


async def save_artifact(
    runtime: ToolRuntime[PrometheusContext],
    filename: str,
    data: bytes,
    mime_type: str,
    *,
    description: str | None = None,
    json_type: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SavedArtifact:
    """Save *data* as a new DeepLynx item and emit its ``deeplynx://`` reference.

    *description* goes to the item and the reference (default ``"<filename> (version N)"``).
    *json_type* and the *metadata* entries go to the item properties and the reference
    metadata; the artifact keys (``artifact_key``, ``version``, ``sha256``,
    ``idempotency_key``, ``mime_type``, ``filename``, ``file_id``, ``artifact_id``) win over
    them. The registry ``artifact_id`` is stored on the item, so a repeat finds it again.

    A save that repeats the tool call of an earlier save returns that save's item, version
    and ``artifact_id``, and makes no second item and no second reference.
    """
    ctx = runtime.context
    config = _storage(runtime)
    key = f"{ctx.agent._producer_agent_id}/{ctx.thread_id}/{filename}"
    idem = (
        f"{ctx.thread_id}:{runtime.tool_call_id}:{filename}"
        if runtime.tool_call_id is not None
        else None
    )
    lock = _save_locks.setdefault(key, asyncio.Lock())
    async with lock, open_storage(config) as dl:
        if idem is not None:
            hits = await _find_by_property(dl, "idempotency_key", idem)
            if hits:
                first = hits[0]
                ctx.provenance.add_generated(ctx.execution_record_id, first.id)
                return SavedArtifact(
                    item_id=first.id,
                    file_id=int(first.properties.get("file_id") or first.id),
                    version=int(first.properties["version"]),
                    uri=_item_uri(config, first.id),
                    filename=filename,
                    mime_type=first.properties.get("mime_type") or mime_type,
                    artifact_id=first.properties.get("artifact_id"),
                )
        version = len(await _find_by_property(dl, "artifact_key", key))
        meta = await dl.files.upload_bytes(data, name=filename)
        artifact_id = str(uuid.uuid4())
        extra: dict[str, Any] = dict(metadata or {})
        if json_type:
            extra["json_type"] = json_type

        # The upload made the item; write its artifact properties once, before anything
        # can cite it. No later call changes it.
        await merge_item_properties(
            dl,
            meta.id,
            {
                **extra,
                "artifact_key": key,
                "version": version,
                "sha256": hashlib.sha256(data).hexdigest(),
                "idempotency_key": idem,
                "mime_type": mime_type,
                "filename": filename,
                "file_id": meta.id,
                "artifact_id": artifact_id,
            },
            name=filename,
            description=description,
        )

    uri = _item_uri(config, meta.id)
    ctx.provenance.add_generated(ctx.execution_record_id, meta.id)
    await ctx.agent.send_artifact_reference(
        ctx.request,
        ctx.event_queue,
        name=filename,
        description=description or f"{filename} (version {version})",
        uri=uri,
        mime_type=mime_type,
        size_bytes=len(data),
        artifact_id=artifact_id,
        metadata={
            **extra,
            "deeplynx_item_id": meta.id,
            "deeplynx_file_id": meta.id,
            "version": version,
        },
    )
    return SavedArtifact(
        item_id=meta.id,
        file_id=meta.id,
        version=version,
        uri=uri,
        filename=filename,
        mime_type=mime_type,
        artifact_id=artifact_id,
    )


async def load_artifact(runtime: ToolRuntime[PrometheusContext], item_id: int) -> LoadedArtifact:
    """Download the bytes of the DeepLynx item *item_id* and record its ``input_to`` edge."""
    ctx = runtime.context
    config = _storage(runtime)
    async with open_storage(config) as dl:
        item = await dl.items.get(item_id)
        tmp = await asyncio.to_thread(tempfile.mkdtemp)
        try:
            path = Path(tmp) / "artifact"
            await dl.files.download(item_id, path)
            data = await asyncio.to_thread(path.read_bytes)
        finally:
            await asyncio.to_thread(shutil.rmtree, tmp, True)
    ctx.provenance.add_input_to(ctx.execution_record_id, item_id)
    return LoadedArtifact(
        item_id=item_id,
        uri=_item_uri(config, item_id),
        filename=item.properties.get("filename") or item.name,
        mime_type=item.properties.get("mime_type") or "application/octet-stream",
        data=data,
    )
