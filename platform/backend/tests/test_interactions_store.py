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


# --------------------------------------------------------------------------- #
# Refusals and edge paths
# --------------------------------------------------------------------------- #


async def test_create_rejects_oversized_and_empty_messages(store):
    with pytest.raises(InteractionError) as exc:
        await store.create(**_args(message="x" * (ia.MAX_MESSAGE_BYTES + 1)))
    assert exc.value.status == 413
    with pytest.raises(InteractionError) as exc:
        await store.create(**_args(message="  \n"))
    assert exc.value.status == 422


async def test_second_pending_request_for_a_task_is_refused(store):
    await store.create(**_args())
    with pytest.raises(InteractionError) as exc:
        await store.create(**_args())
    assert exc.value.status == 409


async def test_guard_vanishing_between_set_and_get_is_refused(store, fake_redis, monkeypatch):
    """SET NX lost to a guard that expired before the follow-up GET: refuse, don't guess."""
    real_set = fake_redis.set

    async def set_loses(key: str, *args: Any, nx: bool = False, **kwargs: Any) -> Any:
        return None if nx else await real_set(key, *args, **kwargs)

    monkeypatch.setattr(fake_redis, "set", set_loses)
    with pytest.raises(InteractionError) as exc:
        await store.create(**_args())
    assert exc.value.status == 409


async def test_stale_task_guard_is_taken_over(store, fake_redis):
    """A guard naming a resolved request (it outlived the record's resolve) doesn't block."""
    first = await store.create(**_args())
    await store.answer(first.record.id, user_id="alice", accept=True)
    await fake_redis.set(ia.task_pending_key("task-1"), first.record.id)

    second = await store.create(**_args())
    assert await fake_redis.get(ia.task_pending_key("task-1")) == second.record.id
    assert [r.id for r in await store.list_pending("alice")] == [second.record.id]


async def test_get_unknown_is_none(store):
    assert await store.get("ia_missing") is None


async def test_expiry_lost_to_a_concurrent_resolve_returns_the_winner(store, monkeypatch):
    created = await store.create(**_args(timeout_seconds=1))
    await store.resolve(created.record.id, "accepted", "user")
    stale = await store.get(created.record.id)
    assert stale is not None
    pending_view = stale.record.model_copy(update={"state": "pending"})

    # The first read still sees "pending" past expiry; its expire then loses the CAS.
    real_from_hash = ia._from_hash
    calls = 0

    def first_read_is_stale(raw: dict[str, Any]) -> ia.StoredInteraction:
        nonlocal calls
        calls += 1
        out = real_from_hash(raw)
        return ia.StoredInteraction(pending_view, out.user_id, out.agent_token_hash, out.seq) if calls == 1 else out

    later = datetime.now(timezone.utc) + timedelta(seconds=2)
    monkeypatch.setattr(ia, "_now", lambda: later)
    monkeypatch.setattr(ia, "_from_hash", first_read_is_stale)
    got = await store.get(created.record.id)
    assert got is not None and got.record.state == "accepted"


async def test_list_pending_drops_ids_whose_record_is_gone(store, fake_redis):
    await fake_redis.sadd(ia.user_pending_key("alice"), "ia_gone")
    assert await store.list_pending("alice") == []
    assert await fake_redis.smembers(ia.user_pending_key("alice")) == set()


async def test_get_for_agent_checks_agent_and_token(store):
    created = await store.create(**_args())
    rid = created.record.id
    got = await store.get_for_agent(rid, agent="thermal-agent", agent_token=created.agent_token)
    assert got.record.id == rid
    for agent, token, target in (
        ("other-agent", created.agent_token, rid),
        ("thermal-agent", "wrong-token", rid),
        ("thermal-agent", created.agent_token, "ia_missing"),
    ):
        with pytest.raises(InteractionError) as exc:
            await store.get_for_agent(target, agent=agent, agent_token=token)
        assert exc.value.status == 404


async def test_resolve_unknown_is_404(store):
    with pytest.raises(InteractionError) as exc:
        await store.resolve("ia_missing", "cancelled", "system")
    assert exc.value.status == 404


async def test_resolve_gives_up_when_the_record_keeps_changing(store, monkeypatch):
    from redis.exceptions import WatchError

    created = await store.create(**_args())
    monkeypatch.setattr(ia, "_WATCH_RETRIES", 0)
    with pytest.raises(WatchError):
        await store.resolve(created.record.id, "cancelled", "system")


async def test_resolve_retries_after_a_watch_conflict(store, monkeypatch):
    from redis.asyncio.client import Pipeline
    from redis.exceptions import WatchError

    created = await store.create(**_args())
    real_execute = Pipeline.execute
    conflicts = 0

    async def conflict_once(self: Pipeline, *args: Any, **kwargs: Any) -> Any:
        nonlocal conflicts
        if self.watching and conflicts == 0:
            conflicts += 1
            await self.reset()
            raise WatchError("changed")
        return await real_execute(self, *args, **kwargs)

    monkeypatch.setattr(Pipeline, "execute", conflict_once)
    resolved = await store.resolve(created.record.id, "cancelled", "system")
    assert (conflicts, resolved.record.state) == (1, "cancelled")


async def test_answer_by_another_user_is_404(store):
    created = await store.create(**_args())
    with pytest.raises(InteractionError) as exc:
        await store.answer(created.record.id, user_id="mallory", accept=True)
    assert exc.value.status == 404
    with pytest.raises(InteractionError):
        await store.answer("ia_missing", user_id="alice", accept=True)


async def test_wait_on_unknown_is_404(store):
    with pytest.raises(InteractionError) as exc:
        await store.wait("ia_missing", 0.05)
    assert exc.value.status == 404


async def test_wait_on_resolved_returns_at_once(store):
    created = await store.create(**_args())
    await store.answer(created.record.id, user_id="alice", accept=True)
    record = await store.wait(created.record.id, 5)
    assert record.state == "accepted"


async def test_wait_on_record_deleted_mid_wait_is_404(store, fake_redis):
    created = await store.create(**_args())
    rid = created.record.id

    async def delete_soon() -> None:
        await asyncio.sleep(0.05)
        await fake_redis.delete(ia.record_key(rid))
        await fake_redis.publish(ia.resolved_channel(rid), "cancelled")

    task = asyncio.create_task(delete_soon())
    with pytest.raises(InteractionError) as exc:
        await store.wait(rid, 5)
    await task
    assert exc.value.status == 404
