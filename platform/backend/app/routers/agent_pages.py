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

"""Pages an agent serves for its artifacts, proxied through the platform.

An agent may attach a link to a page it serves itself (``metadata.links`` entry
``{"label", "path"}``, e.g. an interactive dashboard at ``/console/?run=7``). The
browser often cannot reach the agent (another host, the compose network), so the
platform serves the page instead:

1. ``GET /api/artifacts/{artifact_id}/links/{n}`` (session cookie): the artifact must be
   in the caller's catalog and its ``n``-th link must be a path link. Answers ``303`` to
   ``/api/agent-pages/{grant}/...``, where ``grant`` is a short-lived token signed for
   this session, artifact and link.
2. ``GET /api/agent-pages/{grant}/{rest}``: checks the grant (signature, expiry, session
   not logged out, artifact still in the catalog) and forwards the request to the
   producing agent's registered URL, under the link's directory only, with the agent's
   own registered credentials, as ``POST /a2a/{agent_name}`` does.

The page loads its scripts and data with relative URLs, which resolve under the grant
path, so every request it makes is checked the same way and none needs the session
cookie. The page runs in an opaque origin (CSP ``sandbox``): it can't read the
platform's cookies or DOM or call ``/api`` as the user, even though it is served from
the platform's host.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from urllib.parse import quote, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from app.api_responses import AUTH_RESPONSES
from app.config import settings
from app.openapi import TAG_ARTIFACTS
from app.redis_client import get_redis
from app.routers.agent_registry import REGISTRY_KEY
from app.routers.artifacts import _find_artifact
from app.security import TokenClaims, current_claims, is_revoked
from app.services.artifacts import agent_page_prefix, artifact_link_path
from app.sessions import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=[TAG_ARTIFACTS])

_GRANT_TYP = "agent-page"
_GRANT_ALG = "HS256"
#: How long one opened page keeps working (its later requests reuse the grant).
GRANT_TTL = timedelta(hours=1)
#: An agent page is a few static files and JSON; don't wait on a stuck agent for long.
AGENT_PAGE_TIMEOUT_S = 30.0

# The page runs in an opaque origin: scripts and popups, but no access to the
# platform's cookies, storage or DOM. Its URL carries the grant, so no referrer.
_PAGE_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-popups",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-store",
    # The page's own fetches come from that opaque origin ("null"); the grant in the
    # URL is the credential, not a cookie, so they may read the responses.
    "Access-Control-Allow-Origin": "*",
}
# Relayed from the agent: the content, never its cookies, caching or security policy.
_RELAY_RESPONSE_HEADERS = ("content-type", "last-modified", "etag")


def _make_client() -> httpx.AsyncClient:
    """The upstream client for one proxied request (a seam for tests)."""
    return httpx.AsyncClient(timeout=AGENT_PAGE_TIMEOUT_S, follow_redirects=False)


def _not_found() -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="No such agent page.")


def issue_grant(sid: str, artifact_id: str, n: int) -> str:
    """A token for one artifact link, for one session, that expires after ``GRANT_TTL``."""
    now = datetime.now(timezone.utc)
    claims = {"typ": _GRANT_TYP, "sid": sid, "aid": artifact_id, "n": n, "iat": now, "exp": now + GRANT_TTL}
    return jwt.encode(claims, settings.jwt_secret, algorithm=_GRANT_ALG)


@router.get(
    "/artifacts/{artifact_id}/links/{n}",
    status_code=http_status.HTTP_303_SEE_OTHER,
    responses=AUTH_RESPONSES,
)
async def open_artifact_link(
    artifact_id: str,
    n: int,
    request: Request,
    claims: TokenClaims = Depends(current_claims),
) -> RedirectResponse:
    """Open the ``n``-th link of an artifact, a page its producing agent serves.

    ``303`` to the proxied page under ``/api/agent-pages/{grant}/``. ``404`` when the
    artifact is not in this session's catalog or that link is not a path link.
    """
    session = await get_store(request).get_or_create(claims.sid)
    artifact = _find_artifact(session, artifact_id)
    path = artifact_link_path(artifact, n) if artifact is not None else None
    prefix = agent_page_prefix(path) if path is not None else None
    if path is None or prefix is None:
        raise _not_found()
    grant = issue_grant(claims.sid, artifact_id, n)
    # The rest of the path, and the query, keep their meaning under the grant path.
    return RedirectResponse(
        f"/api/agent-pages/{grant}/{path[len(prefix) :]}",
        status_code=http_status.HTTP_303_SEE_OTHER,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


async def _granted_target(request: Request, grant: str, rest: str) -> tuple[str, dict[str, str]]:
    """The agent URL a granted request goes to, and the agent's own headers; else 404."""
    try:
        claims = jwt.decode(grant, settings.jwt_secret, algorithms=[_GRANT_ALG])
    except jwt.InvalidTokenError as exc:
        raise _not_found() from exc
    if claims.get("typ") != _GRANT_TYP or not isinstance(claims.get("n"), int):
        raise _not_found()
    sid, artifact_id, n = str(claims.get("sid") or ""), str(claims.get("aid") or ""), int(claims["n"])
    redis = get_redis(request)
    if not sid or await is_revoked(redis, sid):
        raise _not_found()
    session = await get_store(request).get(sid)
    artifact = _find_artifact(session, artifact_id) if session is not None else None
    path = artifact_link_path(artifact, n) if artifact is not None else None
    prefix = agent_page_prefix(path) if path is not None else None
    if artifact is None or prefix is None:
        raise _not_found()
    # Only inside the link's directory: no way up and out of it, and no second host.
    segments = rest.split("/")
    if rest.startswith("/") or "\\" in rest or any(seg in (".", "..") for seg in segments):
        raise _not_found()

    metadata = artifact.get("metadata")
    producer = artifact.get("producer_agent_id") or (
        metadata.get("producer_agent_id") if isinstance(metadata, dict) else None
    )
    raw = await redis.hget(REGISTRY_KEY, str(producer)) if producer else None
    if raw is None:
        raise _not_found()
    stored: dict[str, Any] = json.loads(raw)
    parts = urlsplit(str(stored.get("agent_card_params", {}).get("url") or ""))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise _not_found()
    target = f"{parts.scheme}://{parts.netloc}{prefix}{quote(rest, safe='/')}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return target, dict(stored.get("static_headers") or {})


@router.get("/agent-pages/{grant}/{rest:path}", include_in_schema=False)
async def agent_page(grant: str, rest: str, request: Request) -> Response:
    """One request of a proxied agent page (see the module docstring). The grant in the
    path is the credential; any failure of it is a plain ``404``."""
    target, headers = await _granted_target(request, grant, rest)
    if accept := request.headers.get("accept"):
        headers["accept"] = accept

    client = _make_client()
    try:
        upstream = await client.send(client.build_request("GET", target, headers=headers), stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("Agent page request failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY, detail="The agent page is unreachable."
        ) from exc

    async def _close() -> None:
        await upstream.aclose()
        await client.aclose()

    relayed = {k: v for k in _RELAY_RESPONSE_HEADERS if (v := upstream.headers.get(k))}
    if 300 <= upstream.status_code < 400:
        # A redirect would leave the grant path (or the agent's network): don't follow it.
        await _close()
        raise HTTPException(status_code=http_status.HTTP_502_BAD_GATEWAY, detail="The agent page redirected.")
    return StreamingResponse(
        _iter_bytes(upstream),
        status_code=upstream.status_code,
        headers={**relayed, **_PAGE_HEADERS},
        background=BackgroundTask(_close),
    )


async def _iter_bytes(upstream: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in upstream.aiter_bytes():
        yield chunk
