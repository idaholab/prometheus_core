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

"""Offline tests for the turn orchestrator (task 04).

These exercise the pure ``ConversationResponse`` → ``ChatMessageResponse``
mapping and the ``handle_turn`` glue with a stubbed ``A2AClient`` — no live agent.
The router's error-to-inline-response behavior is covered against a ``TestClient``
with a monkeypatched service.

Session state is Valkey-backed (``conftest``'s ``session_store`` over ``fakeredis``),
so the mapper takes ``(store, sid)`` rather than a live ``SessionState``: a snapshot is
frozen, and every former in-place mutation is now a store write. The assertions here
therefore *re-read* the session after the call — which is also the stronger check, since
it proves the mutation reached Valkey rather than a local object.
"""

import pytest
from fastapi.testclient import TestClient

from app.a2a_client import ConversationResponse
from app.contract import ChatMessageResponse, ChatStatus
from app.services import chat as chat_service
from app.sessions import SessionStore

SID = "sid-1"


def _resp(**kwargs) -> ConversationResponse:
    return ConversationResponse.from_payload({"conversation_id": "c1", **kwargs})


async def _seed(store: SessionStore, sid: str = SID, *, conversation_id: str = "c1") -> None:
    """Bind ``sid`` to a conversation — the state every mapper branch reads."""
    await store.reset(sid, conversation_id)


async def _stored(store: SessionStore, sid: str = SID):
    """Re-read the session snapshot after a call that was supposed to write."""
    return await store.get_or_create(sid)


# --------------------------------------------------------------------------- #
# map_response — per-status branches
# --------------------------------------------------------------------------- #


async def test_map_completed_shapes_artifacts_and_persists_catalog(session_store):
    await _seed(session_store)
    response = _resp(
        status="completed",
        report="The analysis is done.",
        artifacts=[{"artifact_id": "a1", "name": "full"}],
        new_artifacts=[
            {"artifact_id": "a1", "name": "result.json", "mime_type": "application/json"},
            {"artifact_id": "up", "name": "upload", "metadata": {"source": "user-upload"}},
        ],
        message_metadata={"follow_up_suggestions": ["Do X", "Do Y"]},
    )

    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )

    assert mapped.status == ChatStatus.COMPLETED.value
    assert mapped.turn_id == "t1"
    assert mapped.report == "The analysis is done."
    # user-upload echo is dropped; only the real artifact survives.
    assert mapped.artifacts is not None and len(mapped.artifacts) == 1
    assert mapped.artifacts[0].artifact_id == "a1"
    assert mapped.follow_up_suggestions == ["Do X", "Do Y"]
    # Full catalog persisted onto the session for task-07 content fetches.
    assert (await _stored(session_store)).artifacts == [{"artifact_id": "a1", "name": "full"}]


async def test_map_completed_slash_command_suppresses_artifacts(session_store):
    await _seed(session_store)
    response = _resp(
        status="completed",
        report="done",
        new_artifacts=[{"artifact_id": "a1", "name": "x"}],
        message_metadata={"slash_command": True},
    )
    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.artifacts is None


async def test_map_completed_falls_back_to_artifact_count_text(session_store):
    await _seed(session_store)
    response = _resp(
        status="completed",
        new_artifacts=[{"artifact_id": "a1", "name": "x", "mime_type": "application/json"}],
    )
    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.report == "1 artifact(s) ready."


async def test_map_needs_info_normalizes_questions(session_store):
    await _seed(session_store)
    response = _resp(
        status="needs_info",
        message="Need more",
        followup_questions=[
            {
                "field": "temp",
                "question": "Temperature?",
                "type": "number",
                "required": True,
                "description": "in Celsius",
            },
            {"question": "Material?", "type": "select", "options": ["steel", "copper"]},
        ],
    )
    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )

    assert mapped.status == ChatStatus.NEEDS_INFO.value
    assert mapped.followup_questions is not None and len(mapped.followup_questions) == 2
    first = mapped.followup_questions[0]
    assert first.id == "temp"
    assert first.label == "Temperature?"
    assert first.input_type == "number"
    assert first.help == "in Celsius"
    second = mapped.followup_questions[1]
    assert second.id == "Material?"  # falls back to the question text
    assert second.options is not None
    assert [o.value for o in second.options] == ["steel", "copper"]


async def test_map_needs_info_carries_new_artifacts_and_persists_catalog(session_store):
    """A workflow step can publish artifacts and then pause at a review form in the same
    turn; the artifacts must reach the frontend with the form, not be dropped."""
    await _seed(session_store)
    response = _resp(
        status="needs_info",
        message="Gate 2: approve, request more evidence, or reject?",
        followup_questions=[
            {"field": "gate_action", "question": "Decision?", "type": "select", "options": ["approve", "reject"]}
        ],
        artifacts=[{"artifact_id": "a1", "name": "full"}],
        new_artifacts=[
            {"artifact_id": "a1", "name": "status.png", "mime_type": "image/png"},
            {"artifact_id": "up", "name": "upload", "metadata": {"source": "user-upload"}},
        ],
    )

    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )

    assert mapped.status == ChatStatus.NEEDS_INFO.value
    assert mapped.followup_questions is not None and len(mapped.followup_questions) == 1
    assert mapped.artifacts is not None and [a.artifact_id for a in mapped.artifacts] == ["a1"]
    assert (await _stored(session_store)).artifacts == [{"artifact_id": "a1", "name": "full"}]


async def test_map_needs_info_without_artifacts_leaves_catalog(session_store):
    await session_store.reset(SID, "c1", artifacts=[{"artifact_id": "earlier"}])
    response = _resp(status="needs_info", message="m", followup_questions=[], artifacts=[])
    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.artifacts is None
    # artifacts=[] must not wipe the accumulated catalog (T-7).
    assert (await _stored(session_store)).artifacts == [{"artifact_id": "earlier"}]


async def test_map_needs_info_skips_catalog_write_after_rebind(session_store):
    await _seed(session_store)
    await _rebind(session_store)
    response = _resp(
        status="needs_info",
        message="m",
        followup_questions=[],
        artifacts=[{"artifact_id": "a1", "name": "full"}],
        new_artifacts=[{"artifact_id": "a1", "name": "x.png", "mime_type": "image/png"}],
    )
    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.status == ChatStatus.NEEDS_INFO.value
    assert (await _stored(session_store)).artifacts == [{"artifact_id": "c2-art"}]


async def test_map_plan_ready_carries_auto_approve(session_store):
    await _seed(session_store)
    response = _resp(status="plan_ready", message="Proposed plan", plan={"steps": ["a", "b"]})

    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=True
    )
    assert mapped.status == ChatStatus.PLAN_READY.value
    assert mapped.plan == {"steps": ["a", "b"]}
    assert mapped.auto_approve is True

    mapped_off = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped_off.auto_approve is False


async def test_map_backgrounded_registers_awaited_task(session_store):
    await _seed(session_store)
    response = _resp(status="backgrounded", message_metadata={"task_id": "task-42"})

    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.status == ChatStatus.BACKGROUNDED.value
    assert mapped.task_id == "task-42"
    assert "task-42" in (await _stored(session_store)).awaited_task_ids


# --------------------------------------------------------------------------- #
# rebind — a turn whose session has since moved to a different conversation
# (chat-history "New chat"/resume while a turn is in flight) must not mutate
# session state for the conversation the session now points at. The writes are
# guarded on the turn's own conversation id, so a rebind at any point before them wins.
# --------------------------------------------------------------------------- #


async def _rebind(store: SessionStore, sid: str = SID) -> None:
    await store.reset(sid, "c2", artifacts=[{"artifact_id": "c2-art"}])


async def test_map_final_skips_session_mutation_after_rebind(session_store):
    await _seed(session_store)
    await _rebind(session_store)
    response = _resp(
        status="completed",
        report="done",
        artifacts=[{"artifact_id": "a1", "name": "full"}],
    )

    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )

    # A response is still produced (the original HTTP request needs one)...
    assert mapped.status == ChatStatus.COMPLETED.value
    # ...but the catalog of the conversation the session is *now* bound to is untouched.
    assert (await _stored(session_store)).artifacts == [{"artifact_id": "c2-art"}]


async def test_map_backgrounded_skips_registration_after_rebind(session_store):
    await _seed(session_store)
    await _rebind(session_store)
    response = _resp(status="backgrounded", message_metadata={"task_id": "task-42"})

    await chat_service.map_response(response, "t1", session_store, SID, conversation_id="c1", auto_approve=False)

    assert not (await _stored(session_store)).awaited_task_ids


async def test_map_needs_info_depth_cap_not_applied_after_rebind(session_store):
    await _seed(session_store, conversation_id="c2")
    for _ in range(5):
        await session_store.bump_needs_info(SID, conversation_id="c2")
    ni = _resp(status="needs_info", message="m", followup_questions=[])

    mapped = await chat_service.map_response(ni, "t", session_store, SID, conversation_id="c1", auto_approve=False)

    # Still a needs_info response, not the "too many followups" fallback...
    assert mapped.status == ChatStatus.NEEDS_INFO.value
    # ...and the counter for the conversation the session now points at is untouched.
    assert (await _stored(session_store)).consecutive_needs_info == 5


async def test_map_other_status_does_not_reset_the_new_conversations_counter(session_store):
    await _seed(session_store, conversation_id="c2")
    await session_store.bump_needs_info(SID, conversation_id="c2")

    await chat_service.map_response(
        _resp(status="answer", response_text="x"), "t", session_store, SID, conversation_id="c1", auto_approve=False
    )

    assert (await _stored(session_store)).consecutive_needs_info == 1


# --------------------------------------------------------------------------- #
# T-8 — one authoritative text field per terminal status (no double-render)
# --------------------------------------------------------------------------- #


async def test_answer_text_only_in_response_text(session_store):
    await _seed(session_store)
    mapped = await chat_service.map_response(
        _resp(status="answer", response_text="42", message="noise"),
        "t",
        session_store,
        SID,
        conversation_id="c1",
        auto_approve=False,
    )
    assert mapped.response_text == "42"
    assert mapped.report is None
    assert mapped.message is None


async def test_completed_text_only_in_report(session_store):
    await _seed(session_store)
    mapped = await chat_service.map_response(
        _resp(status="completed", report="done", response_text="dup", message="noise"),
        "t",
        session_store,
        SID,
        conversation_id="c1",
        auto_approve=False,
    )
    assert mapped.report == "done"
    assert mapped.response_text is None
    assert mapped.message is None


# --------------------------------------------------------------------------- #
# T-2 — follow-up depth cap
# --------------------------------------------------------------------------- #


async def test_needs_info_depth_cap_stops_looping(session_store):
    await _seed(session_store)
    ni = _resp(status="needs_info", followup_questions=[{"field": "f", "question": "Q?"}])
    # The cap allows N consecutive needs_info turns…
    for _ in range(chat_service._MAX_CONSECUTIVE_NEEDS_INFO):
        mapped = await chat_service.map_response(ni, "t", session_store, SID, conversation_id="c1", auto_approve=False)
        assert mapped.status == ChatStatus.NEEDS_INFO.value
    # …then stops looping with a plain message instead of another form.
    capped = await chat_service.map_response(ni, "t", session_store, SID, conversation_id="c1", auto_approve=False)
    assert capped.status == ChatStatus.ANSWER.value
    assert capped.followup_questions is None
    assert "restate" in (capped.response_text or "").lower()


async def test_needs_info_counter_resets_on_other_status(session_store):
    await _seed(session_store)
    ni = _resp(status="needs_info", followup_questions=[{"field": "f", "question": "Q?"}])
    await chat_service.map_response(ni, "t", session_store, SID, conversation_id="c1", auto_approve=False)
    await chat_service.map_response(ni, "t", session_store, SID, conversation_id="c1", auto_approve=False)
    assert (await _stored(session_store)).consecutive_needs_info == 2
    await chat_service.map_response(
        _resp(status="answer", response_text="done"), "t", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert (await _stored(session_store)).consecutive_needs_info == 0


async def test_map_backgrounded_without_task_id_registers_nothing(session_store):
    await _seed(session_store)
    response = _resp(status="backgrounded")
    mapped = await chat_service.map_response(
        response, "t1", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.task_id is None
    assert not (await _stored(session_store)).awaited_task_ids


async def test_map_executing_and_error_and_unknown(session_store):
    await _seed(session_store)

    executing = await chat_service.map_response(
        _resp(status="executing"), "t", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert executing.status == ChatStatus.EXECUTING.value
    assert "executing" in (executing.message or "").lower()

    err = await chat_service.map_response(
        _resp(status="error", message="boom"), "t", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert err.status == ChatStatus.ERROR.value
    assert err.message == "boom"

    answer = await chat_service.map_response(
        _resp(status="answer", response_text="hi"), "t", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert answer.status == ChatStatus.ANSWER.value
    assert answer.response_text == "hi"


# --------------------------------------------------------------------------- #
# handle_turn — glue over a stubbed A2AClient
# --------------------------------------------------------------------------- #


class _StubClient:
    def __init__(self, response: ConversationResponse):
        self._response = response
        self.sent: dict = {}

    async def send(self, **kwargs):
        self.sent = kwargs
        return self._response


async def test_handle_turn_forwards_args_and_maps(session_store):
    await _seed(session_store)
    await session_store.set_artifacts(SID, [{"artifact_id": "a1"}], conversation_id="c1")
    client = _StubClient(_resp(status="answer", response_text="ok"))

    mapped = await chat_service.handle_turn(
        client,  # type: ignore[arg-type]
        session_store,
        SID,
        turn_id="t1",
        query="hello",
        plan_approved=True,
    )

    assert mapped.status == ChatStatus.ANSWER.value
    assert client.sent["query"] == "hello"
    assert client.sent["conversation_id"] == "c1"
    assert client.sent["plan_approved"] is True
    assert client.sent["artifacts"] == [{"artifact_id": "a1"}]


async def test_handle_turn_forwards_user_token(session_store):
    await _seed(session_store)
    client = _StubClient(_resp(status="answer", response_text="ok"))

    await chat_service.handle_turn(
        client,  # type: ignore[arg-type]
        session_store,
        SID,
        turn_id="t1",
        query="hello",
        user_token="fake.jwt.token",
    )

    assert client.sent["user_token"] == "fake.jwt.token"


async def test_handle_turn_user_token_defaults_to_none(session_store):
    await _seed(session_store)
    client = _StubClient(_resp(status="answer", response_text="ok"))

    await chat_service.handle_turn(
        client,  # type: ignore[arg-type]
        session_store,
        SID,
        turn_id="t1",
        query="hello",
    )

    assert client.sent["user_token"] is None


async def test_handle_turn_requires_conversation_id(session_store):
    # "sid-x" was never bound to a conversation, so the store returns the empty default
    # snapshot and handle_turn refuses the turn rather than inventing an id.
    client = _StubClient(_resp(status="answer"))
    with pytest.raises(ValueError):
        await chat_service.handle_turn(client, session_store, "sid-x", turn_id="t", query="q")  # type: ignore[arg-type]


class _ConversationSwitchingStubClient:
    """Simulates a chat-history "New chat"/resume rebinding the session's
    ``conversation_id`` while a turn is still in flight — the race the guarded session
    writes close.

    The rebind is a store write landing after ``handle_turn`` captured the conversation
    id and before it writes the result back, so only a write that re-checks the binding
    atomically with the write itself can notice it."""

    def __init__(
        self,
        response: ConversationResponse,
        store: SessionStore,
        sid: str,
        new_conversation_id: str,
    ):
        self._response = response
        self._store = store
        self._sid = sid
        self._new_conversation_id = new_conversation_id
        self.sent: dict = {}

    async def send(self, **kwargs):
        self.sent = kwargs
        # The outgoing request must have already captured the ORIGINAL conversation_id
        # before this "rebind" happens (asserted by the caller against .sent).
        await self._store.reset(self._sid, self._new_conversation_id, artifacts=[{"artifact_id": "c2-art"}])
        return self._response


async def test_handle_turn_sends_original_conversation_but_skips_stale_mutation(session_store):
    await _seed(session_store)  # conversation_id == "c1"
    response = _resp(
        status="completed",
        report="done for c1",
        artifacts=[{"artifact_id": "a1", "name": "c1-catalog"}],
    )
    client = _ConversationSwitchingStubClient(response, session_store, SID, new_conversation_id="c2")

    mapped = await chat_service.handle_turn(
        client,  # type: ignore[arg-type]
        session_store,
        SID,
        turn_id="t1",
        query="hello",
    )

    # The A2A request still targeted the conversation this turn was actually for...
    assert client.sent["conversation_id"] == "c1"
    # ...the caller still gets a normal response back...
    assert mapped.status == ChatStatus.COMPLETED.value
    # ...but the session (now bound to "c2") did not get c1's artifact catalog stomped
    # onto it.
    assert (await _stored(session_store)).conversation_id == "c2"
    assert (await _stored(session_store)).artifacts == [{"artifact_id": "c2-art"}]


def test_upload_descriptors_to_dicts_roundtrip():
    from app.contract import UploadDescriptor

    dicts = chat_service.upload_descriptors_to_dicts(
        [UploadDescriptor(upload_id="u1", name="f.stp", mime_type="model/step", size_bytes=10)]
    )
    assert dicts == [{"upload_id": "u1", "name": "f.stp", "mime_type": "model/step", "size_bytes": 10}]
    assert chat_service.upload_descriptors_to_dicts(None) is None


# --------------------------------------------------------------------------- #
# router — A2AClient failures become an inline error response, not a 500
# --------------------------------------------------------------------------- #


def _authed_client(monkeypatch) -> tuple[TestClient, str]:
    """Build a TestClient with a valid session cookie."""
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)

    token = security.issue_token(security.User(identifier="alice"), sid="sid-router")
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client, "sid-router"


def test_post_message_maps_send_failure_to_error(monkeypatch):
    client, _sid = _authed_client(monkeypatch)

    async def boom(*args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(chat_service, "handle_turn", boom)

    resp = client.post("/api/chat/messages", json={"query": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "Error communicating with agent" in body["message"]
    assert body["turn_id"]


def test_post_message_rejects_empty_request(monkeypatch):
    client, _sid = _authed_client(monkeypatch)
    resp = client.post("/api/chat/messages", json={"query": "   "})
    assert resp.status_code == 422


def test_post_message_uploads_only_uses_default_query(monkeypatch):
    """T-1: a file with no caption is a supported turn, not a 422; the router supplies
    the neutral default query the agent expects."""
    client, _sid = _authed_client(monkeypatch)
    captured: dict = {}

    async def capture(client_arg, store_arg, sid_arg, *, turn_id, query, **kwargs):
        captured["query"] = query
        return ChatMessageResponse(turn_id=turn_id, status=ChatStatus.ANSWER, response_text="ok")

    monkeypatch.setattr(chat_service, "handle_turn", capture)

    resp = client.post(
        "/api/chat/messages",
        json={
            "query": "",
            "upload_ids": [{"upload_id": "u1", "name": "part.stl", "mime_type": "model/stl", "size_bytes": 10}],
        },
    )
    assert resp.status_code == 200
    assert captured["query"] == "Please process the uploaded file(s)."


def test_post_message_requires_auth(monkeypatch):
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/chat/messages", json={"query": "hi"})
    assert resp.status_code == 401
