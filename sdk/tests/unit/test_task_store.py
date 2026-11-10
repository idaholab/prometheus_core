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

"""Tests for RedisTaskStore.

These run against the in-memory fallback path (forced via an unreachable Redis
URL, mirroring tests/unit/test_artifacts.py), so they validate the save/get/delete
round-trip and Task (de)serialization without a live Redis.
"""

from __future__ import annotations

import pytest

from a2a.types import ListTasksRequest, Task, TaskState, TaskStatus

from prometheus_api.agent.task_store import TERMINAL_STATES, RedisTaskStore

# Unreachable port → redis_client returns None → memory fallback is exercised.
UNREACHABLE = "redis://localhost:0"


def _task(task_id: str, state: TaskState = TaskState.TASK_STATE_WORKING) -> Task:
    return Task(
        id=task_id,
        context_id="conv-1",
        status=TaskStatus(state=state),
    )


@pytest.fixture()
def store() -> RedisTaskStore:
    return RedisTaskStore(redis_url=UNREACHABLE, ttl_seconds=60)


async def test_save_then_get_roundtrips(store: RedisTaskStore) -> None:
    task = _task("t-1")
    await store.save(task)

    loaded = await store.get("t-1")
    assert loaded is not None
    assert loaded.id == "t-1"
    assert loaded.context_id == "conv-1"
    assert loaded.status.state == TaskState.TASK_STATE_WORKING


async def test_get_missing_returns_none(store: RedisTaskStore) -> None:
    assert await store.get("does-not-exist") is None


async def test_save_overwrites(store: RedisTaskStore) -> None:
    await store.save(_task("t-2", TaskState.TASK_STATE_SUBMITTED))
    await store.save(_task("t-2", TaskState.TASK_STATE_COMPLETED))

    loaded = await store.get("t-2")
    assert loaded is not None
    assert loaded.status.state == TaskState.TASK_STATE_COMPLETED


async def test_delete_removes(store: RedisTaskStore) -> None:
    await store.save(_task("t-3"))
    await store.delete("t-3")
    assert await store.get("t-3") is None
    # Deleting a nonexistent task is a no-op, not an error.
    await store.delete("t-3")


async def test_corrupt_payload_returns_none(store: RedisTaskStore) -> None:
    # Inject a non-Task JSON blob directly into the memory fallback.
    store._memory_store["t-bad"] = '{"not": "a task"}'
    assert await store.get("t-bad") is None


async def test_list_filters_and_paginates_tasks(store: RedisTaskStore) -> None:
    await store.save(_task("t-1", TaskState.TASK_STATE_WORKING))
    await store.save(_task("t-2", TaskState.TASK_STATE_COMPLETED))

    completed = await store.list(
        ListTasksRequest(
            context_id="conv-1",
            status=TaskState.TASK_STATE_COMPLETED,
            page_size=1,
        )
    )

    assert completed.total_size == 1
    assert completed.page_size == 1
    assert [task.id for task in completed.tasks] == ["t-2"]


def test_terminal_states_set() -> None:
    assert TaskState.TASK_STATE_COMPLETED in TERMINAL_STATES
    assert TaskState.TASK_STATE_FAILED in TERMINAL_STATES
    assert TaskState.TASK_STATE_CANCELED in TERMINAL_STATES
    assert TaskState.TASK_STATE_REJECTED in TERMINAL_STATES
    assert TaskState.TASK_STATE_WORKING not in TERMINAL_STATES
