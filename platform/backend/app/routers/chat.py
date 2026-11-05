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

"""POST /api/chat/messages — the non-blocking chat turn (decision D1).

Auth-required. Resolves the caller's session (and its ``conversation_id`` +
artifact catalog), takes the client's ``turn_id`` (or mints one), and runs one turn via
``services.chat.handle_turn``. Live status streams through an ``on_status``
closure that publishes :class:`StatusEvent`s onto the session event bus; the SSE
endpoint (task 05) drains them keyed by ``sid``.

Errors from ``A2AClient.send`` are caught and returned as an ``error``-status
``ChatMessageResponse`` (not a 500), mirroring the Chainlit handler's inline
"Error communicating with agent" message so the frontend renders it in the chat.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status as http_status

from app import identity
from app.a2a_client import A2AClient
from app.api_responses import AUTH_RESPONSES, error
from app.config import settings
from app.contract import (
    TURN_ID_PATTERN,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatStatus,
    StatusEvent,
    TurnDoneEvent,
    TurnStateResponse,
)
from app.openapi import TAG_CHAT
from app.redis_client import get_redis
from app.security import TokenClaims, current_claims
from app.services import chat as chat_service
from app.services import events as events_service
from app.sessions import TURN_LEASE_REFRESH_SECONDS, get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=[TAG_CHAT], responses=AUTH_RESPONSES)

# Cap on the accumulated in-flight status history carried on each StatusEvent (E-1).
_STATUS_HISTORY_LIMIT = 50


def _get_event_bus(request: Request):
    """Return the registered event bus, or ``None``.

    Task-05 seam: the events service registers ``app.state.event_bus`` (with a
    ``publish(sid, event)`` method) in the lifespan. Until then this is ``None``
    and status events are silently dropped — the turn still completes and returns
    its terminal response synchronously.
    """
    return getattr(request.app.state, "event_bus", None)


def _make_on_status(event_bus, sid: str, turn_id: str) -> Optional[chat_service.OnStatus]:
    """Build the ``on_status`` closure that publishes ``StatusEvent``s.

    Returns ``None`` when no event bus is registered so ``A2AClient.send`` skips
    the streaming callback entirely.

    Accumulates a per-turn, consecutive-duplicate-suppressed status history and sends
    it on each event (E-1) so the frontend can render the running step list, porting
    the ``status_history`` accumulation from ``message_handler`` (~121-143). The list
    is capped so a chatty turn can't grow it unbounded.
    """
    if event_bus is None:
        return None

    history: list[str] = []

    async def _on_status(message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if history and history[-1] == text:
            return  # suppress consecutive duplicates
        history.append(text)
        del history[:-_STATUS_HISTORY_LIMIT]
        try:
            await event_bus.publish(sid, StatusEvent(turn_id=turn_id, message=text, history=list(history)))
        except Exception as exc:  # a status publish must never fail the turn
            logger.warning("Failed to publish status event for turn %s: %s", turn_id, exc)

    return _on_status


def _get_a2a_client() -> A2AClient:
    return A2AClient(agent_url=settings.agent_url, agent_secret=settings.agent_secret)


_TURN_ID_REUSED = "This turn id was already used; send a new turn with a new id."
_NO_SUCH_TURN = "No such turn."


async def _keep_turn_alive(store, sid: str, turn_id: str) -> None:
    """Renew the running turn's lease until cancelled (see ``TURN_LEASE_SECONDS``).

    A timer, not the status stream: an agent step can run for minutes without a status
    line, and its turn is alive all the same."""
    while True:
        await asyncio.sleep(TURN_LEASE_REFRESH_SECONDS)
        try:
            await store.renew_turn(sid, turn_id)
        except Exception as exc:  # noqa: BLE001 - a missed renewal is retried next tick
            logger.warning("Failed to renew the lease of turn %s: %s", turn_id, exc)


@router.post(
    "/messages",
    response_model=ChatMessageResponse,
    responses=error(
        http_status.HTTP_409_CONFLICT,
        "This session already sent a turn with this `turn_id`; the agent is not run again.",
        _TURN_ID_REUSED,
    ),
)
async def post_message(
    request: Request,
    body: ChatMessageRequest,
    claims: TokenClaims = Depends(current_claims),
) -> ChatMessageResponse:
    store = get_store(request)

    # A conversation is normally started via POST /api/sessions; tolerate a
    # missing one by minting an id so a bare first message still works. Atomic
    # (HSETNX) so it can't race a concurrent upload minting its own.
    await store.ensure_conversation(claims.sid, str(uuid.uuid4()))

    query = (body.query or "").strip()
    if (
        not query
        and not body.followup_answers
        and not body.plan_approved
        and not body.plan_rejected
        and not body.upload_ids
    ):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request must include a query, followup_answers, a plan decision, or uploads.",
        )
    # Uploads with no caption is a supported flow (T-1): supply the neutral default
    # query the agent expects (ports message_handler.py:227) so the turn isn't empty.
    if not query and body.upload_ids:
        query = "Please process the uploaded file(s)."

    turn_id = body.turn_id or str(uuid.uuid4())
    if not await store.start_turn(claims.sid, turn_id):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=_TURN_ID_REUSED,
        )
    event_bus = _get_event_bus(request)
    on_status = _make_on_status(event_bus, claims.sid, turn_id)
    user_token = await identity.mint_for_user(claims.sub)

    lease = asyncio.create_task(_keep_turn_alive(store, claims.sid, turn_id))
    try:
        response = await chat_service.handle_turn(
            _get_a2a_client(),
            store,
            claims.sid,
            turn_id=turn_id,
            query=query,
            followup_answers=body.followup_answers,
            plan_approved=body.plan_approved,
            plan_rejected=body.plan_rejected,
            workflow_id=body.workflow_id,
            uploaded_files=chat_service.upload_descriptors_to_dicts(body.upload_ids),
            auto_approve=settings.auto_approve_steps,
            on_status=on_status,
            user_token=user_token,
        )
    except Exception as exc:
        # Mirror message_handler's inline "Error communicating with agent"; the
        # frontend renders an error-status response rather than handling a 500.
        logger.warning("Chat turn %s failed: %s", turn_id, exc)
        response = ChatMessageResponse(
            turn_id=turn_id,
            status=ChatStatus.ERROR,
            message=f"Error communicating with agent: {exc}",
        )
        await _end_lease(lease)
        await _deliver(store, event_bus, claims.sid, response)
        return response
    except BaseException:
        # Cancelled (e.g. the worker shuts down): stop renewing, so the lease runs out and
        # a client asking about this turn hears 404 rather than "running".
        await _end_lease(lease)
        raise
    await _end_lease(lease)

    # T-4: a fast-finishing backgrounded task can reach a terminal state before the SSE
    # subscriber sees the event; re-check the node once so its completion isn't lost.
    if event_bus is not None and response.task_id and response.status == ChatStatus.BACKGROUNDED:
        try:
            await events_service.reconcile_backgrounded(
                event_bus,
                store,
                claims.sid,
                get_redis(request),
                response.task_id,
                auto_approve=settings.auto_approve_steps,
            )
        except Exception as exc:  # reconcile is best-effort; never fail the response
            logger.warning("Reconcile of backgrounded task %s failed: %s", response.task_id, exc)
    await _deliver(store, event_bus, claims.sid, response)
    return response


async def _end_lease(lease: "asyncio.Task[None]") -> None:
    """Stop renewing the turn's lease, and wait until it has stopped: ``finish_turn`` must
    not be followed by a renewal, which would cut the stored result's TTL to the lease's."""
    lease.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await lease


async def _deliver(store, event_bus, sid: str, response: ChatMessageResponse) -> None:
    """Store the finished turn and announce it with ``turn_done``, besides returning it.

    The POST reply is one of two ways the result reaches the page: a proxy or a network
    change can drop a long-held request after the turn has finished. The stored state
    answers ``GET /api/chat/turns/{turn_id}`` for a client whose event stream was down
    too. Best effort: a Valkey blip must not turn a finished turn into a 500.
    """
    try:
        await store.finish_turn(sid, response.turn_id, response.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to store the result of turn %s: %s", response.turn_id, exc)
    if event_bus is not None:
        await event_bus.publish(sid, TurnDoneEvent(turn_id=response.turn_id, response=response))


@router.get(
    "/turns/{turn_id}",
    response_model=TurnStateResponse,
    responses=error(
        http_status.HTTP_404_NOT_FOUND,
        "This session has no such turn: it never started, its result expired, the worker running "
        "it stopped, or it belongs to another session.",
        _NO_SUCH_TURN,
    ),
)
async def get_turn(
    request: Request,
    turn_id: str = Path(pattern=TURN_ID_PATTERN),
    claims: TokenClaims = Depends(current_claims),
) -> TurnStateResponse:
    """A turn's state: ``running``, or ``done`` with the response its POST returned.

    For a client that lost track of a turn: its POST failed at the network level, or its
    event stream reconnected while the turn was in flight. Read once at those moments;
    the ``turn_done`` event is the normal path, so don't poll this. 404 when this session
    has no such turn (never started, expired, its worker stopped, or another session's).
    """
    state = await get_store(request).get_turn(claims.sid, turn_id)
    if state is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=_NO_SUCH_TURN)
    if state.get("state") == "done" and isinstance(state.get("response"), dict):
        return TurnStateResponse(
            turn_id=turn_id, state="done", response=ChatMessageResponse.model_validate(state["response"])
        )
    return TurnStateResponse(turn_id=turn_id, state="running")
