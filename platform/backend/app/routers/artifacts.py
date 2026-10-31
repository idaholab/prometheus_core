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

"""GET /api/artifacts/{artifact_id}/content — resolve + stream artifact bytes (D3).

Auth-required. Looks the id up in the session's artifact catalog (populated by the
turn orchestrator, task 04), resolves its URI to local bytes via
``uri_resolver.resolve_to_local_path`` (``file://`` / ``http(s)://`` / ``deeplynx://``),
and streams the file with the correct ``Content-Type`` and an ``inline`` disposition.
For inline-only artifacts (``json_body`` / text, no URI) it serializes the content
via :func:`app.services.artifacts.artifact_download_payload`.

Consolidates Chainlit's ``_render_pdf_artifact`` / ``_render_remote_file_artifact`` /
``_render_file_artifact`` / ``_render_download_artifact`` into one endpoint; the React
viewers fetch bytes from here instead of the server building elements (task 07).
"""

from __future__ import annotations

import logging
import mimetypes
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app import uri_resolver
from app.api_responses import AUTH_RESPONSES
from app.openapi import TAG_ARTIFACTS
from app.security import TokenClaims, current_claims
from app.services.artifacts import (
    artifact_download_payload,
    artifact_identity,
    classify_render_hint,
    report_file_id,
)
from app.services.mesh.service import mesh_cache_root
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
            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not resolve artifact {artifact_id!r} from {uri!r}.",
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


# The report runs its own scripts (Plotly figures), so it is served as an opaque
# origin: no access to the platform's cookies, storage or DOM, even when opened
# directly in a tab rather than through the viewer's sandboxed iframe. Popups it
# opens stay sandboxed too, and it may not make network requests of its own.
_REPORT_CSP = "sandbox allow-scripts allow-popups; connect-src 'none'"
# A baked notebook with inline Plotly is a few MB; refuse anything far larger.
_MAX_REPORT_BYTES = 64 * 1024 * 1024
_REPORT_UNAVAILABLE = "The report could not be loaded from storage."


@router.get("/artifacts/{artifact_id}/report")
async def get_artifact_report(
    artifact_id: str,
    request: Request,
    claims: TokenClaims = Depends(current_claims),
) -> Response:
    """The baked HTML report a producer attached to an artifact (``metadata.report``).

    A UQ notebook artifact carries ``metadata.report = {"uri": "deeplynx://.../items/{id}"}``
    pointing at the static HTML export of the notebook, stored in DeepLynx next to the
    notebook itself. Only ``deeplynx://`` is served, and the file id comes from the
    URI's item id (``services.artifacts.report_file_id``), so no service shares a disk
    with the agent and the producer cannot point the backend at another address.
    """
    store = get_store(request)
    session = await store.get_or_create(claims.sid)

    artifact = _find_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Artifact {artifact_id!r} is not in this session's catalog.",
        )

    file_id = report_file_id(artifact)
    if file_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Artifact {artifact_id!r} has no report.",
        )
    uri = str(artifact["metadata"]["report"]["uri"])

    name = f"{Path(str(artifact.get('name') or 'report')).stem}.html"
    # Resolve as its own artifact: the report's file id (from its URI), not the notebook's.
    report_artifact = {"name": name, "metadata": {"deeplynx_file_id": file_id}}
    cache_dir = Path(tempfile.mkdtemp(prefix="chat-report-"))
    try:
        local_path = await uri_resolver.resolve_to_local_path(
            uri,
            cache_dir=cache_dir,
            artifact=report_artifact,
            artifact_id=f"{artifact_id}-report",
        )
        if local_path is None or not local_path.is_file():
            logger.warning("Report of artifact %r (DeepLynx file %d) could not be resolved", artifact_id, file_id)
            raise HTTPException(status_code=http_status.HTTP_502_BAD_GATEWAY, detail=_REPORT_UNAVAILABLE)
        if local_path.stat().st_size > _MAX_REPORT_BYTES:
            logger.warning("Report of artifact %r (DeepLynx file %d) exceeds the size cap", artifact_id, file_id)
            raise HTTPException(status_code=http_status.HTTP_502_BAD_GATEWAY, detail=_REPORT_UNAVAILABLE)
    except BaseException:
        # Clean up on every failure, including a resolver that raises.
        shutil.rmtree(cache_dir, ignore_errors=True)
        raise
    return FileResponse(
        path=str(local_path),
        media_type="text/html",
        headers={
            **_content_disposition(name, "inline"),
            "Content-Security-Policy": _REPORT_CSP,
            "X-Content-Type-Options": "nosniff",
            # Per-user (the session's catalog), so never in a shared cache.
            "Cache-Control": "private, max-age=300",
        },
        background=BackgroundTask(shutil.rmtree, str(cache_dir), ignore_errors=True),
    )


def _reject_unsafe_segment(value: str) -> None:
    """Reject any path segment that isn't a single safe name (path-traversal guard)."""
    if not _MESH_SEGMENT_RE.match(value) or ".." in value:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid mesh path.")


@router.get("/artifacts/mesh/{dataset_id}/{filename}")
async def get_mesh_file(
    dataset_id: str,
    filename: str,
    claims: TokenClaims = Depends(current_claims),
) -> Response:
    """Serve a converted VTP timestep for the React MeshViewer (auth-required).

    A mesh artifact's ``json_body.baseUrl`` is ``/api/artifacts/mesh/{dataset_id}``
    (see ``services/mesh/service.py``); the viewer fetches each
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
