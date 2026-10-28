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

"""Task Graph registry for background / long-running task tracking.

The client-agent owns a per-conversation *tree* of tasks: the root node is the
user's turn, and every dispatch to a specialist agent creates a child node. The
tree is the backbone for the ``/tasks`` command, completion notifications,
inspection, and — most importantly — *percolation*: a node stays non-terminal
while any descendant is still running, so the root node (what the user sees)
reflects the deepest thing still in flight.

State lives in Redis (the platform state layer). This module is intentionally
independent of the ``prometheus_api`` base image so it can ship and be tested
without a base-image rebuild.

See ``docs/dev-docs/background-tasks.md`` for the full design.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger(__name__)

# --- state vocabulary (aligned with the A2A SDK TaskState) -------------------

#: Terminal states a node can rest in.
TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})
#: Terminal states that represent a failure (vs. a clean completion).
FAILURE_STATES = frozenset({"failed", "canceled", "rejected"})

#: How long a node lives in Redis. Non-terminal nodes are refreshed on every
#: update so an active task never expires out from under a watcher.
NODE_TTL_SECONDS = int(os.getenv("TASK_NODE_TTL", str(24 * 60 * 60)))

#: Safety cap on percolation recursion depth (also guards against cycles).
_MAX_PERCOLATE_DEPTH = 64

_redis_client: Optional[redis.Redis] = None


def _client() -> redis.Redis:
    """Get or create the singleton Redis client for the task graph."""
    global _redis_client
    if _redis_client is None:
        from prometheus_api.redis_utils import create_redis_client

        _redis_client = create_redis_client(ping=False)
        if _redis_client is None:
            raise RuntimeError(
                "Redis client could not be created; check REDIS_URL/REDIS_PASSWORD"
            )
    return _redis_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- keys --------------------------------------------------------------------


def _graph_key(conversation_id: str) -> str:
    return f"tasks:graph:{conversation_id}"


def _node_key(conversation_id: str, task_id: str) -> str:
    return f"tasks:node:{conversation_id}:{task_id}"


def _roots_key(conversation_id: str) -> str:
    return f"tasks:roots:{conversation_id}"


def events_channel(conversation_id: str) -> str:
    """Redis pub/sub channel that carries state-change events for a conversation."""
    return f"tasks:events:{conversation_id}"


# --- node model --------------------------------------------------------------


@dataclass
class TaskNode:
    """One node in a conversation's task tree.

    ``own_state`` is what this node's *own* work reports; ``state`` is the
    *effective* state after considering children (percolation). For a leaf with
    no children the two are identical.
    """

    task_id: str
    conversation_id: str
    parent_task_id: Optional[str] = None
    child_task_ids: List[str] = field(default_factory=list)

    agent: Optional[str] = None
    skill: Optional[str] = None
    title: str = ""

    own_state: str = "submitted"
    state: str = "submitted"
    is_background: bool = False
    waiting_on: List[str] = field(default_factory=list)
    fail_fast: bool = True

    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    updated_at: str = field(default_factory=_now)
    finished_at: Optional[str] = None

    last_status_message: str = ""
    progress: Optional[float] = None

    result_ref: Optional[str] = None
    error: Optional[str] = None

    # The ADK run of a detached turn; ``invocation_id`` resumes it after a restart.
    # Nodes stored before these fields existed load with ``None``.
    invocation_id: Optional[str] = None
    adk_session_id: Optional[str] = None
    # The user the ADK session belongs to; a resume runs as the same user.
    adk_user_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskNode":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# --- persistence -------------------------------------------------------------


def save_node(node: TaskNode) -> None:
    """Persist a node and register it in the conversation's graph set."""
    try:
        client = _client()
        key = _node_key(node.conversation_id, node.task_id)
        pipe = client.pipeline()
        pipe.set(key, json.dumps(node.to_dict(), default=str))
        pipe.expire(key, NODE_TTL_SECONDS)
        pipe.sadd(_graph_key(node.conversation_id), node.task_id)
        pipe.expire(_graph_key(node.conversation_id), NODE_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:  # never let task tracking break the request path
        logger.warning("[TASKGRAPH] Failed to save node %s: %s", node.task_id, exc)


def get_node(conversation_id: str, task_id: str) -> Optional[TaskNode]:
    try:
        data = _client().get(_node_key(conversation_id, task_id))
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to read node %s: %s", task_id, exc)
        return None
    if not data:
        return None
    try:
        return TaskNode.from_dict(json.loads(data))
    except Exception as exc:
        logger.warning("[TASKGRAPH] Corrupt node %s: %s", task_id, exc)
        return None


def list_nodes(conversation_id: str) -> List[TaskNode]:
    """Return every node in a conversation's task graph."""
    try:
        task_ids = _client().smembers(_graph_key(conversation_id))
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to list graph %s: %s", conversation_id, exc)
        return []
    nodes = [get_node(conversation_id, tid) for tid in task_ids]
    return [n for n in nodes if n is not None]


def list_resumable_nodes() -> List[TaskNode]:
    """Every unfinished node, across conversations, that records an ADK invocation."""
    nodes: List[TaskNode] = []
    try:
        client = _client()
        cursor = 0
        while True:
            # One MGET per SCAN batch instead of one GET per node.
            cursor, keys = client.scan(cursor=cursor, match="tasks:node:*")
            for key, data in zip(keys, client.mget(keys) if keys else []):
                if not data:
                    continue
                try:
                    node = TaskNode.from_dict(json.loads(data))
                except Exception as exc:
                    logger.warning("[TASKGRAPH] Corrupt node %s: %s", key, exc)
                    continue
                if node.invocation_id and node.state not in TERMINAL_STATES:
                    nodes.append(node)
            if not cursor:
                break
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to scan nodes: %s", exc)
    return nodes


def list_roots(conversation_id: str) -> List[str]:
    try:
        return list(_client().lrange(_roots_key(conversation_id), 0, -1))
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to list roots %s: %s", conversation_id, exc)
        return []


def _publish_event(conversation_id: str, event: Dict[str, Any]) -> None:
    try:
        _client().publish(
            events_channel(conversation_id), json.dumps(event, default=str)
        )
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to publish event: %s", exc)


def _result_key(conversation_id: str, task_id: str) -> str:
    return f"tasks:result:{conversation_id}:{task_id}"


def store_result(conversation_id: str, task_id: str, payload: Dict[str, Any]) -> None:
    """Persist the final response payload of a backgrounded task for later delivery."""
    try:
        client = _client()
        key = _result_key(conversation_id, task_id)
        client.set(key, json.dumps(payload, default=str))
        client.expire(key, NODE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to store result for %s: %s", task_id, exc)


def get_result(conversation_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a stored backgrounded-task result payload, if any."""
    try:
        data = _client().get(_result_key(conversation_id, task_id))
    except Exception as exc:
        logger.warning("[TASKGRAPH] Failed to read result for %s: %s", task_id, exc)
        return None
    if not data:
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


# --- mutations ---------------------------------------------------------------


def create_node(
    *,
    task_id: str,
    conversation_id: str,
    parent_task_id: Optional[str] = None,
    agent: Optional[str] = None,
    skill: Optional[str] = None,
    title: str = "",
    is_background: bool = False,
    fail_fast: bool = True,
) -> TaskNode:
    """Create and persist a new task node, linking it to its parent (if any)."""
    node = TaskNode(
        task_id=task_id,
        conversation_id=conversation_id,
        parent_task_id=parent_task_id,
        agent=agent,
        skill=skill,
        title=title or (f"{agent}:{skill}" if agent else "request"),
        own_state="submitted",
        state="submitted",
        is_background=is_background,
        fail_fast=fail_fast,
        started_at=_now(),
    )
    save_node(node)

    if parent_task_id:
        parent = get_node(conversation_id, parent_task_id)
        if parent and task_id not in parent.child_task_ids:
            parent.child_task_ids.append(task_id)
            save_node(parent)
            _reconcile(conversation_id, parent_task_id)
    else:
        try:
            client = _client()
            client.rpush(_roots_key(conversation_id), task_id)
            client.expire(_roots_key(conversation_id), NODE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("[TASKGRAPH] Failed to register root %s: %s", task_id, exc)

    _publish_event(
        conversation_id,
        {
            "type": "node-created",
            "task_id": task_id,
            "parent_task_id": parent_task_id,
            "state": node.state,
            "title": node.title,
            "agent": agent,
            "ts": node.created_at,
        },
    )
    return node


def update_own_state(
    conversation_id: str,
    task_id: str,
    *,
    own_state: Optional[str] = None,
    message: Optional[str] = None,
    progress: Optional[float] = None,
    is_background: Optional[bool] = None,
    result_ref: Optional[str] = None,
    error: Optional[str] = None,
    invocation_id: Optional[str] = None,
    adk_session_id: Optional[str] = None,
    adk_user_id: Optional[str] = None,
) -> Optional[TaskNode]:
    """Update a node's *own* reported state, then percolate the effect upward.

    This is the single entry point a watcher calls when a sub-agent emits a
    status/artifact/terminal event.
    """
    node = get_node(conversation_id, task_id)
    if node is None:
        return None

    direct_changed = False
    if own_state is not None and own_state != node.own_state:
        node.own_state = own_state
        direct_changed = True
    if message is not None and message != node.last_status_message:
        node.last_status_message = message
        direct_changed = True
    if progress is not None and progress != node.progress:
        node.progress = progress
        direct_changed = True
    if is_background is not None and is_background != node.is_background:
        node.is_background = is_background
        direct_changed = True
    if result_ref is not None and result_ref != node.result_ref:
        node.result_ref = result_ref
        direct_changed = True
    if error is not None and error != node.error:
        node.error = error
        direct_changed = True
    if invocation_id is not None and invocation_id != node.invocation_id:
        node.invocation_id = invocation_id
        direct_changed = True
    if adk_session_id is not None and adk_session_id != node.adk_session_id:
        node.adk_session_id = adk_session_id
        direct_changed = True
    if adk_user_id is not None and adk_user_id != node.adk_user_id:
        node.adk_user_id = adk_user_id
        direct_changed = True
    if direct_changed:
        save_node(node)

    return _reconcile(conversation_id, task_id, _direct_changed=direct_changed)


def _root_of(conversation_id: str, task_id: str) -> str:
    """Walk parents to the root, for tagging events."""
    seen: set[str] = set()
    current = task_id
    for _ in range(_MAX_PERCOLATE_DEPTH):
        if current in seen:
            break
        seen.add(current)
        node = get_node(conversation_id, current)
        if node is None or not node.parent_task_id:
            return current
        current = node.parent_task_id
    return current


def _deepest_blocking_message(
    conversation_id: str, node: TaskNode, depth: int = 0
) -> str:
    """Derive a human message naming the deepest still-running descendant."""
    if depth > _MAX_PERCOLATE_DEPTH:
        return node.last_status_message
    for child_id in node.waiting_on:
        child = get_node(conversation_id, child_id)
        if child is None:
            continue
        if child.waiting_on:
            return _deepest_blocking_message(conversation_id, child, depth + 1)
        label = child.title or child.agent or child_id[:8]
        detail = f" — {child.last_status_message}" if child.last_status_message else ""
        return f"waiting on {label}{detail}"
    return node.last_status_message


def _effective_state(node: TaskNode, child_states: List[str]) -> str:
    """Compute a node's effective state from its own state and its children."""
    waiting = [s for s in child_states if s not in TERMINAL_STATES]
    own = node.own_state

    if own in FAILURE_STATES:
        return own
    if own == "completed":
        if waiting:
            return "working"  # own work done, but children still running
        if node.fail_fast and any(s == "failed" for s in child_states):
            return "failed"
        return "completed"
    # own work still in progress (submitted / working / input-required)
    if waiting:
        return "working"
    return own


def _reconcile(
    conversation_id: str,
    task_id: str,
    _visited: Optional[set[str]] = None,
    _depth: int = 0,
    _direct_changed: bool = False,
) -> Optional[TaskNode]:
    """Recompute a node's effective state and propagate changes to its parent.

    Idempotent: only persists/publishes/propagates when something actually
    changed, which also terminates the cascade.
    """
    if _depth > _MAX_PERCOLATE_DEPTH:
        logger.warning("[TASKGRAPH] Percolation depth cap hit at %s", task_id)
        return None
    _visited = _visited or set()
    if task_id in _visited:
        return None
    _visited.add(task_id)

    node = get_node(conversation_id, task_id)
    if node is None:
        return None

    child_states: List[str] = []
    waiting_on: List[str] = []
    for child_id in node.child_task_ids:
        child = get_node(conversation_id, child_id)
        if child is None:
            continue
        child_states.append(child.state)
        if child.state not in TERMINAL_STATES:
            waiting_on.append(child_id)

    new_state = _effective_state(node, child_states)
    new_message = node.last_status_message
    if waiting_on:
        new_message = _deepest_blocking_message(
            conversation_id, TaskNode(**{**node.to_dict(), "waiting_on": waiting_on})
        )

    changed = (
        _direct_changed
        or new_state != node.state
        or waiting_on != node.waiting_on
        or new_message != node.last_status_message
    )
    if not changed:
        return node

    became_terminal = new_state in TERMINAL_STATES and node.state not in TERMINAL_STATES

    node.state = new_state
    node.waiting_on = waiting_on
    if waiting_on:
        node.last_status_message = new_message
    node.updated_at = _now()
    if became_terminal:
        node.finished_at = _now()
    save_node(node)

    if new_state in FAILURE_STATES:
        event_type = "node-failed"
    elif became_terminal:
        event_type = "node-completed"
    else:
        event_type = "node-updated"
    _publish_event(
        conversation_id,
        {
            "type": event_type,
            "task_id": task_id,
            "parent_task_id": node.parent_task_id,
            "root_task_id": _root_of(conversation_id, task_id),
            "state": new_state,
            "title": node.title,
            "message": node.last_status_message,
            "progress": node.progress,
            "result_ref": node.result_ref,
            "ts": node.updated_at,
        },
    )

    if node.parent_task_id:
        _reconcile(conversation_id, node.parent_task_id, _visited, _depth + 1)

    return node


# --- read helpers for /tasks -------------------------------------------------


def build_tree(conversation_id: str) -> List[Dict[str, Any]]:
    """Return root nodes with nested children, for rendering ``/tasks``."""
    nodes = {n.task_id: n for n in list_nodes(conversation_id)}

    def render(task_id: str, seen: set[str]) -> Optional[Dict[str, Any]]:
        if task_id in seen or task_id not in nodes:
            return None
        seen.add(task_id)
        node = nodes[task_id]
        return {
            **node.to_dict(),
            "children": [
                child
                for cid in node.child_task_ids
                if (child := render(cid, seen)) is not None
            ],
        }

    seen: set[str] = set()
    roots = [r for r in list_roots(conversation_id) if r in nodes]
    # Include any orphan nodes whose parent is missing, so nothing is hidden.
    roots += [
        n.task_id
        for n in nodes.values()
        if not n.parent_task_id and n.task_id not in roots
    ]
    trees = [tree for r in roots if (tree := render(r, seen)) is not None]
    return trees
