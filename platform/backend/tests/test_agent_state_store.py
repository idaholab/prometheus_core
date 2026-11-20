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

"""Agent state store (app/services/agent_state.py): ownership, versions, TTL, races."""

from __future__ import annotations

import asyncio

import pytest

from app.services.agent_state import AgentStateError, AgentStateStore, Owner

CONV = "conv-1"
ALICE = Owner(user_id="alice", agent="thermal-agent", conversation_id=CONV)


@pytest.fixture
def store(fake_redis) -> AgentStateStore:
    return AgentStateStore(fake_redis, ttl_seconds=60, max_bytes=1024)


async def test_put_get_delete(store, fake_redis):
    created = await store.put("k", ALICE, {"a": 1}, expected_version=None)
    assert created.version == 1
    replaced = await store.put("k", ALICE, {"a": 2}, expected_version=1)
    assert (replaced.version, replaced.created_at) == (2, created.created_at)
    assert 0 < await fake_redis.ttl("k") <= 60
    got = await store.get("k", ALICE)
    assert got is not None and got.state == {"a": 2}
    await store.delete("k", ALICE)
    assert await store.get("k", ALICE) is None


@pytest.mark.parametrize(
    "other",
    [
        Owner(user_id="bob", agent="thermal-agent", conversation_id=CONV),
        Owner(user_id="alice", agent="osti-agent", conversation_id=CONV),
        Owner(user_id="alice", agent="thermal-agent", conversation_id="conv-2"),
    ],
)
async def test_other_owner_sees_nothing_and_cannot_write(store, other):
    await store.put("k", ALICE, {"a": 1}, expected_version=None)
    assert await store.get("k", other) is None
    with pytest.raises(AgentStateError) as exc:
        await store.put("k", other, {}, expected_version=None)
    assert exc.value.status == 404
    await store.delete("k", other)
    assert await store.get("k", ALICE) is not None


async def test_size_limit(store):
    with pytest.raises(AgentStateError) as exc:
        await store.put("k", ALICE, {"x": "y" * 2048}, expected_version=None)
    assert exc.value.status == 413


async def test_racing_replaces_have_one_winner(interleaving_redis):
    store = AgentStateStore(interleaving_redis, ttl_seconds=60, max_bytes=1024)
    owner = ALICE
    await store.put("k", owner, {"n": 0}, expected_version=None)

    async def bump(n: int) -> int:
        try:
            await store.put("k", owner, {"n": n}, expected_version=1)
            return n
        except AgentStateError as exc:
            assert exc.status == 409
            return -1

    results = await asyncio.gather(*(bump(i) for i in range(1, 6)))
    winners = [r for r in results if r > 0]
    assert len(winners) == 1
    record = await store.get("k", owner)
    assert record is not None and record.version == 2 and record.state == {"n": winners[0]}
