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

"""POST /api/sessions — start a conversation for the authenticated session.

Replaces Chainlit's ``on_chat_start``: mints a fresh ``conversation_id``, records
it (and the chosen profile) on the session, and returns the client
bootstrap payload. For the beginner profile it includes the workflow suggestions,
mirroring the ``chat_profile == "Beginner Chat"`` branch in ``frontend/main.py``.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from app.api_responses import AUTH_RESPONSES
from app.config import settings
from app.contract import CreateSessionRequest, SessionResponse
from app.routers.config import BEGINNER_PROFILE, CHAT_PROFILES
from app.security import TokenClaims, current_claims
from app.sessions import get_store

router = APIRouter(prefix="/api", tags=["sessions"], responses=AUTH_RESPONSES)

# Selectable profile names (AU-8): a client-supplied profile is validated against these.
_VALID_PROFILES = {p.name for p in CHAT_PROFILES}


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: Request,
    body: Optional[CreateSessionRequest] = Body(default=None),
    claims: TokenClaims = Depends(current_claims),
) -> SessionResponse:
    """Create a new conversation under the caller's session identity.

    A second call reuses the same session (keyed by the JWT ``sid``) but mints a
    fresh ``conversation_id``, so the user can start a new conversation without
    re-authenticating.
    """
    store = get_store(request)
    state = await store.get_or_create(claims.sid)

    requested = body.profile if body else None
    if requested is not None and requested not in _VALID_PROFILES:
        # AU-8: reject an unknown profile rather than silently falling through to the
        # no-suggestions ("advanced") behavior and persisting an arbitrary string.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown profile {requested!r}",
        )

    profile = requested or state.profile or BEGINNER_PROFILE
    conversation_id = str(uuid.uuid4())

    # One pipeline: rebind the conversation, record the profile, and clear the
    # artifact catalog and the awaited-task set -- a new conversation starts with
    # neither. ``SessionState`` is a frozen snapshot, so this is the only way to
    # write; assigning to ``state`` would raise rather than silently do nothing.
    # ``bind_seq`` keeps a slower, older resume from rebinding over this afterwards.
    await store.reset(claims.sid, conversation_id, profile=profile, bind_seq=body.bind_seq if body else None)

    suggestions = settings.workflow_suggestions if profile == BEGINNER_PROFILE else []

    return SessionResponse(
        conversation_id=conversation_id,
        profile=profile,
        chat_intro=settings.chat_intro,
        chat_suggestion_title=settings.chat_suggestion_title,
        workflow_suggestions=suggestions,
        auto_approve_steps=settings.auto_approve_steps,
    )
