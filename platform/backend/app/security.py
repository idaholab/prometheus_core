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

"""Authentication: password identity provider, JWT cookie issue/verify, deps.

Ports ``auth_callback`` / ``oauth_callback`` from ``frontend/main.py``. Chainlit's
password auth becomes an explicit :class:`PasswordIdentityProvider`; its OAuth
pass-through becomes a modeled-but-unimplemented :class:`IdentityProvider` shape
(the callback route is reserved and stubs 501 until a real OAuth provider lands).

The session cookie is a signed JWT (``pyjwt``, ``settings.jwt_secret``). Its claims
carry the username (``sub``), ``role``, a per-login session id (``sid``), and an
``exp``. The ``sid`` is the key into the Valkey-backed :class:`~app.sessions.SessionStore`.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol, runtime_checkable

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import OidcProvider as OidcProviderRow
from app.db.models import User as UserRow
from app.passwords import verify_password
from app.redis_client import RedisClient, get_redis

# JWT signing algorithm. HS256 is symmetric — the same ``jwt_secret`` signs and
# verifies, which matches the single-service deployment here.
_JWT_ALG = "HS256"

logger = logging.getLogger(__name__)


class User(BaseModel):
    """Authenticated principal, mirroring Chainlit's ``cl.User`` shape.

    ``identifier`` matches what the React app read from ``/user``; ``role`` and
    ``provider`` mirror the ``cl.User.metadata`` keys set in ``auth_callback``.
    """

    identifier: str
    role: str = "user"
    provider: str = "credentials"


class TokenClaims(BaseModel):
    """Decoded JWT payload."""

    sub: str
    role: str
    sid: str
    provider: str = "credentials"
    exp: int


# --------------------------------------------------------------------------- #
# Identity provider interface
# --------------------------------------------------------------------------- #


@runtime_checkable
class IdentityProvider(Protocol):
    """Pluggable auth backend.

    ``authenticate`` handles credential-based login (password only -- OIDC
    providers return ``None`` unconditionally, they have no password path).
    ``callback`` completes a redirect-based OIDC handshake, given the inbound
    callback ``Request`` (query params ``code``/``state``, and the
    ``OIDC_FLOW_COOKIE`` set by the ``/login/{provider_id}`` redirect) --
    raises on any failure (:class:`~fastapi.HTTPException` for a request-level
    problem, ``NotImplementedError`` for a provider that has no redirect flow
    at all, e.g. the password provider) rather than returning ``None``, since
    a callback that reaches this far has committed to either resolving a user
    or failing loudly.
    """

    name: str

    async def authenticate(self, username: str, password: str, db: AsyncSession) -> Optional[User]:
        """Return a :class:`User` on valid credentials, else ``None``."""
        ...

    async def callback(self, request: Request, db: AsyncSession) -> User:
        """Complete a redirect-based (OIDC) handshake and return the resolved user."""
        ...


class PasswordIdentityProvider:
    """Local-users password check against the admin-plane ``users`` table.

    Previously compared against ``settings.local_users`` (plaintext, loaded once
    from ``config.yml`` at process start). Local accounts now live in Postgres
    (``app/db/models.py::User``, created via the first-run setup wizard or the
    admin API), hashed with bcrypt (:func:`app.passwords.verify_password`, itself
    timing-safe) — closing the AU-3 hashed-at-rest gap this used to defer.
    """

    name = "credentials"

    async def authenticate(self, username: str, password: str, db: AsyncSession) -> Optional[User]:
        row = await db.scalar(select(UserRow).where(UserRow.provider == self.name, UserRow.username == username))
        if row is None or not row.is_active or not row.password_hash:
            return None
        if not verify_password(password, row.password_hash):
            return None
        row.last_login_at = datetime.now(timezone.utc)
        await db.commit()
        return User(identifier=row.username, role=row.role, provider=self.name)

    async def callback(self, request: Request, db: AsyncSession) -> User:
        raise NotImplementedError("Password provider has no redirect callback")


# The active credential provider. Swap/extend when OAuth arrives.
password_provider = PasswordIdentityProvider()

# Provider registry (AU-6): a real seam rather than a hardcoded singleton. Login and
# the OAuth callback resolve providers through here, and a future OAuth provider is a
# drop-in via :func:`register_provider`. Only the password provider is wired today.
_PROVIDERS: dict[str, "IdentityProvider"] = {password_provider.name: password_provider}


def register_provider(provider: "IdentityProvider") -> None:
    """Register (or replace) an identity provider by its ``name``."""
    _PROVIDERS[provider.name] = provider


def unregister_provider(name: str) -> None:
    """Remove a registered provider by its ``name``. Idempotent."""
    _PROVIDERS.pop(name, None)


def get_provider(name: str) -> Optional["IdentityProvider"]:
    """Return the identity provider for ``name``, or ``None`` if unregistered."""
    return _PROVIDERS.get(name)


# --------------------------------------------------------------------------- #
# Generic OIDC provider (Phase 4) -- authorization-code flow
# --------------------------------------------------------------------------- #

#: Short-lived cookie carrying this one login attempt's state/nonce, signed
#: the same way as the session cookie (settings.jwt_secret) so it can't be
#: forged -- there is deliberately no server-side flow-state store (matches
#: the single-replica, in-memory-everything-else pattern used across the app).
OIDC_FLOW_COOKIE = "oidc_flow"
_OIDC_FLOW_TTL_SECONDS = 300


def _callback_url(request: Request, provider_id: str) -> str:
    """Must exactly match the ``redirect_uri`` sent at the start of the flow
    (login_redirect_url) and again during token exchange (oidc.exchange_code)
    -- OAuth requires it to be byte-identical on every leg, and it must match
    what's registered with the identity provider.

    ``settings.backend_public_url`` takes priority over ``request.base_url``
    when set -- the request's own base URL reflects whatever host a reverse
    proxy used to reach this container *internally* (e.g. a Vite dev server
    or nginx proxying ``/api``), never the browser-facing origin the identity
    provider redirects back to.
    """
    base = settings.backend_public_url or str(request.base_url).rstrip("/")
    return f"{base}/api/auth/callback/{provider_id}"


class GenericOidcProvider:
    """Full authorization-code OIDC flow against an admin-configured issuer
    (``app/db/models.py::OidcProvider`` -- this instance's ``name`` is that
    row's ``provider_id``).

    Config (issuer, client secret, scopes, ``is_enabled``, ``default_role``)
    is read fresh from the DB on every call, never cached on this instance --
    an admin edit (secret rotation, disabling, issuer change) takes effect on
    the very next request. Only provider_id existing/not-existing needs a
    registry update (see :func:`register_provider` / :func:`unregister_provider`,
    called from ``routers/admin_oidc.py``'s create/delete).
    """

    def __init__(self, provider_id: str) -> None:
        self.name = provider_id

    async def authenticate(self, username: str, password: str, db: AsyncSession) -> Optional[User]:
        return None  # OIDC providers have no password path

    async def _row(self, db: AsyncSession) -> OidcProviderRow:
        row = await db.scalar(select(OidcProviderRow).where(OidcProviderRow.provider_id == self.name))
        if row is None or not row.is_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Identity provider '{self.name}' is not configured"
            )
        return row

    async def login_redirect_url(self, request: Request, db: AsyncSession) -> tuple[str, str]:
        """Return ``(authorization_url, flow_cookie_value)`` -- the caller
        (``routers/auth.py``) sets the cookie and redirects the browser."""
        from app import oidc

        provider = await self._row(db)
        try:
            discovery = await oidc.fetch_discovery(provider.issuer_url)
            state = secrets.token_urlsafe(24)
            nonce = secrets.token_urlsafe(24)
            redirect_uri = _callback_url(request, self.name)
            auth_url = oidc.build_authorization_url(
                discovery, provider, redirect_uri=redirect_uri, state=state, nonce=nonce
            )
        except oidc.OidcError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        now = datetime.now(timezone.utc)
        flow_claims = {
            "provider_id": self.name,
            "state": state,
            "nonce": nonce,
            "iat": now,
            "exp": now + timedelta(seconds=_OIDC_FLOW_TTL_SECONDS),
        }
        flow_cookie = jwt.encode(flow_claims, settings.jwt_secret, algorithm=_JWT_ALG)
        return auth_url, flow_cookie

    async def callback(self, request: Request, db: AsyncSession) -> User:
        from app import oidc

        provider = await self._row(db)

        error = request.query_params.get("error")
        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Identity provider returned an error: {error}"
            )

        flow_cookie = request.cookies.get(OIDC_FLOW_COOKIE)
        if not flow_cookie:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Login flow expired or was not started through this backend",
            )
        try:
            flow = jwt.decode(flow_cookie, settings.jwt_secret, algorithms=[_JWT_ALG])
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Login flow expired or is invalid"
            ) from exc
        if flow.get("provider_id") != self.name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Login flow provider mismatch")

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state or state != flow.get("state"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or missing state/code")

        redirect_uri = _callback_url(request, self.name)
        try:
            discovery = await oidc.fetch_discovery(provider.issuer_url)
            tokens = await oidc.exchange_code(discovery, provider, code=code, redirect_uri=redirect_uri)
            id_token = tokens.get("id_token")
            if not id_token:
                raise oidc.OidcError("Identity provider did not return an id_token")
            claims = oidc.verify_id_token(discovery, provider, id_token, expected_nonce=flow.get("nonce", ""))
            external_subject = claims.get("sub")
            if not external_subject:
                raise oidc.OidcError("id_token is missing a 'sub' claim")
            row = await oidc.upsert_user(db, provider, external_subject, claims)
        except oidc.OidcError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        return User(identifier=row.username, role=row.role, provider=row.provider)


async def register_existing_oidc_providers(db: AsyncSession) -> None:
    """Register every already-configured ``OidcProvider`` row so
    :func:`get_provider` resolves them from the very first request.

    Called once at startup (``app/main.py``'s lifespan, after migrations).
    ``routers/admin_oidc.py`` keeps the registry in sync afterward for
    create/delete; an update needs no registry change since
    :class:`GenericOidcProvider` re-reads its row fresh on every call.
    """
    rows = (await db.scalars(select(OidcProviderRow))).all()
    for row in rows:
        register_provider(GenericOidcProvider(row.provider_id))


# --------------------------------------------------------------------------- #
# Session revocation (AU-1) — logout invalidates the JWT before its natural expiry
# --------------------------------------------------------------------------- #

# Valkey ``revoked:sid:{sid}`` markers. On logout the session's sid is revoked so a
# retained cookie stops passing ``current_claims`` before ``exp`` (the JWT itself is
# stateless). The key's TTL is the token's remaining lifetime, which replaces the
# manual prune loop this used to need: once the JWT would have expired anyway, the
# marker is gone and there is nothing to grow.
#
# Previously a process-local dict, which meant a logged-out session came back to life
# on every restart and was never revoked in the other workers at all.
_REVOKED_PREFIX = "revoked:sid:"


def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


async def revoke_session(redis: RedisClient, sid: str, exp: int) -> None:
    """Revoke a session id until ``exp`` (its token's expiry).

    A token already past ``exp`` needs no marker -- ``verify_token`` rejects it on its
    own -- and Redis rejects a non-positive TTL, so that case is a no-op.
    """
    ttl = exp - _now_epoch()
    if ttl <= 0:
        return
    await redis.set(f"{_REVOKED_PREFIX}{sid}", "1", ex=ttl)


async def is_revoked(redis: RedisClient, sid: str) -> bool:
    """Whether ``sid`` was logged out. **Fails open.**

    A Valkey outage returns ``False`` (not revoked) rather than 401-ing every request:
    failing closed would lock out every logged-in user whenever Valkey blips, while
    failing open leaves a logged-out session usable until its token expires -- exactly
    what the old in-process dict did after any restart, so not a regression.
    """
    try:
        return bool(await redis.exists(f"{_REVOKED_PREFIX}{sid}"))
    except Exception as exc:  # noqa: BLE001 - availability beats revocation here
        logger.warning("revocation check failed for sid=%s (%s); treating as not revoked", sid, exc)
        return False


# --------------------------------------------------------------------------- #
# JWT issue / verify
# --------------------------------------------------------------------------- #


def issue_token(user: User, sid: Optional[str] = None) -> str:
    """Sign a JWT for ``user``. Mints a fresh ``sid`` unless one is supplied."""
    if not settings.jwt_secret:
        # Fail loud rather than sign with an empty key (which would make forgery trivial).
        raise RuntimeError("jwt_secret is not configured (set BACKEND_JWT_SECRET)")
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user.identifier,
        "role": user.role,
        "provider": user.provider,
        "sid": sid or str(uuid.uuid4()),
        "exp": now + timedelta(seconds=settings.token_ttl_seconds),
        "iat": now,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_JWT_ALG)


def verify_token(token: str) -> TokenClaims:
    """Decode and validate a JWT. Raises ``jwt.InvalidTokenError`` on any failure."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALG])
    return TokenClaims(**payload)


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the signed session JWT as an httpOnly cookie.

    Shared by every route that logs a user in (``routers/auth.py``'s ``/login``,
    ``routers/setup.py``'s ``/bootstrap``). ``secure`` comes from
    ``settings.cookie_secure``, which tracks the *browser-facing* scheme
    (``BACKEND_PUBLIC_URL``) rather than ``debug`` -- see ``config._cookie_secure``
    for why that distinction matters to Safari. ``max_age`` matches the token TTL so
    the browser drops the cookie in step with JWT expiry.
    """
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.token_ttl_seconds,
        path="/",
    )


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #


async def current_claims(
    request: Request,
    session_cookie: Optional[str] = Cookie(
        default=None,
        alias=settings.cookie_name,
        description="The session token that login sets. Browsers send it automatically.",
    ),
) -> TokenClaims:
    """Dependency: verify the session cookie and return its claims, or 401.

    ``alias`` binds this to the configured cookie name; the parameter name itself
    is arbitrary. ``async`` because the revocation check is a Valkey round trip now --
    FastAPI resolves async dependencies natively, so every ``Depends(current_claims)``
    site is unchanged.
    """
    if not session_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        claims = verify_token(session_cookie)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session") from exc
    # AU-1: logged-out sessions are rejected before exp.
    if await is_revoked(get_redis(request), claims.sid):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been logged out")
    return claims


def current_user(claims: TokenClaims = Depends(current_claims)) -> User:
    """Dependency: the authenticated :class:`User` derived from the cookie."""
    return User(identifier=claims.sub, role=claims.role, provider=claims.provider)


def require_admin(user: User = Depends(current_user)) -> User:
    """Dependency: like :func:`current_user`, but 403s unless ``role == "admin"``.

    Guards the admin API (``routers/admin_users.py`` and friends). The role comes
    from the session JWT, minted at login from the ``users`` table -- a role change
    via the admin API takes effect on that user's *next* login, not retroactively on
    an already-issued token (same staleness window as the JWT's other claims).
    """
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
