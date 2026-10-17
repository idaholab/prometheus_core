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

"""Mint short-lived platform JWTs for the authenticated user (identity plane).

The backend mints its own internal JWT after login — never forwards the
session cookie or any external IdP token — so agents can verify *who* is
calling them independent of how the user logged in (local password or a
future OIDC provider).

Signing is RS256 only. Key source, in priority order:

1. **admin-db's active** ``SigningKey`` row (``app/signing_keys.py``) — the
   backend creates and activates one key at first start
   (``ensure_active_signing_key()``) unless ``USER_IDENTITY_PRIVATE_KEY`` is
   set; admins rotate it through the admin API. Cached in-process for ``_CACHE_TTL_SECONDS`` to avoid a DB
   round-trip on every turn; ``app/routers/admin_keys.py`` invalidates the
   cache immediately after activate/retire so rotation doesn't wait it out.
2. **``USER_IDENTITY_PRIVATE_KEY`` env var** — the static-key alternative, for
   a deploy that manages its own key outside admin-db. While it is set, the
   backend creates no key at startup.

Either way, every agent verifies with ``USER_IDENTITY_PUBLIC_KEY`` or a
``JWKS_URL`` pointed at this backend's own ``GET /.well-known/jwks.json``
(``app/routers/jwks.py``) — never the private key.

Verification-side lives in ``prometheus_api.agent.identity``; see
``docs/dev-docs/multi-user-setup.md`` for the full picture (identity plane,
credential plane, per-user worker isolation).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """Return True when the env-var fallback has enough config to mint a token."""
    return bool(os.environ.get("USER_IDENTITY_PRIVATE_KEY"))


async def _load_active_key_from_db() -> Optional[tuple[str, str]]:
    """Return ``(kid, private_key_pem)`` for admin-db's active signing key, or
    ``None`` if there isn't one. Opens its own short-lived session -- callers
    (routers) don't carry a DB session through every request just for this."""
    from sqlalchemy import select

    from app.crypto import decrypt
    from app.db import get_session_factory
    from app.db.models import SigningKey

    session_factory = get_session_factory()
    async with session_factory() as db:
        row = await db.scalar(select(SigningKey).where(SigningKey.is_active.is_(True)))
        if row is None:
            return None
        return row.kid, decrypt(row.private_key_encrypted)


async def _active_signing_key() -> Optional[tuple[str, str]]:
    from app.signing_keys import cached_active_key, set_cached_active_key

    is_fresh, cached = cached_active_key()
    if is_fresh:
        return cached
    loaded = await _load_active_key_from_db()
    set_cached_active_key(loaded)
    return loaded


def _mint_with_key(user_id: str, private_key_pem: str, kid: str) -> str:
    """Mint a JWT with the same claim shape as ``prometheus_api.agent.identity.
    mint_user_token()`` (same env-configured iss/aud/ttl), just signed with a
    DB-sourced key instead of the env-var one -- so the unchanged verifier on
    every agent doesn't need to know which source minted a given token."""
    import jwt

    iss = os.environ.get("USER_IDENTITY_ISS", "prometheus-platform")
    aud = os.environ.get("USER_IDENTITY_AUD", "prometheus-agents")
    ttl = int(os.environ.get("USER_IDENTITY_TTL", "7200"))
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "iss": iss,
        "aud": aud,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers={"kid": kid})


async def mint_for_user(user_id: str) -> Optional[str]:
    """Mint a short-lived platform JWT for *user_id*, or ``None`` if unavailable.

    Returns ``None`` (rather than raising) both when identity isn't configured
    and when minting fails for any reason — mirrors ``USER_IDENTITY_REQUIRED=false``
    dev/CI mode on the agent side: the backend simply omits ``userToken`` and
    agents fall back to a synthetic ``"local"`` identity.
    """
    if not user_id:
        return None

    try:
        key = await _active_signing_key()
    except Exception as exc:
        logger.warning("Failed to load active signing key from admin-db: %s", exc)
        key = None

    if key is not None:
        kid, private_key_pem = key
        try:
            return _mint_with_key(user_id, private_key_pem, kid)
        except Exception as exc:
            logger.warning("Failed to mint user token for %r with DB key %r: %s", user_id, kid, exc)
            return None

    if not _is_configured():
        return None
    try:
        from prometheus_api.agent.identity import mint_user_token

        ttl = int(os.environ.get("USER_IDENTITY_TTL", "7200"))
        return mint_user_token(user_id, ttl_seconds=ttl)
    except Exception as exc:
        logger.warning("Failed to mint user token for %r: %s", user_id, exc)
        return None
