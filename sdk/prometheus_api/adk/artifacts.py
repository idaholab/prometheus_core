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
"""ADK artifact service over DeepLynx: one immutable item per save (REQ-016-02).

``save_artifact`` uploads the bytes as a new DeepLynx item, writes its artifact properties
with one ``items.update`` on that new item, tags it, adds the ``generated`` edge through the
provenance plugin and emits the artifact reference through the A2A bridge. It never updates
or deletes an earlier item, and it writes no ``supersedes`` relation: the versions of an
artifact are the items that share its ``artifact_key`` property. ``delete_artifact`` creates
a ``kind: tombstone`` item; the versions saved before the newest tombstone of a key are
hidden from load and list.

Idempotency (BEH-016-01): ADK passes neither the invocation ID nor the function call ID to
``save_artifact``, so ``ArtifactCallPlugin.before_tool_callback`` binds them in a
``ContextVar``. ADK runs that callback in the task that then runs the tool, so the tool's
``save_artifact`` sees its own call. A save inside a tool call carries the idempotency key
``invocation_id:function_call_id:filename``; a resumed tool that saves the same file again
gets the first version back and no second item is made. A save outside a tool call has no
idempotency key and always makes a new item.

The version list is rebuilt from ``search.advanced_query`` on ``artifact_key`` on every call;
the service keeps no ``artifact_index`` session-state index, because it only sees the
session inside a tool call. DeepLynx errors propagate after the storage client's retries;
there is no local fallback.
"""

import asyncio
import hashlib
import json
import shutil
import tempfile
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from google.adk.artifacts.base_artifact_service import (
    ArtifactVersion,
    BaseArtifactService,
    ensure_part,
)
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from ..storage_client.async_client import AsyncStorageClient
from ..storage_client.connection import ConnectionConfig
from ..storage_client.models.item import Item, ItemCreate, ItemUpdate
from .plugins.credentials import deeplynx_config

if TYPE_CHECKING:
    from ..agent.base import PrometheusAgent
    from .plugins.bridge import A2ABridgePlugin
    from .plugins.provenance import ProvenancePlugin

ARTIFACT_KIND = "artifact"
TOMBSTONE_KIND = "tombstone"
USER_NAMESPACE = "user:"

_SEARCH_PAGE_SIZE = 500
# One lock per artifact_key, so concurrent saves in this process count versions one at a time.
_save_locks: dict[str, asyncio.Lock] = {}
_tool_call: ContextVar[tuple[str, str] | None] = ContextVar(
    "prometheus_adk_artifact_tool_call", default=None
)


class ArtifactCallPlugin(BasePlugin):
    """Bind the current ``(invocation_id, function_call_id)`` for ``DeepLynxArtifactService``."""

    def __init__(self) -> None:
        super().__init__(name="prometheus_artifact_call")

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        if tool_context.function_call_id:
            _tool_call.set((tool_context.invocation_id, tool_context.function_call_id))
        return None


def artifact_key(app_name: str, user_id: str, session_id: str | None, filename: str) -> str:
    """Return the key that groups the versions of an artifact.

    The artifact is user-scoped when *session_id* is ``None`` or *filename* has ADK's
    ``user:`` namespace, and session-scoped otherwise.
    """
    if _user_scoped(session_id, filename):
        return f"{app_name}/{user_id}/user/{filename}"
    return f"{app_name}/{user_id}/{session_id}/{filename}"


def _user_scoped(session_id: str | None, filename: str) -> bool:
    return session_id is None or filename.startswith(USER_NAMESPACE)


def idempotency_key(filename: str) -> str | None:
    """Return ``invocation_id:function_call_id:filename``, or ``None`` outside a tool call."""
    call = _tool_call.get()
    if call is None:
        return None
    invocation_id, function_call_id = call
    return f"{invocation_id}:{function_call_id}:{filename}"


def _payload(part: types.Part) -> tuple[bytes, str]:
    """Return the bytes and MIME type of an inline-data or text artifact."""
    if part.inline_data is not None and part.inline_data.data is not None:
        return part.inline_data.data, part.inline_data.mime_type or "application/octet-stream"
    if part.text is not None:
        return part.text.encode("utf-8"), "text/plain"
    raise ValueError("DeepLynxArtifactService saves inline-data or text artifacts only")


def _item_uri(config: ConnectionConfig, item_id: int) -> str:
    return (
        f"deeplynx://organizations/{config.organization_id}"
        f"/projects/{config.project_id}"
        f"/items/{item_id}"
    )


async def find_by_property(dl: AsyncStorageClient, name: str, value: Any) -> list[Item]:
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


def _live_versions(items: list[Item]) -> list[Item]:
    """Return the artifact items saved after the newest tombstone, by version."""
    tombstones = [i.id for i in items if i.properties.get("kind") == TOMBSTONE_KIND]
    deleted_through = max(tombstones, default=0)
    live = [
        i for i in items if i.properties.get("kind") == ARTIFACT_KIND and i.id > deleted_through
    ]
    return sorted(live, key=lambda i: int(i.properties["version"]))


def _select(items: list[Item], version: int | None) -> Item | None:
    live = _live_versions(items)
    if version is None:
        return live[-1] if live else None
    return next((i for i in live if int(i.properties["version"]) == version), None)


def _artifact_version(config: ConnectionConfig, item: Item) -> ArtifactVersion:
    raw_metadata = item.properties.get("custom_metadata_json")
    return ArtifactVersion(
        version=int(item.properties["version"]),
        canonical_uri=_item_uri(config, item.id),
        custom_metadata=json.loads(raw_metadata) if raw_metadata else {},
        create_time=item.created_at.timestamp(),
        mime_type=item.properties.get("mime_type"),
    )


class DeepLynxArtifactService(BaseArtifactService):
    """Store each ADK artifact save as a new, never-updated DeepLynx item.

    Args:
        agent: The agent whose per-user DeepLynx config (``deeplynx_config``), execution
            record and producer ID the items carry.
        bridge: The run's A2A bridge; each new item is emitted through
            ``emit_artifact_reference``. ``None`` emits nothing.
        provenance: The run's provenance plugin; it adds the ``generated`` edge of a save
            and the ``input_to`` edge of a load. ``None`` writes no edge.

    Register ``ArtifactCallPlugin()`` on the same runner, or saves carry no idempotency key.
    """

    def __init__(
        self,
        agent: "PrometheusAgent",
        *,
        bridge: "A2ABridgePlugin | None",
        provenance: "ProvenancePlugin | None",
    ) -> None:
        self._agent = agent
        self._bridge = bridge
        self._provenance = provenance

    async def save_artifact(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        artifact: types.Part | dict[str, Any],
        session_id: str | None = None,
        custom_metadata: dict[str, Any] | None = None,
    ) -> int:
        key = artifact_key(app_name, user_id, session_id, filename)
        idem = idempotency_key(filename)
        data, mime_type = _payload(ensure_part(artifact))
        config = await deeplynx_config(self._agent, user_id)
        lock = _save_locks.setdefault(key, asyncio.Lock())
        async with lock, AsyncStorageClient(config) as dl:
            if idem is not None:
                for hit in await find_by_property(dl, "idempotency_key", idem):
                    if hit.properties.get("kind") == ARTIFACT_KIND:
                        return int(hit.properties["version"])
            existing_items = await find_by_property(dl, "artifact_key", key)
            version = sum(1 for i in existing_items if i.properties.get("kind") == ARTIFACT_KIND)
            meta = await dl.files.upload_bytes(data, name=filename)

            # The upload made the item; write its artifact properties once, before anything
            # can cite it. No later call changes it.
            uploaded = await dl.items.get(meta.id)
            properties: dict[str, Any] = dict(uploaded.properties or {})
            properties.update(
                {
                    "kind": ARTIFACT_KIND,
                    "artifact_key": key,
                    "filename": filename,
                    "version": version,
                    "mime_type": mime_type,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                    "scope": "user" if _user_scoped(session_id, filename) else "session",
                    "conversation_id": session_id,
                    "producer_agent_id": self._agent._producer_agent_id,
                    "idempotency_key": idem,
                    "execution_record_id": self._agent.execution_record_id,
                    "file_id": meta.id,
                }
            )
            if custom_metadata:
                properties["custom_metadata_json"] = json.dumps(
                    custom_metadata, sort_keys=True, default=str
                )
            await dl.items.update(
                meta.id,
                ItemUpdate(
                    name=filename,
                    description=uploaded.description,
                    properties=properties,
                    class_id=uploaded.class_id,
                    original_id=uploaded.original_id,
                ),
            )
            tags = [f"artifact:{key}"]
            if session_id is not None:
                tags.append(f"session:{session_id}")
            await dl.items.add_tags(meta.id, tags)

        if self._provenance is not None:
            await self._provenance.add_generated(user_id, meta.id)
        if self._bridge is not None:
            await self._bridge.emit_artifact_reference(
                meta.id, filename, mime_type, uri=_item_uri(config, meta.id)
            )
        return version

    async def load_artifact(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: str | None = None,
        version: int | None = None,
    ) -> types.Part | None:
        key = artifact_key(app_name, user_id, session_id, filename)
        config = await deeplynx_config(self._agent, user_id)
        async with AsyncStorageClient(config) as dl:
            item = _select(await find_by_property(dl, "artifact_key", key), version)
            if item is None:
                return None
            tmp = await asyncio.to_thread(tempfile.mkdtemp)
            try:
                path = Path(tmp) / "artifact"
                await dl.files.download(item.id, path)
                data = await asyncio.to_thread(path.read_bytes)
            finally:
                await asyncio.to_thread(shutil.rmtree, tmp, True)
        if self._provenance is not None:
            await self._provenance.add_input(user_id, item.id)
        mime_type = item.properties.get("mime_type") or "application/octet-stream"
        if mime_type == "text/plain":
            return types.Part(text=data.decode("utf-8"))
        return types.Part.from_bytes(data=data, mime_type=mime_type)

    async def list_artifact_keys(
        self, *, app_name: str, user_id: str, session_id: str | None = None
    ) -> list[str]:
        config = await deeplynx_config(self._agent, user_id)
        prefixes = [f"{app_name}/{user_id}/user/"]
        if session_id is not None:
            prefixes.append(f"{app_name}/{user_id}/{session_id}/")
        async with AsyncStorageClient(config) as dl:
            candidates = [
                i
                for i in await find_by_property(dl, "scope", "user")
                if i.properties.get("artifact_key", "").startswith(prefixes[0])
            ]
            if session_id is not None:
                candidates += [
                    i
                    for i in await find_by_property(dl, "conversation_id", session_id)
                    if i.properties.get("artifact_key", "").startswith(prefixes[1])
                ]
            tombstones = [
                i
                for i in await find_by_property(dl, "kind", TOMBSTONE_KIND)
                if i.properties.get("artifact_key", "").startswith(tuple(prefixes))
            ]
        by_key: dict[str, list[Item]] = {}
        for i in [*candidates, *tombstones]:
            by_key.setdefault(i.properties["artifact_key"], []).append(i)
        return sorted(
            live[-1].properties["filename"]
            for items in by_key.values()
            if (live := _live_versions(items))
        )

    async def delete_artifact(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: str | None = None,
    ) -> None:
        key = artifact_key(app_name, user_id, session_id, filename)
        config = await deeplynx_config(self._agent, user_id)
        async with AsyncStorageClient(config) as dl:
            if not _live_versions(await find_by_property(dl, "artifact_key", key)):
                return
            await dl.items.create(
                ItemCreate(
                    name=f"Tombstone {filename}",
                    description=f"Deletion of artifact {key}",
                    properties={
                        "kind": TOMBSTONE_KIND,
                        "artifact_key": key,
                        "deleted_at": datetime.now(UTC).isoformat(),
                        "execution_record_id": self._agent.execution_record_id,
                    },
                    class_id=None,
                    original_id=f"prometheus-artifact-tombstone:{key}:{uuid.uuid4()}",
                )
            )

    async def list_versions(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: str | None = None,
    ) -> list[int]:
        versions = await self.list_artifact_versions(
            app_name=app_name, user_id=user_id, filename=filename, session_id=session_id
        )
        return [v.version for v in versions]

    async def list_artifact_versions(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: str | None = None,
    ) -> list[ArtifactVersion]:
        key = artifact_key(app_name, user_id, session_id, filename)
        config = await deeplynx_config(self._agent, user_id)
        async with AsyncStorageClient(config) as dl:
            items = _live_versions(await find_by_property(dl, "artifact_key", key))
        return [_artifact_version(config, i) for i in items]

    async def get_artifact_version(
        self,
        *,
        app_name: str,
        user_id: str,
        filename: str,
        session_id: str | None = None,
        version: int | None = None,
    ) -> ArtifactVersion | None:
        key = artifact_key(app_name, user_id, session_id, filename)
        config = await deeplynx_config(self._agent, user_id)
        async with AsyncStorageClient(config) as dl:
            item = _select(await find_by_property(dl, "artifact_key", key), version)
        return None if item is None else _artifact_version(config, item)
