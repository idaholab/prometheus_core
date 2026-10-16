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

"""Authentication endpoints — login, logout, me, and the OIDC redirect flow.

Replaces Chainlit's built-in auth surface. Login issues a JWT session cookie
(httpOnly, SameSite=Lax, Secure outside debug); ``/api/auth/me`` replaces the
React app's ``fetch("/user")`` probe. ``/login/{provider_id}`` and
``/callback/{provider}`` are the two legs of the OIDC authorization-code flow
(see :mod:`app.security`'s ``GenericOidcProvider`` for the actual exchange).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_responses import AUTH_RESPONSES, ENCRYPTION_RESPONSES
from app.config import settings
from app.db import get_db_session
from app.db.models import OidcProvider
from app.security import (
    OIDC_FLOW_COOKIE,
    User,
    current_user,
    get_provider,
    issue_token,
    revoke_session,
    set_session_cookie,
    verify_token,
)
from app.redis_client import get_redis
from app.sessions import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginResult(BaseModel):
    user: User


class ProviderInfo(BaseModel):
    provider_id: str
    display_name: str


async def _read_credentials(request: Request) -> tuple[Optional[str], Optional[str]]:
    """Extract ``(username, password)`` from a JSON or form-encoded request body.

    FastAPI can't declare both ``Body`` and ``Form`` params on one endpoint (the
    presence of ``Form`` forces multipart/form decoding), so dispatch on the
    Content-Type ourselves to accept either shape.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            data = await request.json()
        except Exception:
            return None, None
        if not isinstance(data, dict):
            return None, None
        return data.get("username"), data.get("password")
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    return (
        username if isinstance(username, str) else None,
        password if isinstance(password, str) else None,
    )


@router.post("/login", response_model=LoginResult)
async def login(request: Request, response: Response, db: AsyncSession = Depends(get_db_session)) -> LoginResult:
    """Accept form-encoded or JSON ``{username, password}`` and set the cookie."""
    username, password = await _read_credentials(request)
    if not username or not password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="username and password required")

    provider = get_provider("credentials")
    user = await provider.authenticate(username, password, db) if provider else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = issue_token(user)
    # Assert the freshly minted session id resolves before handing out the cookie.
    # Nothing is written: an untouched session is just the defaults (see app/sessions.py),
    # and this is also the first place a Valkey outage surfaces as a failed login rather
    # than as a cookie that works until the first chat turn.
    await get_store(request).get_or_create(verify_token(token).sid)
    set_session_cookie(response, token)
    return LoginResult(user=user)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    """Clear the session cookie and forget any server-side session state."""
    cookie = request.cookies.get(settings.cookie_name)
    claims = None
    if cookie:
        try:
            claims = verify_token(cookie)
        except Exception:
            # A bad/expired cookie has nothing to clean up; still clear it below.
            claims = None
    if claims is not None:
        try:
            await get_store(request).drop(claims.sid)
            # AU-1: revoke the sid so the (still-unexpired) JWT can't be replayed. In
            # Valkey now, so the revocation is seen by every worker and survives a restart.
            await revoke_session(get_redis(request), claims.sid, claims.exp)
        except Exception as exc:  # noqa: BLE001
            # Kept separate from the cookie parse above so a Valkey outage is *logged*
            # rather than silently indistinguishable from a junk cookie: the cookie is
            # still cleared (the browser forgets the session either way), but the JWT
            # stays replayable until ``exp``, which an operator should know about.
            logger.warning("logout: could not revoke sid=%s: %s", claims.sid, exc)
    response.delete_cookie(key=settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=User, responses=AUTH_RESPONSES)
async def me(user: User = Depends(current_user)) -> User:
    """Return the authenticated user, or 401. Replaces the React ``/user`` probe."""
    return user


@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers(db: AsyncSession = Depends(get_db_session)) -> list[ProviderInfo]:
    """Public: enabled OIDC providers, for <Login> to render a button per entry."""
    rows = (
        await db.scalars(
            select(OidcProvider).where(OidcProvider.is_enabled.is_(True)).order_by(OidcProvider.display_name)
        )
    ).all()
    return [ProviderInfo(provider_id=row.provider_id, display_name=row.display_name) for row in rows]


@router.get("/login/{provider_id}")
async def login_via_provider(
    provider_id: str, request: Request, db: AsyncSession = Depends(get_db_session)
) -> Response:
    """Start the OIDC authorization-code flow: redirect the browser to the
    identity provider, with the state/nonce cookie ``callback`` reads back."""
    provider = get_provider(provider_id)
    login_redirect_url = getattr(provider, "login_redirect_url", None)
    if login_redirect_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Identity provider '{provider_id}' not found"
        )

    auth_url, flow_cookie_value = await login_redirect_url(request, db)

    redirect = RedirectResponse(url=auth_url)
    redirect.set_cookie(
        key=OIDC_FLOW_COOKIE,
        value=flow_cookie_value,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=300,
        path="/api/auth",
    )
    return redirect


@router.get("/callback/{provider}", responses=ENCRYPTION_RESPONSES)
async def oauth_callback(provider: str, request: Request, db: AsyncSession = Depends(get_db_session)) -> Response:
    """OIDC redirect callback — resolved through the provider registry (AU-6).

    A registered provider completes the handshake via ``IdentityProvider.callback``,
    which raises on any failure (``HTTPException`` for a request-level problem,
    ``NotImplementedError`` for a provider with no redirect flow at all).
    """
    impl = get_provider(provider)
    if impl is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"OAuth provider '{provider}' is not configured",
        )
    try:
        user = await impl.callback(request, db)
    except NotImplementedError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"OAuth provider '{provider}' is not configured",
        ) from None

    token = issue_token(user)
    await get_store(request).get_or_create(verify_token(token).sid)
    # Land back in the SPA root; App.tsx's boot sequence sees the fresh
    # session cookie on its next /api/auth/me probe and renders <ProjectView>.
    redirect = RedirectResponse(url="/")
    set_session_cookie(redirect, token)
    redirect.delete_cookie(key=OIDC_FLOW_COOKIE, path="/api/auth")
    return redirect
