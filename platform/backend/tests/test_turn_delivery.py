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

"""A chat turn's result reaches the client by turn id, not only through the POST reply.

The client names each turn (``turn_id`` in the request). When the turn finishes, the
backend stores the response under that id and publishes ``turn_done`` with it, so a
client whose POST reply was dropped still settles the turn; ``GET /api/chat/turns/{id}``
answers a client whose event stream was down at that moment too (issue #334).
"""

from typing import Any

from fastapi.testclient import TestClient

from app.contract import ChatMessageResponse, ChatStatus, TurnDoneEvent
from app.services import chat as chat_service
from app.sessions import SessionStore

TURN = "turn-0123456789"


def _authed_client(monkeypatch, sid: str = "sid-turns", user: str = "alice") -> TestClient:
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    token = security.issue_token(security.User(identifier=user), sid=sid)
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client


def _capture_published(monkeypatch, event_bus) -> list[Any]:
    published: list[Any] = []

    async def publish(sid, event):
        published.append((sid, event))

    monkeypatch.setattr(event_bus, "publish", publish)
    return published


def _answer(calls: list[str]):
    async def handle_turn(client_arg, store_arg, sid_arg, *, turn_id, query, **kwargs):
        calls.append(turn_id)
        return ChatMessageResponse(turn_id=turn_id, status=ChatStatus.ANSWER, response_text="42")

    return handle_turn


def test_client_turn_id_is_used_for_the_turn(monkeypatch):
    client = _authed_client(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(chat_service, "handle_turn", _answer(calls))

    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})

    assert resp.status_code == 200
    assert resp.json()["turn_id"] == TURN
    assert calls == [TURN]


def test_server_mints_a_turn_id_when_the_client_sends_none(monkeypatch):
    client = _authed_client(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(chat_service, "handle_turn", _answer(calls))

    resp = client.post("/api/chat/messages", json={"query": "hi"})

    assert resp.status_code == 200
    assert resp.json()["turn_id"] == calls[0]


def test_malformed_turn_id_is_rejected(monkeypatch):
    client = _authed_client(monkeypatch)
    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": "bad id!"})
    assert resp.status_code == 422


def test_a_repeated_turn_id_is_a_conflict_and_does_not_rerun_the_agent(monkeypatch):
    """A retried POST must not start a second agent turn."""
    client = _authed_client(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(chat_service, "handle_turn", _answer(calls))

    assert client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN}).status_code == 200
    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})

    assert resp.status_code == 409
    assert calls == [TURN]


def test_finished_turn_publishes_turn_done_with_the_post_response(monkeypatch, event_bus):
    client = _authed_client(monkeypatch)
    published = _capture_published(monkeypatch, event_bus)
    monkeypatch.setattr(chat_service, "handle_turn", _answer([]))

    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})

    done = [e for sid, e in published if isinstance(e, TurnDoneEvent)]
    assert [sid for sid, e in published if isinstance(e, TurnDoneEvent)] == ["sid-turns"]
    assert len(done) == 1
    assert done[0].turn_id == TURN
    assert done[0].response.model_dump(mode="json") == resp.json()


def test_failed_turn_is_stored_and_published_as_its_error_response(monkeypatch, event_bus):
    client = _authed_client(monkeypatch)
    published = _capture_published(monkeypatch, event_bus)

    async def boom(*args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(chat_service, "handle_turn", boom)

    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})
    assert resp.json()["status"] == "error"

    done = [e for _sid, e in published if isinstance(e, TurnDoneEvent)]
    assert len(done) == 1 and done[0].response.status == "error"
    state = client.get(f"/api/chat/turns/{TURN}").json()
    assert state == {"turn_id": TURN, "state": "done", "response": resp.json()}


def test_turn_state_is_running_while_the_agent_works_then_done(monkeypatch, session_store):
    client = _authed_client(monkeypatch)
    seen: dict[str, Any] = {}

    async def handle_turn(client_arg, store_arg, sid_arg, *, turn_id, query, **kwargs):
        # The route's own read path is GET /turns/{id}; read the same store here, since a
        # synchronous TestClient call from inside the handler would block its event loop.
        seen["during"] = await session_store.get_turn(sid_arg, turn_id)
        return ChatMessageResponse(turn_id=turn_id, status=ChatStatus.ANSWER, response_text="42")

    monkeypatch.setattr(chat_service, "handle_turn", handle_turn)

    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})

    assert seen["during"] == {"state": "running"}
    after = client.get(f"/api/chat/turns/{TURN}")
    assert after.status_code == 200
    assert after.json() == {"turn_id": TURN, "state": "done", "response": resp.json()}


def test_running_turn_reads_as_running(monkeypatch, session_store):
    client = _authed_client(monkeypatch)

    async def start() -> None:
        assert await session_store.start_turn("sid-turns", TURN)

    import asyncio

    asyncio.run(start())
    resp = client.get(f"/api/chat/turns/{TURN}")
    assert resp.json() == {"turn_id": TURN, "state": "running", "response": None}


def test_unknown_turn_is_404(monkeypatch):
    client = _authed_client(monkeypatch)
    assert client.get(f"/api/chat/turns/{TURN}").status_code == 404


def test_another_sessions_turn_is_404(monkeypatch):
    """Turn state is scoped to the session that sent it."""
    owner = _authed_client(monkeypatch, sid="sid-owner", user="alice")
    monkeypatch.setattr(chat_service, "handle_turn", _answer([]))
    assert owner.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN}).status_code == 200

    other = _authed_client(monkeypatch, sid="sid-other", user="bob")
    assert other.get(f"/api/chat/turns/{TURN}").status_code == 404


def test_turn_state_requires_auth():
    from app.main import app

    assert TestClient(app).get(f"/api/chat/turns/{TURN}").status_code == 401


async def test_turn_result_is_visible_to_another_worker(session_store, valkey_server):
    """The POST and the client's event stream or lookup can land on different workers."""
    from fakeredis.aioredis import FakeRedis

    worker_b = SessionStore(FakeRedis(server=valkey_server, decode_responses=True))

    assert await session_store.start_turn("sid-mw", TURN)
    assert await worker_b.get_turn("sid-mw", TURN) == {"state": "running"}
    assert not await worker_b.start_turn("sid-mw", TURN)

    await session_store.finish_turn("sid-mw", TURN, {"turn_id": TURN, "status": "answer"})
    assert await worker_b.get_turn("sid-mw", TURN) == {
        "state": "done",
        "response": {"turn_id": TURN, "status": "answer"},
    }


async def test_a_running_turn_is_a_short_lease_and_a_finished_one_lasts_an_hour(session_store, fake_redis):
    """A running turn's state expires soon unless renewed, so a turn whose worker died
    reads as 404 within a minute; a finished turn's result is kept for the full hour."""
    from app.sessions import TURN_LEASE_SECONDS, TURN_TTL_SECONDS

    key = f"session:sid-ttl:turn:{TURN}"
    await session_store.start_turn("sid-ttl", TURN)
    assert TURN_LEASE_SECONDS - 5 < await fake_redis.ttl(key) <= TURN_LEASE_SECONDS

    await fake_redis.expire(key, 3)
    await session_store.renew_turn("sid-ttl", TURN)
    assert TURN_LEASE_SECONDS - 5 < await fake_redis.ttl(key) <= TURN_LEASE_SECONDS

    await session_store.finish_turn("sid-ttl", TURN, {"turn_id": TURN, "status": "answer"})
    assert TURN_TTL_SECONDS - 60 < await fake_redis.ttl(key) <= TURN_TTL_SECONDS


async def test_a_turn_whose_lease_ran_out_reads_as_no_turn(session_store, fake_redis):
    """The worker died mid-turn: nothing renews the lease, so the lookup stops saying
    "running" and the client can stop waiting."""
    await session_store.start_turn("sid-dead", TURN)
    await fake_redis.delete(f"session:sid-dead:turn:{TURN}")  # what expiry does
    assert await session_store.get_turn("sid-dead", TURN) is None


async def test_the_turn_lease_is_renewed_while_the_agent_works(monkeypatch, session_store):
    """A long turn keeps its lease even when the agent sends no status line."""
    import asyncio

    from app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "TURN_LEASE_REFRESH_SECONDS", 0)
    renewed: list[str] = []

    async def renew(sid, turn_id):
        renewed.append(turn_id)

    monkeypatch.setattr(session_store, "renew_turn", renew)
    lease = asyncio.create_task(chat_router._keep_turn_alive(session_store, "sid-l", TURN))
    for _ in range(5):
        await asyncio.sleep(0)
    await asyncio.wait_for(chat_router._end_lease(lease), timeout=2)
    count = len(renewed)
    assert count >= 2 and set(renewed) == {TURN}

    for _ in range(5):
        await asyncio.sleep(0)
    assert len(renewed) == count, "no renewal after the lease ended"


async def test_a_failed_renewal_is_retried_on_the_next_tick(monkeypatch, session_store):
    import asyncio

    from app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "TURN_LEASE_REFRESH_SECONDS", 0)
    calls = 0

    async def flaky(sid, turn_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("valkey blip")

    monkeypatch.setattr(session_store, "renew_turn", flaky)
    lease = asyncio.create_task(chat_router._keep_turn_alive(session_store, "sid-l", TURN))
    for _ in range(6):
        await asyncio.sleep(0)
    await asyncio.wait_for(chat_router._end_lease(lease), timeout=2)
    assert calls >= 2


async def test_a_cancelled_turn_stops_renewing_its_lease(monkeypatch, session_store, valkey_state):
    """Worker shutdown cancels the request: the lease must end with it, not outlive it."""
    import asyncio

    from app.routers import chat as chat_router
    from app.security import TokenClaims

    monkeypatch.setattr(chat_router, "TURN_LEASE_REFRESH_SECONDS", 0)
    renewed: list[str] = []

    async def renew(sid, turn_id):
        renewed.append(turn_id)

    monkeypatch.setattr(session_store, "renew_turn", renew)
    started = asyncio.Event()

    async def hang(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(chat_service, "handle_turn", hang)

    async def no_token(sub):
        return None

    monkeypatch.setattr(chat_router.identity, "mint_for_user", no_token)

    from app.main import app

    class _Req:
        pass

    req = _Req()
    req.app = app  # type: ignore[attr-defined]
    claims = TokenClaims(sub="alice", role="user", sid="sid-c", exp=0)
    body = chat_router.ChatMessageRequest(query="hi", turn_id=TURN)
    turn = asyncio.create_task(chat_router.post_message(req, body, claims))  # type: ignore[arg-type]
    await started.wait()
    turn.cancel()
    try:
        await asyncio.wait_for(turn, timeout=2)  # hangs if the lease isn't ended
    except asyncio.CancelledError:
        pass
    count = len(renewed)
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(renewed) == count


def test_a_turn_whose_result_cannot_be_stored_still_answers_and_announces(monkeypatch, session_store, event_bus):
    """Storing the result is best effort: a Valkey blip must not turn a finished turn
    into a 500, and the POST reply and turn_done still carry it."""
    client = _authed_client(monkeypatch)
    published = _capture_published(monkeypatch, event_bus)
    monkeypatch.setattr(chat_service, "handle_turn", _answer([]))

    async def broken(*args, **kwargs):
        raise ConnectionError("valkey down")

    monkeypatch.setattr(session_store, "finish_turn", broken)

    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})

    assert resp.status_code == 200
    assert resp.json()["response_text"] == "42"
    assert [e.turn_id for _sid, e in published if isinstance(e, TurnDoneEvent)] == [TURN]


def test_a_turn_with_no_event_bus_is_still_stored(monkeypatch):
    from app.main import app

    client = _authed_client(monkeypatch)
    monkeypatch.setattr(chat_service, "handle_turn", _answer([]))
    monkeypatch.setattr(app.state, "event_bus", None)

    resp = client.post("/api/chat/messages", json={"query": "hi", "turn_id": TURN})

    assert client.get(f"/api/chat/turns/{TURN}").json()["response"] == resp.json()


async def test_unreadable_turn_state_reads_as_no_turn(session_store, fake_redis):
    """A corrupt value (hand-edited, half-written) must not 500 the lookup."""
    await fake_redis.set(f"session:sid-bad:turn:{TURN}", "{not json")
    assert await session_store.get_turn("sid-bad", TURN) is None

    await fake_redis.set(f"session:sid-bad:turn:{TURN}", '["a list"]')
    assert await session_store.get_turn("sid-bad", TURN) is None


def test_unreadable_turn_state_is_a_404(monkeypatch, fake_redis):
    import asyncio

    client = _authed_client(monkeypatch)
    asyncio.run(fake_redis.set(f"session:sid-turns:turn:{TURN}", "{not json"))
    assert client.get(f"/api/chat/turns/{TURN}").status_code == 404
