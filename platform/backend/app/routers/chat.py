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
artifact catalog), mints a ``turn_id``, and runs one turn via
``services.chat.handle_turn``. Live status streams through an ``on_status``
closure that publishes :class:`StatusEvent`s onto the session event bus; the SSE
endpoint (task 05) drains them keyed by ``sid``.

Errors from ``A2AClient.send`` are caught and returned as an ``error``-status
``ChatMessageResponse`` (not a 500), mirroring the Chainlit handler's inline
"Error communicating with agent" message so the frontend renders it in the chat.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status

from app import identity
from app.api_responses import AUTH_RESPONSES
from app.a2a_client import A2AClient
from app.config import settings
from app.contract import ChatMessageRequest, ChatMessageResponse, ChatStatus, StatusEvent
from app.redis_client import get_redis
from app.security import TokenClaims, current_claims
from app.services import chat as chat_service
from app.services import events as events_service
from app.sessions import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"], responses=AUTH_RESPONSES)

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


@router.post("/messages", response_model=ChatMessageResponse)
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

    turn_id = str(uuid.uuid4())
    event_bus = _get_event_bus(request)
    on_status = _make_on_status(event_bus, claims.sid, turn_id)
    user_token = await identity.mint_for_user(claims.sub)

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
        return ChatMessageResponse(
            turn_id=turn_id,
            status=ChatStatus.ERROR,
            message=f"Error communicating with agent: {exc}",
        )

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
    return response
