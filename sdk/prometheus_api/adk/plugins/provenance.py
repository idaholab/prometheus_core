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
"""Provenance plugin: the execution graph of an ADK run, on the PR #198 execution record.

``PrometheusAgent`` creates the run's DeepLynx execution item before ``_execute`` and exposes
its ID as ``agent.execution_record_id``. The plugin never creates a second record (REQ-016-03).
It adds relations to that record and closes it once:

- ``before_run_callback``: ``input_to`` (artifact -> record) for each DeepLynx item ID in the
  params JSON of the run's first user message (a ``deeplynx://.../items/{id}`` string, or an
  integer value of a key that ends in ``artifact_id``), and ``child_of`` (record -> parent)
  when ``RunConfig.custom_metadata`` carries ``PARENT_EXECUTION_RECORD_METADATA_KEY``, at the top
  level or inside ADK's ``a2a_metadata`` dict (the incoming A2A message metadata).
- ``add_input`` and ``add_generated``: the ``input_to`` and ``generated`` (record -> artifact)
  edges of an artifact that the artifact service loads or saves during the run.
- ``after_tool_callback``: one ``{tool, function_call_id, arguments_sha256, result_sha256,
  duration_ms}`` entry per call in ``TOOL_CALLS_STATE_KEY``.
- ``after_run_callback`` and ``on_run_error_callback``: one ``items.update`` of the record with
  ``status``, ``ended_at``, ``token_usage`` and ``tool_calls`` (plus the approvals of
  ``APPROVALS_STATE_KEY``), and the status in the session state key
  ``EXECUTION_STATUS_STATE_KEY``, which ``PrometheusMemoryService`` reads.

Each ``(from, to, type)`` edge is written once; a resumed run first reads the record's existing
relations. All edges go through ``relationships.bulk_create`` with the per-user DeepLynx
config, and a relation type that DeepLynx rejects raises. Arguments and results are stored as
SHA-256 digests only, so no credential reaches provenance. Without an execution record (no
DeepLynx, as in unit tests) the plugin writes nothing to DeepLynx.
"""

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from google.adk.a2a.converters.request_converter import A2A_METADATA_KEY
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.sessions.state import State
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from ...contract import PARENT_EXECUTION_RECORD_METADATA_KEY
from ...storage_client.async_client import AsyncStorageClient
from ...storage_client.models.item import ItemUpdate
from ...storage_client.models.relationship import RelationshipCreate
from ..memory import EXECUTION_STATUS_STATE_KEY
from .approval import APPROVALS_STATE_KEY
from .credentials import deeplynx_config

if TYPE_CHECKING:
    from ...agent.base import PrometheusAgent

logger = logging.getLogger(__name__)

TOOL_CALLS_STATE_KEY = f"{State.TEMP_PREFIX}tool_calls"
INPUT_TO = "input_to"
GENERATED = "generated"
CHILD_OF = "child_of"

_TOOL_CANCELLED_STATE_KEY = f"{State.TEMP_PREFIX}prometheus_tool_cancelled"
_DEEPLYNX_ITEM_URI = re.compile(r"deeplynx://[^\s\"']*?/items/(\d+)")

Edge = tuple[int, int, str]

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def _sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _item_id(value: Any) -> int | None:
    """Return *value* as a DeepLynx item ID, or ``None`` when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def artifact_item_ids(value: Any, key: str = "") -> Iterator[int]:
    """Yield the DeepLynx item IDs named in a params value, recursively.

    A string yields the ID of each ``deeplynx://.../items/{id}`` URI in it; an integer (or
    digit string) under a key that ends in ``artifact_id`` yields itself.
    """
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from artifact_item_ids(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from artifact_item_ids(child, key)
    elif isinstance(value, str):
        for match in _DEEPLYNX_ITEM_URI.finditer(value):
            yield int(match.group(1))
        if key.endswith("artifact_id") and (item_id := _item_id(value)) is not None:
            yield item_id
    elif key.endswith("artifact_id") and (item_id := _item_id(value)) is not None:
        yield item_id


def _run_events(invocation_context: InvocationContext) -> list[Event]:
    invocation_id = invocation_context.invocation_id
    return [e for e in invocation_context.session.events if e.invocation_id == invocation_id]


def _request_metadata(invocation_context: InvocationContext) -> dict[str, Any]:
    """Return the A2A message metadata the runner was given in ``RunConfig.custom_metadata``.

    The caller passes the message metadata either under ADK's ``a2a_metadata`` key (the
    convention of ``google.adk.a2a``) or as top-level ``custom_metadata`` keys.
    """
    run_config = invocation_context.run_config
    metadata = (run_config.custom_metadata if run_config else None) or {}
    nested = metadata.get(A2A_METADATA_KEY)
    return {**metadata, **nested} if isinstance(nested, dict) else dict(metadata)


def _params_value(invocation_context: InvocationContext) -> Any:
    """Return the params JSON of the run's first user message (its text when not JSON)."""
    content = invocation_context.user_content
    if content is None:
        content = next(
            (e.content for e in _run_events(invocation_context) if e.author == "user"), None
        )
    if content is None:
        return None
    text = "".join(part.text or "" for part in content.parts or [])
    try:
        return json.loads(text)
    except ValueError:
        return text


def _pending_long_running_calls(invocation_context: InvocationContext) -> set[str]:
    """Return the IDs of the run's long-running calls that have no function response yet."""
    pending: set[str] = set()
    answered: set[str] = set()
    for event in _run_events(invocation_context):
        long_running = event.long_running_tool_ids or set()
        pending.update(c.id for c in event.get_function_calls() if c.id and c.id in long_running)
        answered.update(r.id for r in event.get_function_responses() if r.id)
    return pending - answered


def _token_usage(events: Iterable[Event]) -> dict[str, int]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for event in events:
        metadata = event.usage_metadata
        if metadata is None:
            continue
        usage["prompt_tokens"] += metadata.prompt_token_count or 0
        usage["completion_tokens"] += metadata.candidates_token_count or 0
        usage["total_tokens"] += metadata.total_token_count or 0
    return usage


def _tool_calls(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the run's tool-call log with the approval answers folded in."""
    calls = [dict(call) for call in state.get(TOOL_CALLS_STATE_KEY) or []]
    by_call_id = {call.get("function_call_id"): call for call in calls}
    for approval in state.get(APPROVALS_STATE_KEY) or []:
        call = by_call_id.get(approval.get("function_call_id"))
        if call is None:
            calls.append(dict(approval))
            continue
        call["confirmed"] = approval.get("confirmed")
        call["approver"] = approval.get("approver")
    return calls


class ProvenancePlugin(BasePlugin):
    """Add the run's ``input_to``, ``generated`` and ``child_of`` edges and close its record."""

    def __init__(self, agent: "PrometheusAgent") -> None:
        super().__init__(name="prometheus_provenance")
        self._agent = agent
        self._edges: dict[int, set[Edge]] = {}
        self._resumed: set[int] = set()
        self._cancelled: dict[int, list[Any]] = {}
        self._closed: set[str] = set()
        self._tool_started: dict[str, float] = {}
        self._logged_no_record = False

    async def add_input(self, user_id: str, item_id: int) -> None:
        """Add ``input_to`` from the artifact item *item_id* to the run's execution record."""
        record_id = self._record_id()
        if record_id is not None:
            await self._write_edges(user_id, record_id, [(item_id, record_id, INPUT_TO)])

    async def add_generated(self, user_id: str, item_id: int) -> None:
        """Add ``generated`` from the run's execution record to the artifact item *item_id*."""
        record_id = self._record_id()
        if record_id is not None:
            await self._write_edges(user_id, record_id, [(record_id, item_id, GENERATED)])

    def mark_cancelled(self, artifact_ids: Iterable[Any] = ()) -> None:
        """Close the run's record as ``cancelled``, listing the artifacts that finished."""
        self._cancelled[self._agent.execution_record_id or 0] = list(artifact_ids)

    async def before_run_callback(self, *, invocation_context: InvocationContext) -> None:
        record_id = self._record_id()
        if record_id is None:
            return None
        if any(e.author != "user" for e in _run_events(invocation_context)):
            self._resumed.add(record_id)
        edges = [
            (item_id, record_id, INPUT_TO)
            for item_id in artifact_item_ids(_params_value(invocation_context))
        ]
        metadata = _request_metadata(invocation_context)
        parent_id = _item_id(metadata.get(PARENT_EXECUTION_RECORD_METADATA_KEY))
        if parent_id is not None:
            edges.append((record_id, parent_id, CHILD_OF))
        await self._write_edges(invocation_context.user_id, record_id, edges)
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        if tool_context.function_call_id:
            self._tool_started[tool_context.function_call_id] = time.monotonic()
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        function_call_id = tool_context.function_call_id
        started = self._tool_started.pop(function_call_id or "", None)
        calls = list(tool_context.state.get(TOOL_CALLS_STATE_KEY) or [])
        calls.append(
            {
                "tool": tool.name,
                "function_call_id": function_call_id,
                "arguments_sha256": _sha256(tool_args),
                "result_sha256": _sha256(result),
                "duration_ms": (
                    None if started is None else round((time.monotonic() - started) * 1000)
                ),
            }
        )
        tool_context.state[TOOL_CALLS_STATE_KEY] = calls
        if isinstance(result, dict) and result.get("status") == "cancelled":
            tool_context.state[_TOOL_CANCELLED_STATE_KEY] = True
        return None

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        await self._close(invocation_context, "succeeded")

    async def on_run_error_callback(
        self,
        *,
        invocation_context: InvocationContext,
        error: Exception,
    ) -> None:
        await self._close(invocation_context, "failed")

    def _record_id(self) -> int | None:
        record_id = self._agent.execution_record_id
        if record_id is None and not self._logged_no_record:
            self._logged_no_record = True
            logger.debug("No execution record for this run; provenance is not written")
        return record_id

    async def _write_edges(self, user_id: str, record_id: int, edges: list[Edge]) -> None:
        if not edges:
            return
        config = await deeplynx_config(self._agent, user_id)
        async with AsyncStorageClient(config) as client:
            known = self._edges.get(record_id)
            if known is None:
                known = set()
                if record_id in self._resumed:
                    for rel in await client.relationships.get_item_relationships(record_id):
                        known.add((rel.from_item_id, rel.to_item_id, rel.relationship_type))
                self._edges[record_id] = known
            new_edges = list(dict.fromkeys(edge for edge in edges if edge not in known))
            if not new_edges:
                return
            await client.relationships.bulk_create(
                [
                    RelationshipCreate(from_item_id=src, to_item_id=dst, relationship_type=kind)
                    for src, dst, kind in new_edges
                ]
            )
            known.update(new_edges)

    async def _close(self, invocation_context: InvocationContext, status: str) -> None:
        """Write the run's close status to session state and, once, to its record.

        A run that stopped on an unanswered long-running call (an approval or input pause)
        is not closed: its record stays open until the resumed run ends.
        """
        invocation_id = invocation_context.invocation_id
        if invocation_id in self._closed:
            return
        record_id = self._agent.execution_record_id
        state = invocation_context.session.state
        artifact_ids = self._cancelled.get(record_id or 0)
        if (
            artifact_ids is not None
            or invocation_context.is_aborted
            or state.get(_TOOL_CANCELLED_STATE_KEY)
        ):
            status = "cancelled"
        if status == "succeeded" and _pending_long_running_calls(invocation_context):
            logger.debug("Run %s paused on a long-running call; record left open", invocation_id)
            return
        self._closed.add(invocation_id)
        self._cancelled.pop(record_id or 0, None)

        if record_id is None:
            self._record_id()
        else:
            await self._close_record(invocation_context, record_id, status, artifact_ids)

        # after_run runs after the last event is stored, so the status reaches the session
        # store (and PrometheusMemoryService) only through an event of its own; a temp: key
        # would be trimmed from it.
        await invocation_context.session_service.append_event(
            invocation_context.session,
            Event(
                invocation_id=invocation_id,
                author=getattr(invocation_context.agent, "name", None) or self.name,
                actions=EventActions(state_delta={EXECUTION_STATUS_STATE_KEY: status}),
            ),
        )

    async def _close_record(
        self,
        invocation_context: InvocationContext,
        record_id: int,
        status: str,
        artifact_ids: list[Any] | None,
    ) -> None:
        """Update the execution record once with the run's close properties."""
        state = invocation_context.session.state
        self._edges.pop(record_id, None)
        self._resumed.discard(record_id)
        close: dict[str, Any] = {
            "status": status,
            "ended_at": datetime.now(UTC).isoformat(),
            "token_usage": _token_usage(_run_events(invocation_context)),
            "tool_calls": _tool_calls(state),
        }
        if artifact_ids is not None:
            close["artifact_ids"] = artifact_ids
        config = await deeplynx_config(self._agent, invocation_context.user_id)
        async with AsyncStorageClient(config) as client:
            existing = await client.items.get(record_id)
            if (existing.properties or {}).get("status") in _TERMINAL_STATUSES:
                # Another plugin instance (an earlier request of the same task) closed it.
                logger.debug("Execution record %s is already closed", record_id)
                return
            await client.items.update(
                record_id,
                ItemUpdate(
                    name=existing.name,
                    description=existing.description,
                    properties={**(existing.properties or {}), **close},
                    class_id=existing.class_id,
                    original_id=existing.original_id,
                ),
            )
        logger.info("Closed execution record %s as %s", record_id, status)
