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

"""Chat turn orchestration — the inverted, non-blocking loop (decision D1).

Ports the turn logic from ``frontend/components/message_handler.py`` while
dropping Chainlit's blocking waits and server-side rendering:

- The Chainlit handler *blocked* inside one turn — it awaited a ``cl.Step``
  through streaming, then awaited an ``AskElementMessage`` / ``AskActionMessage``
  for follow-ups and plan approval, recursing on the same call stack. Here every
  turn is a single ``POST`` that returns as soon as the agent produces a terminal
  ``ConversationResponse``. Follow-up answers and plan approval/rejection arrive
  as the *next* ``POST`` (carrying ``followup_answers`` / ``plan_approved`` /
  ``plan_rejected``), which ``A2AClient.send`` already supports.
- Live status no longer updates a ``cl.Step``; the caller's ``on_status`` closure
  publishes a :class:`StatusEvent` onto the session event bus (task 05).
- Artifacts are shaped into :class:`ArtifactMeta` (task 07's builder) rather than
  rendered into Chainlit elements.

The mapping between ``prometheus_api``'s ``ConversationResponse`` and our wire
:class:`ChatMessageResponse` lives entirely in :func:`map_response`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Optional

from app.a2a_client import A2AClient, ConversationResponse
from app.contract import ArtifactMeta, ChatMessageResponse, ChatStatus, UploadDescriptor
from app.contract import normalize_followup_questions as _normalize_followup_questions
from app.services.artifacts import is_user_upload, shape_artifacts
from app.services.mesh.service import enrich_mesh_artifacts
from app.sessions import SessionStore

logger = logging.getLogger(__name__)

# Async callback: receives one status-line string per streamed progress event.
OnStatus = Callable[[str], Coroutine[Any, Any, None]]

# Follow-up depth cap (T-2): the max consecutive ``needs_info`` turns before we stop
# looping and return a plain message. Mirrors the old ``_MAX_NEEDS_INFO_DEPTH`` (5).
_MAX_CONSECUTIVE_NEEDS_INFO = 5
_TOO_MANY_FOLLOWUPS_MESSAGE = (
    "I've asked several follow-up questions in a row without being able to proceed. "
    "Please restate your request with the details included."
)


def _coerce_final_text(response: ConversationResponse, artifact_count: int) -> str:
    """Best-available human text for a terminal response.

    Reused verbatim from ``message_handler._coerce_final_text``: report →
    response_text → message → ``"N artifact(s) ready."``.
    """
    text = (response.report or response.response_text or response.message or "").strip()
    if text:
        return text
    if artifact_count:
        return f"{artifact_count} artifact(s) ready."
    return ""


def normalize_followup_questions(response: ConversationResponse) -> list:
    """Normalize an agent ``needs_info`` response's questions to ``FormField``s.

    Thin wrapper over :func:`app.contract.normalize_followup_questions` (which
    ports the field-building loop from ``_handle_needs_info``, message_handler.py
    ~502-518). The ``AskElementMessage`` round-trip and ``_depth`` recursion are
    intentionally dropped: the next ``POST`` carries ``followup_answers``.
    """
    return _normalize_followup_questions(response.followup_questions or [])


async def _turn_artifacts(
    response: ConversationResponse,
    store: SessionStore,
    sid: str,
    *,
    conversation_id: str,
) -> list[ArtifactMeta]:
    """Persist the conversation catalog (a Valkey write) and shape this turn's new artifacts.

    Shared by the terminal and ``needs_info`` branches, since either can end a turn
    that produced artifacts (a workflow step that pauses at a review form still
    published its outputs first).

    - Filters ``new_artifacts``, dropping user-uploaded echoes
      (``metadata.source == "user-upload"``; message_handler.py:672) and all
      artifacts on slash-command turns.
    - Persists the full ``response.artifacts`` catalog onto the session so task 07's
      ``GET /api/artifacts/{id}/content`` can resolve ids for the whole
      conversation, not just this turn. Truthy, not ``is not None`` (T-7): an
      ``artifacts=[]`` turn must not wipe the accumulated catalog.
    - The catalog write is guarded on ``conversation_id`` (see :func:`map_response`).
    """
    metadata = response.message_metadata or {}
    is_slash_command = bool(metadata.get("slash_command"))

    raw_new = [] if is_slash_command else (response.new_artifacts or [])
    new_artifacts = [artifact for artifact in raw_new if not is_user_upload(artifact)]

    if response.artifacts:
        await store.set_artifacts(sid, response.artifacts, conversation_id=conversation_id)

    return shape_artifacts(new_artifacts)


async def _map_needs_info(
    response: ConversationResponse,
    turn_id: str,
    store: SessionStore,
    sid: str,
    *,
    conversation_id: str,
) -> ChatMessageResponse:
    """Follow-up branch. Carries the turn's new artifacts too: a workflow that pauses at
    a review form has usually just published the outputs the reviewer needs to see."""
    shaped = await _turn_artifacts(response, store, sid, conversation_id=conversation_id)
    return ChatMessageResponse(
        turn_id=turn_id,
        status=ChatStatus.NEEDS_INFO,
        message=response.message,
        followup_questions=normalize_followup_questions(response),
        artifacts=shaped or None,
    )


def _map_plan_ready(
    response: ConversationResponse,
    turn_id: str,
    *,
    auto_approve: bool,
) -> ChatMessageResponse:
    """Plan branch (ports ``_handle_plan_ready``, minus ``AskActionMessage``).

    ``auto_approve`` mirrors ``settings.auto_approve_steps`` so the frontend can
    immediately re-``POST`` with ``plan_approved: true`` without prompting.
    Approval/rejection is the *next* request; rejection (``plan_rejected: true``)
    clears the agent's ``awaiting_approval`` server-side.
    """
    return ChatMessageResponse(
        turn_id=turn_id,
        status=ChatStatus.PLAN_READY,
        message=response.message,
        plan=response.plan or {},
        auto_approve=auto_approve,
    )


async def _map_final(
    response: ConversationResponse,
    turn_id: str,
    status: ChatStatus,
    store: SessionStore,
    sid: str,
    *,
    conversation_id: str,
) -> ChatMessageResponse:
    """Terminal branch (ports ``_handle_final_response``, minus rendering).

    - Filters, shapes and persists artifacts via :func:`_turn_artifacts`.
    - Pulls ``follow_up_suggestions`` from ``message_metadata``.

    The catalog write is guarded on ``conversation_id`` (see :func:`map_response`), so
    a late-arriving response for an abandoned conversation can't stomp the catalog of
    whatever conversation the session now points at. The returned
    :class:`ChatMessageResponse` is still produced normally since the caller (the
    original HTTP request) still needs *some* response, even though the frontend will
    discard it as stale on its side too.
    """
    metadata = response.message_metadata or {}
    shaped = await _turn_artifacts(response, store, sid, conversation_id=conversation_id)
    text = _coerce_final_text(response, len(shaped)) or None

    suggestions = metadata.get("follow_up_suggestions") or None

    # One authoritative text field per status (T-8): ``completed`` carries the blob in
    # ``report``; ``answer``/``recommendation`` in ``response_text``. The other text
    # fields are nulled so a frontend can't double-render the same text. (Old code
    # produced a single coalesced blob; the new mapping had leaked all three at once.)
    report_text = text if status == ChatStatus.COMPLETED else None
    response_text = None if status == ChatStatus.COMPLETED else text

    return ChatMessageResponse(
        turn_id=turn_id,
        status=status,
        message=None,
        report=report_text,
        response_text=response_text,
        artifacts=shaped or None,
        recommended_materials=response.recommended_materials or None,
        follow_up_suggestions=suggestions,
    )


async def _map_backgrounded(
    response: ConversationResponse,
    turn_id: str,
    store: SessionStore,
    sid: str,
    *,
    conversation_id: str,
) -> ChatMessageResponse:
    """Backgrounded branch (ports ``_handle_backgrounded`` registration only).

    Reads ``task_id`` from ``message_metadata`` and registers it on the session
    (``session:{sid}:awaited``) so the SSE Redis subscriber (task 05) knows which root
    tasks this user is waiting on. The **fast-finish snapshot guard** — checking
    ``node_snapshot`` for a task that finished before the subscriber saw it — moves
    to the events service (task 05), which owns the Redis lifecycle.

    Guarded on ``conversation_id`` like every write here: registering a task under a
    session that has since moved to a different conversation would make that *other*
    conversation's session wait on a task it never started.
    """
    metadata = response.message_metadata or {}
    task_id = metadata.get("task_id")
    if task_id:
        await store.await_task(sid, str(task_id), conversation_id=conversation_id)

    return ChatMessageResponse(
        turn_id=turn_id,
        status=ChatStatus.BACKGROUNDED,
        message=response.message
        or ("This is taking a while — it's now running in the background. I'll post the result here when it's ready."),
        task_id=str(task_id) if task_id else None,
    )


async def map_response(
    response: ConversationResponse,
    turn_id: str,
    store: SessionStore,
    sid: str,
    *,
    conversation_id: str,
    auto_approve: bool,
) -> ChatMessageResponse:
    """Map a terminal ``ConversationResponse`` to our wire ``ChatMessageResponse``.

    Ports the ``_handle_response`` status dispatch (message_handler.py:265) but
    returns a value instead of sending ``cl.Message``s. ``executing`` is surfaced
    as a plain ``ChatStatus.EXECUTING`` message; any unknown status collapses to
    ``ANSWER`` carrying the best-available text (the Chainlit ``else`` fallthrough).

    ``conversation_id`` is the conversation this response is *for* — the one the turn
    was sent to, which is not necessarily the one the session is bound to by now (a
    "New chat" or resume may have landed mid-turn, on any worker). Every session write
    below is conditional on the session still being bound to it, checked atomically in
    Valkey (see ``SessionStore._guarded``), so a stale response mutates nothing; a
    response is still returned (the caller's HTTP request still needs one; the frontend
    discards it as stale independently — see ``lib/store/chat.ts``'s ``post()``).
    """
    status = response.status  # str, because ConversationResponse uses use_enum_values

    # Follow-up depth cap (T-2): count consecutive needs_info turns; reset on anything
    # else. Beyond the cap, stop looping and return a plain message so a misbehaving
    # agent that keeps asking can't trap the conversation indefinitely. The counter is
    # ``conversation_id``'s: once the session has moved on, bump returns ``None`` and
    # no cap applies — a stale turn has nothing to do with the new conversation's depth.
    if status != "needs_info":
        await store.reset_needs_info(sid, conversation_id=conversation_id)
    else:
        count = await store.bump_needs_info(sid, conversation_id=conversation_id)
        if count is not None and count > _MAX_CONSECUTIVE_NEEDS_INFO:
            await store.reset_needs_info(sid, conversation_id=conversation_id)
            return ChatMessageResponse(
                turn_id=turn_id,
                status=ChatStatus.ANSWER,
                response_text=_TOO_MANY_FOLLOWUPS_MESSAGE,
            )

    if status == "needs_info":
        return await _map_needs_info(response, turn_id, store, sid, conversation_id=conversation_id)
    if status == "plan_ready":
        return _map_plan_ready(response, turn_id, auto_approve=auto_approve)
    if status in ("completed", "answer", "recommendation"):
        return await _map_final(response, turn_id, ChatStatus(status), store, sid, conversation_id=conversation_id)
    if status == "backgrounded":
        return await _map_backgrounded(response, turn_id, store, sid, conversation_id=conversation_id)
    if status == "executing":
        return ChatMessageResponse(
            turn_id=turn_id,
            status=ChatStatus.EXECUTING,
            message=response.message or "Agent is executing the plan…",
        )
    if status == "error":
        return ChatMessageResponse(
            turn_id=turn_id,
            status=ChatStatus.ERROR,
            message=response.message or "An error occurred during processing.",
        )

    # Unknown status: mirror the Chainlit else-branch (message → response_text).
    return ChatMessageResponse(
        turn_id=turn_id,
        status=ChatStatus.ANSWER,
        message=response.message,
        response_text=response.response_text,
    )


async def handle_turn(
    client: A2AClient,
    store: SessionStore,
    sid: str,
    *,
    turn_id: str,
    query: str,
    followup_answers: Optional[dict[str, Any]] = None,
    plan_approved: bool = False,
    plan_rejected: bool = False,
    workflow_id: Optional[str] = None,
    uploaded_files: Optional[list[dict[str, Any]]] = None,
    auto_approve: bool = False,
    on_status: Optional[OnStatus] = None,
    user_token: Optional[str] = None,
) -> ChatMessageResponse:
    """Run one non-blocking chat turn against the client-agent.

    Sends the request (streaming live status through ``on_status``) and maps the
    terminal ``ConversationResponse`` to a ``ChatMessageResponse``. Requires the session
    to already have a ``conversation_id`` (the router mints one on first use).

    ``user_token`` is the platform JWT identifying the caller (see ``app.identity``);
    it is forwarded to the client-agent, which verifies it and propagates it to
    every downstream specialist agent call.

    Callers convert ``A2AClient.send`` failures into an ``error``-status response;
    this function does not swallow them (see ``routers/chat.py``).
    """
    session = await store.get_or_create(sid)
    if not session.conversation_id:
        raise ValueError("session has no conversation_id; create a session first")

    # Read before the await: if the caller starts a "New chat" or resumes a
    # different past conversation (chat-history's loadConversation) while this
    # turn is in flight, the session's stored conversation id changes out from under
    # us — but the outgoing request must still target the conversation this turn was
    # actually for, and the response mapping below writes only if the session is still
    # on it (see ``conversation_id`` on ``map_response``).
    conversation_id = session.conversation_id

    response = await client.send(
        query=query,
        conversation_id=conversation_id,
        artifacts=session.artifacts or None,
        followup_answers=followup_answers,
        plan_approved=plan_approved,
        plan_rejected=plan_rejected,
        workflow_id=workflow_id,
        uploaded_files=uploaded_files,
        on_status=on_status,
        user_token=user_token,
    )

    # Restore interactive mesh rendering: convert any Exodus/STL artifact to VTP +
    # manifest and stamp it onto the artifact's json_body (off the event loop, cached)
    # before shaping, so the frontend adapter mounts the MeshViewer instead of a
    # download. Never raises — a conversion failure leaves json_body None (graceful
    # downgrade), so it can't break the turn.
    await enrich_mesh_artifacts(response)

    return await map_response(response, turn_id, store, sid, conversation_id=conversation_id, auto_approve=auto_approve)


def upload_descriptors_to_dicts(
    uploads: Optional[list[UploadDescriptor]],
) -> Optional[list[dict[str, Any]]]:
    """Convert wire ``UploadDescriptor``s to the dicts ``A2AClient.send`` expects.

    The client-agent's ``uploaded_files`` items are plain dicts with
    ``upload_id`` / ``name`` / ``mime_type`` / ``size_bytes`` (see
    ``_capture_uploaded_file``, message_handler.py:109); the staging round-trip
    itself happens in the uploads router (task 06).
    """
    if not uploads:
        return None
    return [u.model_dump() for u in uploads]
