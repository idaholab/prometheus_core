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

"""Unit tests for prometheus_api.agent.worker_pool."""

from __future__ import annotations

import asyncio

import pytest

from prometheus_api.agent.worker_pool import (
    UserWorkerPool,
    WorkerHandle,
    WorkerResult,
    WorkerTask,
)


# ---------------------------------------------------------------------------
# WorkerTask / WorkerResult types
# ---------------------------------------------------------------------------


def test_worker_task_repr_excludes_token():
    task = WorkerTask(
        task_id="t-1",
        user_id="alice",
        raw_token="super-secret-jwt",
        params={"query": "hi"},
        context_data={"context_id": "conv-1"},
    )
    r = repr(task)
    assert "super-secret-jwt" not in r
    assert "alice" in r


def test_worker_result_captures_error():
    result = WorkerResult(task_id="t-1", user_id="bob", error="boom")
    assert result.error == "boom"
    assert result.result is None


def test_worker_result_captures_result():
    result = WorkerResult(task_id="t-2", user_id="carol", result={"ok": True})
    assert result.result == {"ok": True}
    assert result.error is None


# ---------------------------------------------------------------------------
# WorkerHandle state
# ---------------------------------------------------------------------------


def test_worker_handle_not_alive_without_process():
    handle = WorkerHandle(user_id="dave")
    assert not handle.is_alive()


def test_worker_handle_terminate_is_noop_without_process():
    handle = WorkerHandle(user_id="eve")
    handle.terminate()  # Must not raise


# ---------------------------------------------------------------------------
# UserWorkerPool — capacity enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_raises_at_capacity(monkeypatch):
    """Pool respects USER_WORKER_MAX and raises when full."""
    monkeypatch.setenv("USER_WORKER_MAX", "1")
    pool = UserWorkerPool(
        execute_fn_module="prometheus_api.agent.worker_pool",
        execute_fn_name="_worker_loop",
    )

    # Inject a fake "alive" worker for user-A to fill the cap.
    fake_handle = WorkerHandle(user_id="alice")
    fake_handle.process = type("FakeProcess", (), {"is_alive": lambda s: True, "pid": 9999})()
    pool._workers["alice"] = fake_handle

    with pytest.raises(RuntimeError, match="capacity"):
        await pool._get_or_spawn("bob")


@pytest.mark.asyncio
async def test_pool_reaps_dead_worker_and_spawns_new(monkeypatch):
    """Dead workers are removed before checking capacity."""
    monkeypatch.setenv("USER_WORKER_MAX", "1")
    pool = UserWorkerPool(
        execute_fn_module="prometheus_api.agent.worker_pool",
        execute_fn_name="_worker_loop",
    )

    # Inject a dead worker.
    dead_handle = WorkerHandle(user_id="alice")
    dead_handle.process = type("FakeProcess", (), {"is_alive": lambda self: False, "pid": None})()
    pool._workers["alice"] = dead_handle

    # Spawning for "alice" should succeed (replaces the dead one).
    # We don't actually spawn a real subprocess here; just verify the
    # capacity check passes by patching spawn.
    spawned = []

    class FakeProcess:
        def __init__(self, *, target, args, daemon, name, **kw):
            spawned.append(name)

        def start(self):
            pass

        def is_alive(self):
            return True

        pid = 12345

    class FakeCtx:
        def Process(self, **kwargs):
            return FakeProcess(**kwargs)

    import prometheus_api.agent.worker_pool as wp_module

    monkeypatch.setattr(wp_module.multiprocessing, "get_context", lambda m: FakeCtx())

    handle = await pool._get_or_spawn("alice")
    assert handle.user_id == "alice"
    assert len(spawned) == 1


# ---------------------------------------------------------------------------
# PrometheusAgent.requires_user_isolation flag
# ---------------------------------------------------------------------------


def test_requires_user_isolation_defaults_false():
    from prometheus_api.agent import PrometheusAgent

    assert PrometheusAgent.requires_user_isolation is False


def test_requires_user_isolation_can_be_set():
    from prometheus_api.agent import PrometheusAgent

    class IsolatedAgent(PrometheusAgent):
        requires_user_isolation = True

        async def _execute(self, params, context, event_queue):
            return {}

    assert IsolatedAgent.requires_user_isolation is True
    assert PrometheusAgent.requires_user_isolation is False  # Base unchanged


# ---------------------------------------------------------------------------
# UserWorkerPool.start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_start_creates_reaper_task():
    pool = UserWorkerPool(
        execute_fn_module="prometheus_api.agent.worker_pool",
        execute_fn_name="_worker_loop",
    )
    assert pool._reaper_task is None
    await pool.start()
    assert pool._reaper_task is not None
    assert not pool._reaper_task.done()
    await pool.stop()
    # Allow asyncio to process the cancellation.
    await asyncio.sleep(0)
    assert pool._reaper_task.cancelled() or pool._reaper_task.done()


@pytest.mark.asyncio
async def test_pool_stop_terminates_workers():
    pool = UserWorkerPool(
        execute_fn_module="prometheus_api.agent.worker_pool",
        execute_fn_name="_worker_loop",
    )
    terminated = []

    class FakeHandle(WorkerHandle):
        def terminate(self):
            terminated.append(self.user_id)

    pool._workers["alice"] = FakeHandle("alice")
    pool._workers["bob"] = FakeHandle("bob")
    await pool.stop()
    assert set(terminated) == {"alice", "bob"}
    assert len(pool._workers) == 0
