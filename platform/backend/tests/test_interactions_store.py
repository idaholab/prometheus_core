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

"""Interaction store (app/services/interactions.py): create, resolve, expiry, wait."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.services import interactions as ia
from app.services.interactions import InteractionError, InteractionStore, NotPending

CONV = "conv-1"


@pytest.fixture
def store(fake_redis) -> InteractionStore:
    return InteractionStore(fake_redis)


async def test_task_can_ask_again_after_resolution(store):
    first = await store.create(**_args())
    await store.answer(first.record.id, user_id="alice", accept=True)
    second = await store.create(**_args())
    assert second.record.id != first.record.id


async def test_per_user_cap(store):
    for i in range(ia.MAX_PENDING_PER_USER):
        await store.create(**_args(task_id=f"t{i}"))
    with pytest.raises(InteractionError) as exc:
        await store.create(**_args(task_id="one-too-many"))
    assert exc.value.status == 429


def _args(**overrides: Any) -> dict[str, Any]:
    return {
        "user_id": "alice",
        "agent": "thermal-agent",
        "conversation_id": CONV,
        "task_id": "task-1",
        "skill": "run",
        "message": "ok?",
        "timeout_seconds": 60,
        **overrides,
    }


async def test_long_poll_wakes_on_answer(store):
    created = await store.create(**_args())

    async def answer_soon() -> None:
        await asyncio.sleep(0.05)
        await store.answer(created.record.id, user_id="alice", accept=False)

    task = asyncio.create_task(answer_soon())
    started = asyncio.get_running_loop().time()
    record = await store.wait(created.record.id, 5)
    await task
    assert record.state == "declined"
    assert asyncio.get_running_loop().time() - started < 2


async def test_long_poll_times_out_pending(store):
    created = await store.create(**_args())
    record = await store.wait(created.record.id, 0.05)
    assert record.state == "pending"


async def test_expired_on_read(store, monkeypatch):
    created = await store.create(**_args(timeout_seconds=1))
    later = datetime.now(timezone.utc) + timedelta(seconds=2)
    monkeypatch.setattr(ia, "_now", lambda: later)

    stored = await store.get(created.record.id)
    assert stored is not None
    assert (stored.record.state, stored.record.resolved_by) == ("expired", "timeout")
    with pytest.raises(NotPending):
        await store.answer(created.record.id, user_id="alice", accept=True)
    assert await store.list_pending("alice") == []


async def test_long_poll_returns_expired_at_expiry(store):
    created = await store.create(**_args(timeout_seconds=1))
    record = await store.wait(created.record.id, 5)
    assert record.state == "expired"


async def test_accept_racing_cancel_has_one_winner(interleaving_redis):
    store = InteractionStore(interleaving_redis)
    created = await store.create(**_args())

    async def accept() -> str:
        try:
            return (await store.answer(created.record.id, user_id="alice", accept=True)).state
        except NotPending:
            return "lost"

    async def cancel() -> str:
        record = await store.cancel_for_task("task-1")
        return record.state if record else "lost"

    results = await asyncio.gather(accept(), cancel())
    assert sorted(results) in (["accepted", "lost"], ["cancelled", "lost"])
    final = await store.get(created.record.id)
    assert final is not None and final.record.state in ("accepted", "cancelled")


async def test_cancel_for_task_without_pending_is_noop(store):
    assert await store.cancel_for_task("nothing") is None
