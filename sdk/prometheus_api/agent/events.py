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

"""A2A event helpers shared by Prometheus agent executors and agent helpers."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from a2a.helpers import new_task
from a2a.server.agent_execution.context import RequestContext
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value


STOPPING_TASK_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_INPUT_REQUIRED,
        TaskState.TASK_STATE_AUTH_REQUIRED,
        TaskState.TASK_STATE_REJECTED,
    }
)


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def normalize_producer_agent_id(agent_name: str) -> str:
    """Normalize agent names into stable producer identifiers."""
    return agent_name.lower().replace(" ", "-")


def build_artifact_metadata(
    *,
    context: RequestContext,
    agent_name: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the canonical Prometheus artifact metadata envelope."""
    metadata = {
        "conversation_id": str(getattr(context, "context_id", "") or ""),
        "producer_agent_id": normalize_producer_agent_id(agent_name),
        "created_at": utc_now_iso(),
    }
    metadata.update(dict(extra or {}))
    return metadata


def context_task_id(context: RequestContext) -> str:
    """Return a non-null task ID for A2A event models."""
    return str(getattr(context, "task_id", "") or "")


def context_id(context: RequestContext) -> str:
    """Return a non-null context ID for A2A event models."""
    return str(getattr(context, "context_id", "") or "")


def build_initial_task(context: RequestContext) -> Task:
    """Build the initial ``Task`` for a new request, required before any v1 task update events."""
    message = getattr(context, "message", None)
    history = [message] if message is not None else []
    return new_task(
        task_id=context_task_id(context),
        context_id=context_id(context),
        state=TaskState.TASK_STATE_SUBMITTED,
        history=history,
    )


def is_stopping_status_event(event: Any) -> bool:
    """Return whether a v1.0 status event stops automatic agent finalization."""
    return isinstance(event, TaskStatusUpdateEvent) and event.status.state in STOPPING_TASK_STATES


def build_status_update_event(
    *,
    context: RequestContext,
    state: TaskState,
    final: bool,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TaskStatusUpdateEvent:
    """Build a task status update event with an optional text message.

    ``final`` remains in the public helper signature for source compatibility.
    A2A v1 derives finality from the task state and no longer has a ``final``
    field on ``TaskStatusUpdateEvent``.
    """
    task_id = context_task_id(context)
    current_context_id = context_id(context)
    status_message = None
    if message:
        status_message = Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_AGENT,
            parts=[Part(text=message)],
            context_id=current_context_id,
            task_id=task_id,
        )

    return TaskStatusUpdateEvent(
        task_id=task_id,
        context_id=current_context_id,
        status=TaskStatus(state=state, message=status_message),
        metadata=metadata,
    )


async def emit_status_update(
    *,
    context: RequestContext,
    event_queue: Any,
    state: TaskState,
    final: bool,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Build and enqueue a task status update event."""
    await event_queue.enqueue_event(
        build_status_update_event(
            context=context,
            state=state,
            final=final,
            message=message,
            metadata=metadata,
        )
    )


def build_data_artifact_event(
    *,
    context: RequestContext,
    agent_name: str,
    payload: Any,
    name: str = "result",
    description: Optional[str] = None,
    json_type: Optional[str] = None,
    artifact_id: Optional[str] = None,
    append: bool = False,
    last_chunk: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[TaskArtifactUpdateEvent, str]:
    """Build an inline JSON (data) artifact event. Pure construction — no I/O.

    Returns ``(event, artifact_id)``; the caller may reuse ``artifact_id`` for
    subsequent chunked appends. Shared by ``PrometheusAgent.send_json_artifact``
    (loop side) and ``PrometheusWorker.emit_json_artifact`` (worker side) so both
    enqueue identically-shaped events.
    """
    artifact_id = artifact_id or str(uuid.uuid4())
    part_metadata = {"mime_type": "application/json", **dict(metadata or {})}
    if json_type:
        part_metadata["json_type"] = json_type

    event = TaskArtifactUpdateEvent(
        task_id=context_task_id(context),
        context_id=context_id(context),
        artifact=Artifact(
            artifact_id=artifact_id,
            name=name,
            description=description,
            metadata=build_artifact_metadata(context=context, agent_name=agent_name),
            parts=[
                Part(
                    data=ParseDict(
                        payload if isinstance(payload, dict) else {"value": payload},
                        Value(),
                    ),
                    metadata=part_metadata,
                )
            ],
        ),
        append=append,
        last_chunk=last_chunk,
        metadata=metadata,
    )
    return event, artifact_id
