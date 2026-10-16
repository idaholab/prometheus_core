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

"""Conversation history: list, fetch, rename, soft-delete, and resume.

``GET /api/conversations/recent`` replaces the Chainlit ``/history`` slash command
(``_handle_conversation_history``, frontend/main.py:107): returns recent conversation
summaries as JSON instead of a markdown ``cl.Message``. Slash-command parsing is now
a frontend concern.

The rest of this router is new (chat-history feature): ``GET /{id}`` fetches one
past conversation's transcript, ``PATCH``/``DELETE`` let a user rename or soft-delete
it, and ``POST /{id}/resume`` rebinds the caller's session to it so the next chat
turn continues that conversation rather than starting a fresh one.

``ConversationStateClient`` (app/conversation_state.py) uses the **synchronous**
redis client, so every call is offloaded to a worker thread with
``asyncio.to_thread`` to keep the event loop free. When Redis is unreachable,
``recent`` degrades to ``{available: false, conversations: []}`` with a 200; the
per-conversation endpoints 404 instead, since there's nothing to act on.

Every per-conversation endpoint checks ownership (``user:convs:{user}`` via
``ConversationStateClient.owns``) and returns **404** — not 403 — on a miss, so a
guess at another user's conversation id can't even confirm the id exists.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, Optional, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status as http_status

from app.api_responses import AUTH_RESPONSES
from app.config import settings
from app.contract import (
    ConversationDetailResponse,
    ConversationHistoryResponse,
    ConversationMessage,
    ConversationRenameRequest,
    ConversationResumeRequest,
    ConversationSummary,
)
from app.conversation_state import ConversationStateClient
from app.security import TokenClaims, current_claims
from app.services.artifacts import is_user_upload, shape_artifacts
from app.services.mesh.service import enrich_mesh_artifact_dicts
from app.sessions import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["conversations"], responses=AUTH_RESPONSES)


# One client reused across requests (AU-7): ConversationStateClient caches its Redis
# connection, so a shared instance avoids a fresh connect + ping per call. Keyed on the
# class object (not id()) so tests monkeypatching ``ConversationStateClient`` get their
# own instance without id-reuse hazards, while the class is kept alive as the cache key.
_client_cache: dict = {}


def _client() -> ConversationStateClient:
    cls = ConversationStateClient
    inst = _client_cache.get(cls)
    if inst is None:
        inst = cls(settings.redis_url)
        _client_cache[cls] = inst
    return inst


def _fetch_recent(limit: int, user_id: str) -> tuple[bool, list[dict]]:
    """Blocking Redis read, run in a worker thread.

    Returns ``(available, rows)``: ``available`` distinguishes "Redis down" from
    "Redis up but empty" (both yield an empty ``rows``). ``user_id`` scopes the
    result to the caller's own conversations (see ``ConversationStateClient``).
    """
    client = _client()
    if not client.available:
        return False, []
    return True, client.get_conversation_history(limit=limit, user_id=user_id)


@router.get("/conversations/recent", response_model=ConversationHistoryResponse)
async def get_recent_conversations(
    limit: int = Query(20, ge=1, le=100),
    claims: TokenClaims = Depends(current_claims),
) -> ConversationHistoryResponse:
    available, rows = await asyncio.to_thread(_fetch_recent, limit, claims.sub)
    return ConversationHistoryResponse(
        available=available,
        conversations=[ConversationSummary(**row) for row in rows],
    )


def _fetch_detail_parts(conv_id: str, user_id: str) -> tuple[bool, dict[str, Any] | None]:
    """Blocking ownership check + raw store reads, run in a worker thread.

    Returns ``(found, parts_or_none)``: ``found`` is ``False`` when Redis is down,
    the conversation doesn't exist, it isn't owned by *user_id*, or it is soft-deleted
    -- the caller maps that uniformly to 404 so a non-owner can't distinguish "doesn't
    exist" from "not yours". A soft-deleted conversation must 404 here too, not only
    drop out of ``recent``: a tab that still remembers its id would otherwise resume
    it on reload and append the next turn to a conversation the user deleted.

    Stops at the *raw* artifact dicts rather than returning a finished response,
    because mesh enrichment (:func:`_build_detail`) is async and must run on the event
    loop, not in this thread.
    """
    client = _client()
    if not client.available or not client.owns(user_id, conv_id):
        return False, None
    meta = client.get_meta(conv_id)
    if meta.get("hidden"):
        return False, None
    conv = client.get_conversation(conv_id) or {}
    return True, {
        "title": meta.get("title_override") or conv.get("title") or conv.get("user_query", ""),
        "profile": str(conv.get("profile") or ""),
        "messages": client.get_transcript(conv_id),
        "raw_artifacts": client.get_artifacts(conv_id),
    }


async def _build_detail(conv_id: str, parts: dict[str, Any]) -> ConversationDetailResponse:
    """Turn :func:`_fetch_detail_parts` output into the response, enriching meshes.

    Enriches ``parts["raw_artifacts"]`` **in place**, so a caller holding that list (the
    resume path, which seeds the session catalog from it) sees the enriched dicts.

    The mesh pass is what makes restored conversations mount the interactive
    MeshViewer: the frontend adapter only builds a viewer element when a mesh
    artifact's ``json_body`` carries the VTP manifest, and the persisted catalog has
    ``json_body: None`` (the live turn's manifest is computed on the fly and never
    written back). Without this the whole restored transcript degrades to download
    cards. Enrichment is content-hash cached, so a conversation whose meshes were
    already converted live costs a cache hit -- but a cache miss is a VTK conversion per
    mesh, which is why the resume path rebinds the session *before* calling this.
    """
    raw_artifacts = cast(list[dict[str, Any]], parts["raw_artifacts"])
    await enrich_mesh_artifact_dicts(raw_artifacts)

    messages = cast(list[dict[str, Any]], parts["messages"])
    return ConversationDetailResponse(
        conversation_id=conv_id,
        title=cast(str, parts["title"]),
        profile=cast(str, parts["profile"]),
        messages=[ConversationMessage(**m) for m in messages],
        # User uploads stay in the session catalog (the content proxy and later turns
        # resolve them) but not in the response: the Artifact Contract excludes them
        # from rendering, and the live turn already drops them from `new_artifacts`.
        artifacts=shape_artifacts([a for a in raw_artifacts if not is_user_upload(a)]),
    )


async def _fetch_parts_or_404(conv_id: str, user_id: str) -> dict[str, Any]:
    found, parts = await asyncio.to_thread(_fetch_detail_parts, conv_id, user_id)
    if not found or parts is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return parts


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation_detail(
    conversation_id: str,
    claims: TokenClaims = Depends(current_claims),
) -> ConversationDetailResponse:
    parts = await _fetch_parts_or_404(conversation_id, claims.sub)
    return await _build_detail(conversation_id, parts)


def _rename(conv_id: str, user_id: str, title: str) -> bool:
    client = _client()
    if not client.available or not client.owns(user_id, conv_id):
        return False
    return client.set_title_override(conv_id, title)


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    body: ConversationRenameRequest,
    claims: TokenClaims = Depends(current_claims),
) -> ConversationSummary:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title must not be empty")
    ok = await asyncio.to_thread(_rename, conversation_id, claims.sub, title)
    if not ok:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return ConversationSummary(conversation_id=conversation_id, title=title)


def _soft_delete(conv_id: str, user_id: str) -> bool:
    client = _client()
    if not client.available or not client.owns(user_id, conv_id):
        return False
    return client.set_hidden(conv_id, True)


@router.delete("/conversations/{conversation_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    claims: TokenClaims = Depends(current_claims),
) -> None:
    """Soft delete: hides the conversation from ``recent``, and ``GET /{id}`` and
    ``/resume`` answer 404 for it. The underlying ``conversation:{id}`` document (and
    its artifacts) are left intact."""
    ok = await asyncio.to_thread(_soft_delete, conversation_id, claims.sub)
    if not ok:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Conversation not found")


@router.post("/conversations/{conversation_id}/resume", response_model=ConversationDetailResponse)
async def resume_conversation(
    conversation_id: str,
    request: Request,
    body: Optional[ConversationResumeRequest] = Body(default=None),
    claims: TokenClaims = Depends(current_claims),
) -> ConversationDetailResponse:
    """Rebind the caller's session to a past conversation so the next chat turn
    continues it. Returns its transcript + artifact catalog in the same call so
    the frontend can render history and resume in one round-trip.

    Rebinds first, enriches meshes second. Enrichment can take seconds per mesh on a
    cache miss, and the frontend lets the user click elsewhere meanwhile; the rebind
    itself is ordered by ``bind_seq`` (see ``SessionStore.reset``), so a newer click
    always wins regardless of which request finishes last. The enriched catalog is then
    written back only if the session is still on this conversation, with the catalog
    the rebind seeded."""
    parts = await _fetch_parts_or_404(conversation_id, claims.sub)
    raw_artifacts = cast(list[dict[str, Any]], parts["raw_artifacts"])

    store = get_store(request)
    # Resuming the conversation the session is already on (the reload path) keeps the
    # awaited-task set, so a task backgrounded before the reload still streams its
    # `task_progress` / `task_done` into the resumed session -- the ids live in
    # Valkey, not in a process-local SessionState. Switching to a *different* conversation still
    # clears it: those ids only resolve against the conversation that produced them.
    # SessionStore.reset decides which, atomically. Either way the history sidebar marks
    # a conversation pending while `agent:status:{id}` is live, and the result lands in
    # the transcript.
    #
    # ``raw_artifacts`` is the catalog _fetch_detail_parts already read; seeding it here
    # avoids re-reading Redis, and the content proxy resolves artifact ids out of it.
    # If a newer rebind already won, this is a no-op -- the response is still returned
    # and the frontend discards it as superseded.
    await store.reset(
        claims.sid,
        conversation_id,
        artifacts=raw_artifacts,
        bind_seq=body.bind_seq if body else None,
    )

    # _build_detail enriches raw_artifacts in place, so keep the list reset just seeded.
    seeded = copy.deepcopy(raw_artifacts)
    detail = await _build_detail(conversation_id, parts)
    # Required, not cosmetic: artifact_identity hashes json_body for an artifact with no
    # explicit id, so the ids in this response only resolve against the enriched catalog.
    # Guarded: skipped if the user has moved on in the meantime, or if a turn or task of
    # this conversation wrote a newer catalog while the meshes were converting.
    await store.replace_seeded_artifacts(claims.sid, raw_artifacts, conversation_id=conversation_id, seeded=seeded)

    detail.auto_approve_steps = settings.auto_approve_steps
    return detail
