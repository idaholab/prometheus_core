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

"""POST /api/uploads — stage one file to DeepLynx via the agent (decision D5).

Auth-required. Streams the multipart ``UploadFile`` to a temp path (enforcing
``MAX_UPLOAD_BYTES`` as it goes so an over-limit file is never fully buffered),
guesses its MIME, and stages it against the session's ``conversation_id`` through
``A2AClient.stage_upload``. Returns the :class:`UploadDescriptor` the frontend
echoes back in the next ``POST /api/chat/messages`` ``upload_ids``.

One file per request — the simplest match for the React ``Chat.tsx`` per-file
upload flow (task 06).
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status as http_status

from app import identity
from app.api_responses import AUTH_RESPONSES
from app.a2a_client import A2AClient
from app.config import settings
from app.contract import UploadDescriptor
from app.security import TokenClaims, current_claims
from app.services import uploads as upload_service
from app.sessions import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["uploads"], responses=AUTH_RESPONSES)

_CHUNK_SIZE = 1024 * 1024


def _get_a2a_client() -> A2AClient:
    return A2AClient(agent_url=settings.agent_url, agent_secret=settings.agent_secret)


async def _spool_to_temp(upload: UploadFile) -> tuple[Path, int]:
    """Stream the upload to a temp file, aborting early if it exceeds the limit.

    Returns ``(path, size_bytes)``. Raises :class:`upload_service.UploadTooLargeError`
    (after removing the partial temp file) once the running total crosses
    ``MAX_UPLOAD_BYTES`` — so an over-limit upload is never fully written to disk.
    """
    suffix = Path(upload.filename or "").suffix
    fd, tmp_name = tempfile.mkstemp(suffix=suffix, prefix="chat-upload-")
    tmp_path = Path(tmp_name)
    size = 0
    try:
        with open(fd, "wb") as out:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > upload_service.MAX_UPLOAD_BYTES:
                    raise upload_service.UploadTooLargeError(upload.filename or "upload", size)
                out.write(chunk)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path, size


@router.post("/uploads", response_model=UploadDescriptor)
async def post_upload(
    request: Request,
    file: UploadFile = File(...),
    claims: TokenClaims = Depends(current_claims),
) -> UploadDescriptor:
    store = get_store(request)

    # Uploads attach to a conversation; mint one if a file arrives before the first
    # POST /api/sessions (mirrors the tolerance in routers/chat.py). Atomic, because the
    # frontend uploads every selected file in parallel: a read-then-write here let each
    # request mint its own id and stage its file under a different conversation.
    conversation_id = await store.ensure_conversation(claims.sid, str(uuid.uuid4()))

    name = file.filename or "upload"

    try:
        tmp_path, size = await _spool_to_temp(file)
    except upload_service.UploadTooLargeError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=upload_service.upload_limit_message(exc.name),
        ) from exc

    try:
        return await upload_service.stage_upload(
            _get_a2a_client(),
            tmp_path,
            name=name,
            conversation_id=conversation_id,
            element_mime=file.content_type,
            size_bytes=size,
            user_token=await identity.mint_for_user(claims.sub),
        )
    except upload_service.UploadStagingError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
