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

"""Per-request user identity: minting, verification, and request-scoped propagation.

The platform mints its own short-lived internal JWT after a user logs in, independent
of how authentication happened (Okta, generic OIDC, local password).  This token is what
propagates to agents — never the external IdP token — so the trust model works even when
the deployment has no federated IdP.

Signing is **RS256 only** (asymmetric).  The minting side (the platform backend) holds
``USER_IDENTITY_PRIVATE_KEY``; every verifying side (every agent, including third-party
ones) holds only ``USER_IDENTITY_PUBLIC_KEY`` or a ``JWKS_URL`` — nothing that can forge
a token ever needs to leave the backend.  There is deliberately no symmetric (HS256)
option: a shared secret would let any agent holding it impersonate any user.  Generate a
keypair with :mod:`prometheus_api.agent.identity_keygen` (``prometheus-identity-keygen``
console script) or plain ``openssl``; see ``docs/agent/IDENTITY_KEY_MANAGEMENT.md``.

Usage
-----
Backend (mint on each turn)::

    from prometheus_api.agent.identity import mint_user_token
    token = mint_user_token(user_id="alice")

Base class (verify and scope)::

    from prometheus_api.agent.identity import (
        identity_scope, verify_user_token, get_current_identity, current_user_id,
        USER_TOKEN_METADATA_KEY,
    )
    identity = verify_user_token(raw_token)
    with identity_scope(identity):
        params["user_id"] = current_user_id()
        await agent._execute(params, context, event_queue)

Downstream agent helpers::

    from prometheus_api.agent.identity import get_current_identity, USER_TOKEN_METADATA_KEY
    raw = get_current_identity().raw_token
    message_metadata = {USER_TOKEN_METADATA_KEY: raw}   # merge into outbound A2A
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterator, Optional

import hashlib
import json

import jwt
from jwt import PyJWKClient

if TYPE_CHECKING:
    from jwt.types import Options

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


#: Key used to carry the user token inside A2A message.metadata.
#: The base class reads this key; outbound propagation should use the same key.
USER_TOKEN_METADATA_KEY = "userToken"

#: The only supported signing algorithm.  RS256 only — see module docstring.
ALG = "RS256"

# Defaults — can all be overridden via env vars.
_DEFAULT_ISS = "prometheus-platform"
_DEFAULT_AUD = "prometheus-agents"
_DEFAULT_TTL = 7200  # generous default; background turns can be long


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserIdentity:
    """Verified identity extracted from a platform-minted JWT.

    All fields come from *verified* claims — never from raw, unvalidated input.
    """

    user_id: str
    """The canonical user identifier (JWT ``sub`` claim)."""

    claims: dict[str, Any]
    """All decoded claims from the verified token (read-only copy)."""

    raw_token: str
    """The original token string, for forwarding to downstream A2A hops."""


class IdentityError(Exception):
    """Raised when a token cannot be verified or is missing required claims."""


# ---------------------------------------------------------------------------
# Mint
# ---------------------------------------------------------------------------


def mint_user_token(
    user_id: str,
    *,
    extra_claims: Optional[dict[str, Any]] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Mint a short-lived platform JWT for *user_id*, signed RS256.

    Requires ``USER_IDENTITY_PRIVATE_KEY`` (PEM, with or without passphrase).
    Only the minting side (the platform backend) needs this — agents verify
    with the public key or a JWKS URL and can never sign a token themselves.

    Args:
        user_id: The canonical identifier for the authenticated user.
        extra_claims: Additional claims to embed (will not override ``sub``/``iat``/``exp``/``iss``/``aud``).
        ttl_seconds: Token lifetime; defaults to ``USER_IDENTITY_TTL`` env var
            (seconds, default 7200).

    Returns:
        A signed JWT string.
    """
    iss = _env("USER_IDENTITY_ISS", _DEFAULT_ISS)
    aud = _env("USER_IDENTITY_AUD", _DEFAULT_AUD)
    ttl = ttl_seconds if ttl_seconds is not None else _int_env("USER_IDENTITY_TTL", _DEFAULT_TTL)

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "iss": iss,
        "aud": aud,
    }
    if extra_claims:
        for k, v in extra_claims.items():
            if k not in ("sub", "iat", "exp", "iss", "aud"):
                payload[k] = v

    key = _get_signing_key()
    # Include kid so verifiers (especially PyJWKClient) can select the
    # correct key from the JWKS when multiple keys are present (rotation).
    headers: dict[str, Any] = {}
    jwks = get_jwks_document()
    if jwks["keys"]:
        headers["kid"] = jwks["keys"][0]["kid"]
    return jwt.encode(payload, key, algorithm=ALG, headers=headers or None)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify_user_token(token: str) -> UserIdentity:
    """Verify a platform JWT (RS256) and return the extracted identity.

    Checks signature, expiry, issuer, and audience.

    Key resolution priority:
    1. ``JWKS_URL`` — fetch the JWKS from this URL and select the key by ``kid``
       (for third-party agents that don't have the key locally; uses
       :class:`~jwt.PyJWKClient` with automatic caching and refresh).
    2. ``USER_IDENTITY_PUBLIC_KEY`` (or ``USER_IDENTITY_PRIVATE_KEY`` as a
       single-host fallback) — local env-var key.

    Raises:
        IdentityError: If the token is invalid, expired, or has wrong iss/aud.
    """
    if not token or not isinstance(token, str):
        raise IdentityError("userToken is missing or not a string")

    iss = _env("USER_IDENTITY_ISS", _DEFAULT_ISS)
    aud = _env("USER_IDENTITY_AUD", _DEFAULT_AUD)

    decode_options: Options = {"require": ["sub", "exp", "iat", "iss", "aud"]}

    try:
        jwks_url = _env("JWKS_URL")
        if jwks_url:
            key = _get_jwks_signing_key(jwks_url, token)
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALG],
                issuer=iss,
                audience=aud,
                options=decode_options,
            )
        else:
            key = _get_verification_key()
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALG],
                issuer=iss,
                audience=aud,
                options=decode_options,
            )
    except IdentityError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise IdentityError("userToken has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise IdentityError("userToken audience mismatch") from exc
    except jwt.InvalidIssuerError as exc:
        raise IdentityError("userToken issuer mismatch") from exc
    except jwt.InvalidSignatureError as exc:
        raise IdentityError("userToken signature verification failed") from exc
    except jwt.DecodeError as exc:
        raise IdentityError(f"userToken could not be decoded: {exc}") from exc
    except jwt.PyJWTError as exc:
        raise IdentityError(f"userToken invalid: {exc}") from exc

    user_id = claims.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise IdentityError("userToken missing or invalid 'sub' claim")

    return UserIdentity(user_id=user_id, claims=dict(claims), raw_token=token)


# ---------------------------------------------------------------------------
# JWKS remote key fetching (for JWKS_URL verification path)
# ---------------------------------------------------------------------------

# Module-level cache: url → PyJWKClient (the client caches keys internally)
_jwks_clients: dict[str, "PyJWKClient"] = {}


def _get_jwks_signing_key(jwks_url: str, token: str) -> Any:
    """Fetch the signing key for *token* from the JWKS at *jwks_url*.

    Uses :class:`~jwt.PyJWKClient` which caches the JWKS keyset and refreshes
    it when a ``kid`` is not found (supports zero-downtime key rotation).

    Raises:
        IdentityError: On network failure or missing key.
    """
    if jwks_url not in _jwks_clients:
        _jwks_clients[jwks_url] = PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=3600,  # refresh JWKS at most once per hour
        )
    client = _jwks_clients[jwks_url]
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        return signing_key.key
    except jwt.PyJWKClientConnectionError as exc:
        raise IdentityError(f"Could not fetch JWKS from {jwks_url!r}: {exc}") from exc
    except jwt.exceptions.PyJWKSetError as exc:
        raise IdentityError(f"No matching key found in JWKS at {jwks_url!r}: {exc}") from exc
    except jwt.PyJWTError as exc:
        raise IdentityError(f"JWKS key lookup failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Request-scoped identity (ContextVar — safe across concurrent async requests)
# ---------------------------------------------------------------------------

_current_identity: ContextVar[Optional[UserIdentity]] = ContextVar("current_identity", default=None)


@contextmanager
def identity_scope(identity: Optional[UserIdentity]) -> Iterator[None]:
    """Bind *identity* as the current user for the duration of this context.

    Uses a ``ContextVar`` so concurrent async tasks never share identity
    state.

    Example::

        identity = verify_user_token(raw_token)
        with identity_scope(identity):
            result = await agent._execute(params, context, event_queue)
    """
    token = _current_identity.set(identity)
    try:
        yield
    finally:
        _current_identity.reset(token)


def get_current_identity() -> Optional[UserIdentity]:
    """Return the verified identity for the current async task, or ``None``.

    Returns ``None`` when called outside an :func:`identity_scope` context
    (e.g. during startup or in background tasks that carry no user identity).
    """
    return _current_identity.get()


def current_user_id() -> Optional[str]:
    """Convenience accessor; returns ``identity.user_id`` or ``None``."""
    identity = _current_identity.get()
    return identity.user_id if identity is not None else None


# ---------------------------------------------------------------------------
# Internal key helpers
# ---------------------------------------------------------------------------


def get_jwks_document() -> dict:
    """Return the platform's public key(s) as a JSON Web Key Set (RFC 7517).

    This is what the ``/.well-known/jwks.json`` endpoint serves.  Third-party
    agents and remote verifiers fetch this document to obtain the current
    public key without any private material being shared.

    Returns the RSA public key as a JWK with ``use=sig``, ``alg=RS256``, and a
    stable ``kid`` (SHA-256 thumbprint of the modulus).  If only
    ``USER_IDENTITY_PRIVATE_KEY`` is set the public key is derived from it
    automatically.  Returns an empty keyset when neither key is configured.

    Returns:
        A dict conforming to RFC 7517, e.g.
        ``{"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", ...}]}``.
    """
    pub_pem = _env("USER_IDENTITY_PUBLIC_KEY")
    if not pub_pem:
        priv_pem = _env("USER_IDENTITY_PRIVATE_KEY")
        if not priv_pem:
            return {"keys": []}
        try:
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
                load_pem_private_key,
            )

            private_key = load_pem_private_key(priv_pem.encode(), password=None)
            pub_pem = (
                private_key.public_key()
                .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
                .decode()
            )
        except Exception:
            return {"keys": []}

    try:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from jwt.algorithms import RSAAlgorithm

        public_key = load_pem_public_key(pub_pem.encode())
        if not isinstance(public_key, RSAPublicKey):
            # Only RS256 is supported, so a non-RSA key can't be published
            return {"keys": []}
        jwk_str = RSAAlgorithm.to_jwk(public_key)
        key_dict = json.loads(jwk_str)
        key_dict["use"] = "sig"
        key_dict["alg"] = ALG
        key_dict["kid"] = _compute_kid(key_dict)
        return {"keys": [key_dict]}
    except Exception:
        return {"keys": []}


def _compute_kid(jwk_dict: dict) -> str:
    """Compute a stable key ID from the JWK modulus (RFC 7638 thumbprint).

    Uses the RSA ``n`` parameter (base64url-encoded modulus) hashed with
    SHA-256.  Stable across restarts; changes only when the key is rotated.
    """
    n = jwk_dict.get("n", "")
    return hashlib.sha256(n.encode()).hexdigest()[:16]


def _get_signing_key() -> Any:
    """Return the RS256 private signing key.  Raises ``IdentityError`` if unconfigured."""
    key_pem = _env("USER_IDENTITY_PRIVATE_KEY")
    if not key_pem:
        raise IdentityError(
            "USER_IDENTITY_PRIVATE_KEY (PEM) is required to mint identity tokens. "
            "Generate a keypair with prometheus_api.agent.identity_keygen "
            "(prometheus-identity-keygen) or openssl."
        )
    return key_pem


def _get_verification_key() -> Any:
    """Return the RS256 public verification key.  Raises ``IdentityError`` if unconfigured.

    PyJWT's RS256 verifier requires an actual public key (it has no ``.verify()``
    method on a private key object), so when only ``USER_IDENTITY_PRIVATE_KEY`` is
    set (single-host deployments where the same process mints and verifies, e.g.
    local dev), the public key is derived from it rather than passed through.
    """
    pub = _env("USER_IDENTITY_PUBLIC_KEY")
    if pub:
        return pub
    priv = _env("USER_IDENTITY_PRIVATE_KEY")
    if priv:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            load_pem_private_key,
        )

        private_key = load_pem_private_key(priv.encode(), password=None)
        return (
            private_key.public_key()
            .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
    raise IdentityError(
        "USER_IDENTITY_PUBLIC_KEY (or USER_IDENTITY_PRIVATE_KEY, or JWKS_URL) is "
        "required to verify identity tokens. Generate a keypair with "
        "prometheus_api.agent.identity_keygen (prometheus-identity-keygen) or openssl."
    )
