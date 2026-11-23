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

"""Unit tests for app.identity -- the backend's identity-minting helper (RS256-only).

Covers the backend-side wrapper: env-var fallback (configured/unconfigured, mint
failure degrades to None rather than raising) and the DB-first active-key path
added in Phase 3 (app/signing_keys.py's cache, app/routers/admin_keys.py's
generate/activate flow). Full mint/verify round-trip coverage against
prometheus_api's own verifier lives in prometheus_api's own test_identity.py --
the round-trip test below exists specifically to prove a DB-signed token is
indistinguishable, from an agent's point of view, from an env-signed one.

The autouse ``no_real_signing_key_db_lookup`` fixture (conftest.py) stubs
``app.identity._load_active_key_from_db`` to "no active key" for every test in
this file too, unless a test overrides it itself below.
"""

from __future__ import annotations

import pytest

from app import identity, signing_keys

# Captured at import, before the autouse conftest stub replaces it for each test.
_real_load_public_key_from_db = identity._load_public_key_from_db


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    """One RSA keypair (PEM, PEM) shared across tests in this module."""
    from prometheus_api.agent.identity_keygen import generate_keypair

    return generate_keypair(key_size=2048)


@pytest.fixture()
def rsa_private_key_pem(rsa_keypair: tuple[str, str]) -> str:
    return rsa_keypair[0]


# --------------------------------------------------------------------------- #
# Env-var fallback (no active DB key -- the autouse fixture ensures that)
# --------------------------------------------------------------------------- #


async def test_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)
    assert await identity.mint_for_user("alice") is None


async def test_empty_user_id_returns_none(monkeypatch, rsa_private_key_pem):
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)
    assert await identity.mint_for_user("") is None


async def test_configured_mints_a_token(monkeypatch, rsa_private_key_pem):
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)

    token = await identity.mint_for_user("alice")
    assert token is not None
    assert isinstance(token, str)
    assert token.count(".") == 2  # header.payload.signature


async def test_mint_failure_returns_none_not_raise(monkeypatch, rsa_private_key_pem):
    """Even when configured, a mint-time failure must degrade to None."""
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)

    def _boom(user_id, ttl_seconds=None):
        raise RuntimeError("boom")

    import prometheus_api.agent.identity as upstream_identity

    monkeypatch.setattr(upstream_identity, "mint_user_token", _boom)

    assert await identity.mint_for_user("alice") is None


# --------------------------------------------------------------------------- #
# DB-first active key (Phase 3) -- takes priority over the env var
# --------------------------------------------------------------------------- #


def _stub_db_key(monkeypatch, kid: str, private_key_pem: str) -> None:
    async def _load():
        return kid, private_key_pem

    monkeypatch.setattr(identity, "_load_active_key_from_db", _load)


async def test_db_active_key_takes_priority_over_env(monkeypatch, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    db_kid = signing_keys.compute_kid(public_pem)
    _stub_db_key(monkeypatch, db_kid, private_pem)

    # Env is *also* configured, with a different (never-used) key -- if the env
    # path fired instead, minting still wouldn't fail, so this alone wouldn't
    # prove DB-first; the kid/signature assertions below do.
    from prometheus_api.agent.identity_keygen import generate_keypair

    env_private_pem, _ = generate_keypair(key_size=2048)
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", env_private_pem)

    token = await identity.mint_for_user("alice")
    assert token is not None

    import jwt

    header = jwt.get_unverified_header(token)
    assert header["kid"] == db_kid
    # Verifying with the DB key's public half must succeed...
    claims = jwt.decode(
        token, public_pem, algorithms=["RS256"], audience="prometheus-agents", issuer="prometheus-platform"
    )
    assert claims["sub"] == "alice"
    # ...and verifying with the *env* key's public half must fail, proving the
    # DB key signed it, not the env one.
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_private_key

    env_public_pem = (
        load_pem_private_key(env_private_pem.encode(), password=None)
        .public_key()
        .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token,
            env_public_pem,
            algorithms=["RS256"],
            audience="prometheus-agents",
            issuer="prometheus-platform",
        )


async def test_db_minted_token_verifies_through_the_unchanged_agent_side_verifier(monkeypatch, rsa_keypair):
    """The whole point of matching mint_user_token()'s claim shape: an agent
    (prometheus_api.agent.identity.verify_user_token, untouched by Phase 3)
    can't tell a DB-signed token from an env-signed one."""
    private_pem, public_pem = rsa_keypair
    kid = signing_keys.compute_kid(public_pem)
    _stub_db_key(monkeypatch, kid, private_pem)
    monkeypatch.setenv("USER_IDENTITY_PUBLIC_KEY", public_pem)
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)

    token = await identity.mint_for_user("bob")
    assert token is not None

    from prometheus_api.agent.identity import verify_user_token

    verified = verify_user_token(token)
    assert verified.user_id == "bob"


async def test_db_lookup_failure_falls_back_to_env(monkeypatch, rsa_private_key_pem):
    async def _boom():
        raise RuntimeError("admin-db unreachable")

    monkeypatch.setattr(identity, "_load_active_key_from_db", _boom)
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)

    token = await identity.mint_for_user("alice")
    assert token is not None  # degraded to the env fallback, not None/raise


async def test_active_key_is_cached_across_calls(monkeypatch, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    kid = signing_keys.compute_kid(public_pem)
    calls = []

    async def _load():
        calls.append(1)
        return kid, private_pem

    monkeypatch.setattr(identity, "_load_active_key_from_db", _load)

    await identity.mint_for_user("alice")
    await identity.mint_for_user("alice")
    assert len(calls) == 1  # second call hit the cache, no second DB round-trip


async def test_invalidating_the_cache_forces_a_reload(monkeypatch, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    kid = signing_keys.compute_kid(public_pem)
    calls = []

    async def _load():
        calls.append(1)
        return kid, private_pem

    monkeypatch.setattr(identity, "_load_active_key_from_db", _load)

    await identity.mint_for_user("alice")
    signing_keys.invalidate_active_key_cache()
    await identity.mint_for_user("alice")
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# verify_user_token -- the backend checking a token it minted (agent-facing routes)
# --------------------------------------------------------------------------- #


async def test_verify_env_minted_token(monkeypatch, rsa_private_key_pem):
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)
    token = await identity.mint_for_user("alice")
    assert token is not None
    assert await identity.verify_user_token(token) == "alice"


async def test_verify_db_minted_token_by_kid(monkeypatch, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    kid = signing_keys.compute_kid(public_pem)
    _stub_db_key(monkeypatch, kid, private_pem)
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)

    async def _public(requested: str):
        return public_pem if requested == kid else None

    monkeypatch.setattr(identity, "_load_public_key_from_db", _public)
    token = await identity.mint_for_user("alice")
    assert token is not None
    assert await identity.verify_user_token(token) == "alice"


async def test_verify_rejects_foreign_expired_and_garbage(monkeypatch, rsa_private_key_pem):
    from prometheus_api.agent.identity_keygen import generate_keypair

    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", generate_keypair(key_size=2048)[0])
    foreign = await identity.mint_for_user("mallory")
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)
    assert foreign is not None
    assert await identity.verify_user_token(foreign) is None

    monkeypatch.setenv("USER_IDENTITY_TTL", "-10")
    expired = await identity.mint_for_user("alice")
    assert expired is not None
    assert await identity.verify_user_token(expired) is None

    assert await identity.verify_user_token("") is None
    assert await identity.verify_user_token("not.a.jwt") is None


async def test_verify_without_any_key(monkeypatch, rsa_private_key_pem):
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)
    token = await identity.mint_for_user("alice")
    assert token is not None
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY")
    assert await identity.verify_user_token(token) is None
    assert await identity.verify_user_token("a.b.c") is None


async def test_verify_falls_back_to_env_key_when_db_lookup_fails(monkeypatch, rsa_private_key_pem):
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)
    token = await identity.mint_for_user("alice")
    assert token is not None

    async def _broken(kid: str):
        raise RuntimeError("admin-db down")

    monkeypatch.setattr(identity, "_load_public_key_from_db", _broken)
    assert await identity.verify_user_token(token) == "alice"


async def test_verify_with_unusable_env_key(monkeypatch, rsa_private_key_pem):
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", rsa_private_key_pem)
    token = await identity.mint_for_user("alice")
    assert token is not None
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", "not a pem")
    assert await identity.verify_user_token(token) is None


async def test_load_public_key_from_db_reads_active_and_retired_keys(monkeypatch, db_session):
    import app.db as db_mod
    from app.crypto import encrypt
    from app.db.models import SigningKey

    retired_kid, retired_private, retired_public = signing_keys.generate_signing_key()
    db_session.add(
        SigningKey(
            kid=retired_kid,
            private_key_encrypted=encrypt(retired_private),
            public_key_pem=retired_public,
            is_active=False,
        )
    )
    await db_session.commit()
    monkeypatch.setattr(db_mod, "get_session_factory", lambda: lambda: _SessionContext(db_session))

    assert await _real_load_public_key_from_db(retired_kid) == retired_public
    assert await _real_load_public_key_from_db("unknown-kid") is None


class _SessionContext:
    """``async with factory() as db`` over an existing session, without closing it."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False
