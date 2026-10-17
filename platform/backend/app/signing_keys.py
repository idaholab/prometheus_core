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

"""Shared helpers for the admin-plane RS256 signing keys (app/db/models.py::SigningKey).

Used by:
- app/routers/admin_keys.py -- generate/activate/retire admin actions
- app/routers/jwks.py -- the public JWKS document
- app/identity.py -- DB-first active-key lookup for minting, with a short cache
- app/main.py -- ensure_active_signing_key() at startup, for a fresh install
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional, cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import EncryptionError, encrypt, ensure_configured
from app.db.models import SigningKey

logger = logging.getLogger(__name__)

# Arbitrary but fixed key for pg_advisory_xact_lock: serializes the startup
# check-then-insert in ensure_active_signing_key() across every `--workers N`
# process. Distinct from routers/setup.py's _BOOTSTRAP_LOCK_KEY.
_SIGNING_KEY_BOOTSTRAP_LOCK_KEY = 0x50524F4D_00000002


def _jwk_dict(public_key_pem: str) -> dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from jwt.algorithms import RSAAlgorithm

    public_key = load_pem_public_key(public_key_pem.encode())
    if not isinstance(public_key, RSAPublicKey):
        # Every key this module ever writes comes from generate_signing_key()
        # (always RSA) -- a non-RSA PEM here means a row was hand-edited or
        # corrupted, not a case to silently coerce.
        raise ValueError(f"Expected an RSA public key, got {type(public_key).__name__}")
    return cast(dict[str, Any], json.loads(RSAAlgorithm.to_jwk(public_key)))


def compute_kid(public_key_pem: str) -> str:
    """SHA-256 thumbprint of the JWK modulus, truncated to 16 hex chars.

    Matches ``prometheus_api.agent.identity._compute_kid()``'s algorithm exactly,
    so a kid computed here lines up with one computed there if this same key is
    ever also placed in ``USER_IDENTITY_PUBLIC_KEY`` for a bootstrap/fallback
    deployment -- not required for correctness (the DB is the source of truth
    for its own keys), just for a kid to mean the same thing everywhere.
    """
    jwk = _jwk_dict(public_key_pem)
    return hashlib.sha256(jwk["n"].encode()).hexdigest()[:16]


def jwk_for(key: SigningKey) -> dict[str, Any]:
    """This key's public half as an RFC 7517 JWK entry."""
    jwk = _jwk_dict(key.public_key_pem)
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    jwk["kid"] = key.kid
    return jwk


def generate_signing_key() -> tuple[str, str, str]:
    """Return ``(kid, private_key_pem, public_key_pem)`` for a fresh RS256 keypair.

    ``prometheus_api.agent.identity_keygen.generate_keypair()`` ships in the
    base image the backend already depends on.
    """
    from prometheus_api.agent.identity_keygen import generate_keypair

    private_pem, public_pem = generate_keypair()
    return compute_kid(public_pem), private_pem, public_pem


def new_signing_key_row(*, is_active: bool) -> SigningKey:
    """A fresh RS256 ``SigningKey`` row with its private key encrypted, not yet added to a session.

    Raises:
        EncryptionError: if ADMIN_DB_ENCRYPTION_KEY is missing or invalid --
            checked before the keypair is generated, so a misconfigured
            install skips the keygen.
    """
    ensure_configured()
    kid, private_pem, public_pem = generate_signing_key()
    return SigningKey(
        kid=kid,
        private_key_encrypted=encrypt(private_pem),
        public_key_pem=public_pem,
        is_active=is_active,
    )


async def ensure_active_signing_key(db: AsyncSession) -> Optional[str]:
    """Create and activate one RS256 key when admin-db has no active key.

    Returns the new kid, or None when it did nothing. Never raises on a
    missing or invalid ADMIN_DB_ENCRYPTION_KEY: it logs a warning, creates
    no key, and the backend boots without a DB key.

    Runs once per worker from the lifespan in app/main.py. The advisory lock
    makes the workers' check-then-insert one at a time, so one install gets one
    key. SQLite (tests only) has no advisory locks and skips it, as
    routers/setup.py does. Inactive and retired rows are left untouched.
    """
    from app.identity import _is_configured  # function-local: app.identity imports this module

    if _is_configured():
        logger.info("static identity key configured; not creating a default signing key")
        return None

    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SIGNING_KEY_BOOTSTRAP_LOCK_KEY})

    active = await db.scalar(select(SigningKey.id).where(SigningKey.is_active.is_(True)).limit(1))
    if active is not None:
        # Ends the transaction, which releases the advisory lock.
        await db.rollback()
        return None

    try:
        row = new_signing_key_row(is_active=True)
    except EncryptionError as exc:
        logger.warning("not creating a default signing key: ADMIN_DB_ENCRYPTION_KEY unusable (%s)", exc)
        await db.rollback()
        return None

    db.add(row)
    await db.commit()
    invalidate_active_key_cache()
    logger.info("created default signing key %s", row.kid)
    return row.kid


# --------------------------------------------------------------------------- #
# Active-key cache for minting (app/identity.py) -- avoids a DB round-trip on
# every mint_for_user() call. Invalidated explicitly by admin_keys.py right
# after activate/retire so a rotation takes effect immediately rather than
# waiting out the TTL below.
# --------------------------------------------------------------------------- #

_CACHE_TTL_SECONDS = 60

_cache_value: Optional[tuple[str, str]] = None  # (kid, private_key_pem)
_cache_fresh_until = 0.0  # time.monotonic() deadline; 0 means "never populated"


def cached_active_key() -> tuple[bool, Optional[tuple[str, str]]]:
    """Return ``(is_fresh, value)``. Check ``is_fresh`` before trusting ``value`` --
    a fresh ``None`` means "confirmed no active key", a stale one means "unknown, go
    reload"."""
    return time.monotonic() < _cache_fresh_until, _cache_value


def set_cached_active_key(value: Optional[tuple[str, str]]) -> None:
    global _cache_value, _cache_fresh_until
    _cache_value = value
    _cache_fresh_until = time.monotonic() + _CACHE_TTL_SECONDS


def invalidate_active_key_cache() -> None:
    global _cache_fresh_until
    _cache_fresh_until = 0.0
