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

"""Artifact content routes — resolve + stream artifact bytes (D3).

``GET /api/conversations/{conversation_id}/artifacts/{artifact_id}/content`` is the
route ``ArtifactMeta.content_url`` names. It checks the caller may read the
conversation, then reads the artifact from that conversation's catalog in Valkey
(``artifacts:conv:{id}:by_id``, written by the agents' ``ArtifactRegistry``). It does
not depend on the session: the session catalog follows whichever conversation the
login last bound, and every tab of that login shares it, so a tab showing one
conversation while another tab opens a second one would 404 on its own artifacts.

``GET /api/artifacts/{artifact_id}/content`` is the older, session-scoped route. It
stays until no client builds its URL.

Both are auth-required, resolve the artifact's URI to local bytes via
``uri_resolver.resolve_to_local_path`` (``file://`` / ``http(s)://`` / ``deeplynx://``),
and streams the file with the correct ``Content-Type`` and an ``inline`` disposition.
For inline-only artifacts (``json_body`` / text, no URI) it serializes the content
via :func:`app.services.artifacts.artifact_download_payload`.

Consolidates Chainlit's ``_render_pdf_artifact`` / ``_render_remote_file_artifact`` /
``_render_file_artifact`` / ``_render_download_artifact`` into one endpoint; the React
viewers fetch bytes from here instead of the server building elements (task 07).
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Request, status as http_status
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app import uri_resolver
from app.api_responses import AUTH_RESPONSES, error
from app.conversation_state import ConversationStateClient, shared_client
from app.openapi import SESSION_COOKIE, TAG_ARTIFACTS
from app.security import TokenClaims, current_claims
from app.services.artifacts import artifact_download_payload, artifact_identity, classify_render_hint
from app.services.mesh.service import mesh_cache_root, mesh_props
from app.sessions import SessionState, get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=[TAG_ARTIFACTS], responses=AUTH_RESPONSES)

# Render hints served as a browser download rather than viewed inline.
_DOWNLOAD_HINTS = {"file", "unknown"}

# One safe path segment (no separators; `..` additionally rejected below). Guards the
# dataset_id/filename the browser sends to the mesh VTP route.
_MESH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _find_artifact(session: SessionState, artifact_id: str) -> Optional[dict[str, Any]]:
    """Locate an artifact in the session catalog by its identity (A-4).

    Uses the same :func:`artifact_identity` the wire ``ArtifactMeta`` was built with,
    so a synthetic id minted for an id-less artifact still round-trips to its raw dict
    (and an empty id can never match the first id-less entry)."""
    for artifact in session.artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact_identity(artifact) == artifact_id:
            return artifact
    return None


def _client() -> ConversationStateClient:
    # Looked up here, so tests can patch ``ConversationStateClient`` in this module.
    return shared_client(ConversationStateClient)


def _lookup(conversation_id: str, artifact_id: str, user_id: str, bound: bool) -> Optional[dict[str, Any]]:
    """Blocking access check + catalog read, run in a worker thread.

    ``None`` when Valkey is down, the caller may not read the conversation, or the
    artifact is not in its catalog. The caller maps all of them to one 404, so a
    non-owner can't probe which ids exist.
    """
    client = _client()
    if not client.available:
        return None
    # ``bound`` skips the ownership check. That is sound only because a session's
    # conversation id is server-minted or set by an ownership-checked resume; see
    # ``SessionStore.reset``, which every binding goes through.
    if not bound and not client.owns(user_id, conversation_id):
        return None
    # A soft-deleted conversation answers 404 everywhere else (``_owned_meta``), and
    # its artifacts must not outlive the delete either, even in a tab still bound to it.
    if client.get_meta(conversation_id).get("hidden"):
        return None
    return client.get_artifact(conversation_id, artifact_id)


def _download_filename(name: str, extension: str) -> str:
    """Ensure a safe basename carrying ``extension`` (ports ``_download_filename``)."""
    filename = Path(str(name or "artifact")).name or "artifact"
    if extension and not Path(filename).suffix:
        filename = f"{filename}{extension}"
    return filename


def _content_disposition(filename: str, disposition: str) -> dict[str, str]:
    """Build a safe ``Content-Disposition`` header (A-5/A-6).

    ``disposition`` is ``inline`` for viewer/browser-renderable content and
    ``attachment`` for downloads. The filename is emitted both as a sanitized ASCII
    ``filename`` and an RFC 5987 ``filename*``, so a quote/backslash/newline/unicode in
    the artifact name can't break out of or inject into the header.
    """
    ascii_name = "".join(c for c in filename if c.isprintable() and c not in '"\\')
    ascii_name = ascii_name.encode("ascii", "ignore").decode() or "artifact"
    encoded = quote(filename, safe="")
    return {"Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"}


_CONVERSATION_ID = PathParam(description="The conversation the artifact belongs to.")
_ARTIFACT_ID = PathParam(description="The artifact's id, as in `ArtifactMeta.artifact_id`.")

# The bytes' type is the artifact's own MIME type, so the document can only say "a file".
_FILE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The artifact's bytes, with its MIME type as `Content-Type`.",
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@router.get(
    "/conversations/{conversation_id}/artifacts/{artifact_id}/content",
    summary="Download an artifact of a conversation",
    response_class=Response,
    dependencies=[Depends(SESSION_COOKIE)],
    responses={
        **_FILE_RESPONSE,
        **error(
            http_status.HTTP_404_NOT_FOUND,
            "The caller may not read the conversation, the artifact isn't in its catalog, "
            "or the artifact has nothing to serve.",
            "Artifact not found",
        ),
        **error(http_status.HTTP_502_BAD_GATEWAY, "The artifact's URI could not be resolved."),
    },
)
async def get_conversation_artifact_content(
    request: Request,
    conversation_id: str = _CONVERSATION_ID,
    artifact_id: str = _ARTIFACT_ID,
    claims: TokenClaims = Depends(current_claims),
) -> Response:
    """Stream an artifact of a conversation the caller may read, inline for viewable
    types and as an attachment for downloads. `ArtifactMeta.content_url` names this route.

    The caller may read a conversation they own, or the one their session is bound to.
    Unlike `GET /api/artifacts/{artifact_id}/content`, the result doesn't depend on
    which conversation the session is on, so every tab of a login can show its own.
    \f
    The bound case covers a first turn whose ownership record is not visible yet; it is
    sound because a session's ``conversation_id`` is only server-minted or set by an
    ownership-checked resume.
    """
    artifact = await _readable_artifact(conversation_id, artifact_id, request, claims)
    return await _serve(artifact, artifact_id)


async def _readable_artifact(
    conversation_id: str, artifact_id: str, request: Request, claims: TokenClaims
) -> dict[str, Any]:
    """The raw catalog dict, if the caller may read *conversation_id*; else a 404."""
    session = await get_store(request).get(claims.sid)
    bound = session is not None and session.conversation_id == conversation_id
    artifact = await asyncio.to_thread(_lookup, conversation_id, artifact_id, claims.sub, bound)
    if artifact is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return artifact


@router.get(
    "/conversations/{conversation_id}/artifacts/{artifact_id}/mesh",
    summary="Get a mesh artifact's viewer data",
    response_model=dict[str, Any],
    response_description="The MeshViewer props, the same object a live turn puts in a mesh artifact's "
    "`json_body`: `datasetId`, `baseUrl`, `title`, `metadata`, `manifest`, `initialTimestep`, "
    "`initialVariable`, `initialColorPreset`, `height`, `showControls`, `allowPicking`.",
    dependencies=[Depends(SESSION_COOKIE)],
    responses={
        **error(
            http_status.HTTP_404_NOT_FOUND,
            "The caller may not read the conversation, the artifact isn't in its catalog, or it isn't a mesh.",
            "Artifact not found",
            "Artifact is not a mesh",
        ),
        **error(http_status.HTTP_422_UNPROCESSABLE_CONTENT, "The mesh could not be read or converted."),
    },
)
async def get_conversation_artifact_mesh(
    request: Request,
    conversation_id: str = _CONVERSATION_ID,
    artifact_id: str = _ARTIFACT_ID,
    claims: TokenClaims = Depends(current_claims),
) -> dict[str, Any]:
    """Return the MeshViewer data for a mesh artifact (Exodus or STL), converting it to
    VTP on the first request. `ArtifactMeta.mesh_url` names this route.

    The first request for a mesh can take seconds; later ones read the stored
    conversion. Requests for the same mesh made while it converts wait for that one
    conversion. Same access rule as the content route. The VTP files the response
    points at are served by `GET /api/artifacts/mesh/{dataset_id}/{filename}`.
    \f
    See :func:`app.services.mesh.service.mesh_props` for the source index and the
    shared in-flight conversion.
    """
    artifact = await _readable_artifact(conversation_id, artifact_id, request, claims)
    if classify_render_hint(artifact) != "mesh":
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Artifact is not a mesh")
    props = await mesh_props(artifact)
    if props is None:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Could not convert {artifact.get('name') or 'this mesh'} for viewing.",
        )
    return props


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: str,
    request: Request,
    claims: TokenClaims = Depends(current_claims),
) -> Response:
    store = get_store(request)
    session = await store.get_or_create(claims.sid)

    artifact = _find_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Artifact {artifact_id!r} is not in this session's catalog.",
        )
    return await _serve(artifact, artifact_id)


async def _serve(artifact: dict[str, Any], artifact_id: str) -> Response:
    """Stream one raw catalog dict: its resolved URI, else its inline content."""
    name = str(artifact.get("name") or "artifact")
    mime_type = artifact.get("mime_type") or ""
    uri = artifact.get("uri") or ""
    # Downloads (file/unknown) get `attachment`; viewer/browser-renderable get `inline`.
    disposition = "attachment" if classify_render_hint(artifact) in _DOWNLOAD_HINTS else "inline"

    # 1. Resolvable URI → stream the local/downloaded file.
    if uri:
        # Per-request scratch dir so downloaded bytes don't accumulate for the service
        # lifetime; a BackgroundTask removes it after the response is sent (A-3). A
        # ``file://`` source resolves outside this dir, so cleanup never touches it.
        cache_dir = Path(tempfile.mkdtemp(prefix="chat-artifact-"))
        local_path = await uri_resolver.resolve_to_local_path(
            uri,
            cache_dir=cache_dir,
            artifact=artifact,
            artifact_id=artifact_id,
        )
        if local_path is None or not local_path.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            # The URI can carry a token (a presigned URL), so it goes to the log only.
            logger.warning("artifact %s: could not resolve %r", artifact_id, uri)
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail="Could not fetch the artifact's content.",
            )
        effective_mime = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return FileResponse(
            path=str(local_path),
            media_type=effective_mime,
            headers=_content_disposition(_download_filename(name, Path(local_path).suffix), disposition),
            background=BackgroundTask(shutil.rmtree, str(cache_dir), ignore_errors=True),
        )

    # 2. Inline-only content (json_body / text) → serialize and stream.
    payload = artifact_download_payload(artifact, mime_type)
    if payload is not None:
        content, extension, effective_mime = payload
        filename = _download_filename(name, extension)
        return Response(
            content=content,
            media_type=effective_mime,
            headers=_content_disposition(filename, disposition),
        )

    # 3. In catalog but nothing servable.
    raise HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail=f"Artifact {artifact_id!r} has no downloadable content.",
    )


def _reject_unsafe_segment(value: str) -> None:
    """Reject any path segment that isn't a single safe name (path-traversal guard)."""
    # A leading dot also covers the cache's private ``.index/`` directory.
    if not _MESH_SEGMENT_RE.match(value) or ".." in value or value.startswith("."):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid mesh path.")


@router.get("/artifacts/mesh/{dataset_id}/{filename}")
async def get_mesh_file(
    dataset_id: str,
    filename: str,
    claims: TokenClaims = Depends(current_claims),
) -> Response:
    """Serve a converted VTP timestep for the React MeshViewer (auth-required).

    The MeshViewer props (from an artifact's ``mesh_url``, or an older catalog's inline
    ``json_body``) carry ``baseUrl`` = ``/api/artifacts/mesh/{dataset_id}`` (see
    ``services/mesh/service.py``); the viewer fetches each
    ``${baseUrl}/${filename}`` from here. ``dataset_id`` is a content hash and the
    cached files are session-independent, so the guard is auth + path-traversal
    safety: both segments must be single safe names and the resolved path must stay
    inside the mesh cache root.
    """
    _reject_unsafe_segment(dataset_id)
    _reject_unsafe_segment(filename)

    root = mesh_cache_root().resolve()
    candidate = (root / dataset_id / filename).resolve()
    if not candidate.is_relative_to(root):  # defense in depth beyond the segment check
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid mesh path.")
    if not candidate.is_file():
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Mesh file not found.")

    return FileResponse(path=str(candidate), media_type="application/xml")
