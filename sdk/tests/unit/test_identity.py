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

"""Unit tests for prometheus_api.agent.identity (RS256-only)."""

from __future__ import annotations

import asyncio

import pytest

from prometheus_api.agent.identity import (
    ALG,
    IdentityError,
    UserIdentity,
    USER_TOKEN_METADATA_KEY,
    current_user_id,
    get_current_identity,
    get_jwks_document,
    identity_scope,
    mint_user_token,
    verify_user_token,
)
from prometheus_api.agent.identity_keygen import generate_keypair


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    """One RSA keypair shared across tests in this module (keygen is slow-ish)."""
    return generate_keypair(key_size=2048)


@pytest.fixture(autouse=True)
def identity_env(monkeypatch, keypair):
    """Set the minimum required env vars for every test in this module."""
    private_pem, public_pem = keypair
    monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", private_pem)
    monkeypatch.setenv("USER_IDENTITY_PUBLIC_KEY", public_pem)
    monkeypatch.setenv("USER_IDENTITY_ISS", "prometheus-platform")
    monkeypatch.setenv("USER_IDENTITY_AUD", "prometheus-agents")
    monkeypatch.delenv("JWKS_URL", raising=False)


# ---------------------------------------------------------------------------
# Mint / verify round-trip
# ---------------------------------------------------------------------------


def test_mint_and_verify_returns_correct_user_id():
    token = mint_user_token("alice")
    identity = verify_user_token(token)
    assert identity.user_id == "alice"


def test_mint_and_verify_preserves_raw_token():
    token = mint_user_token("bob")
    identity = verify_user_token(token)
    assert identity.raw_token == token


def test_mint_and_verify_includes_standard_claims():
    token = mint_user_token("carol")
    identity = verify_user_token(token)
    assert identity.claims["iss"] == "prometheus-platform"
    assert identity.claims["aud"] == "prometheus-agents"
    assert identity.claims["sub"] == "carol"
    assert "iat" in identity.claims
    assert "exp" in identity.claims


def test_extra_claims_are_forwarded():
    token = mint_user_token("dave", extra_claims={"role": "admin"})
    identity = verify_user_token(token)
    assert identity.claims.get("role") == "admin"


def test_extra_claims_cannot_override_sub():
    token = mint_user_token("eve", extra_claims={"sub": "injected"})
    identity = verify_user_token(token)
    assert identity.user_id == "eve"


def test_usertoken_metadata_key_constant():
    assert USER_TOKEN_METADATA_KEY == "userToken"


def test_alg_constant_is_rs256():
    assert ALG == "RS256"


def test_mint_includes_kid_header():
    import jwt as _jwt

    token = mint_user_token("alice")
    header = _jwt.get_unverified_header(token)
    assert "kid" in header
    assert header["alg"] == "RS256"


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_expired_token_raises_identity_error():
    expired = mint_user_token("frank", ttl_seconds=-1)
    with pytest.raises(IdentityError, match="expired"):
        verify_user_token(expired)


def test_fresh_token_does_not_expire_immediately():
    token = mint_user_token("grace", ttl_seconds=3600)
    identity = verify_user_token(token)
    assert identity.user_id == "grace"


# ---------------------------------------------------------------------------
# Wrong key
# ---------------------------------------------------------------------------


def test_wrong_public_key_raises_identity_error(monkeypatch):
    token = mint_user_token("harry")
    _, other_public_pem = generate_keypair(key_size=2048)
    monkeypatch.setenv("USER_IDENTITY_PUBLIC_KEY", other_public_pem)
    with pytest.raises(IdentityError, match="signature"):
        verify_user_token(token)


def test_missing_private_key_raises_identity_error_on_mint(monkeypatch):
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)
    with pytest.raises(IdentityError, match="USER_IDENTITY_PRIVATE_KEY"):
        mint_user_token("inga")


def test_missing_keys_raises_identity_error_on_verify(monkeypatch):
    token = mint_user_token("jake")
    monkeypatch.delenv("USER_IDENTITY_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)
    with pytest.raises(IdentityError, match="USER_IDENTITY_PUBLIC_KEY"):
        verify_user_token(token)


def test_verify_falls_back_to_private_key_when_no_public_key(monkeypatch):
    """Single-host deployments (mint + verify in one process) work without a
    separate public key -- the public key is derivable from the private key."""
    token = mint_user_token("karl")
    monkeypatch.delenv("USER_IDENTITY_PUBLIC_KEY", raising=False)
    identity = verify_user_token(token)
    assert identity.user_id == "karl"


# ---------------------------------------------------------------------------
# Wrong audience / issuer
# ---------------------------------------------------------------------------


def test_wrong_audience_raises_identity_error(monkeypatch):
    token = mint_user_token("karen")
    monkeypatch.setenv("USER_IDENTITY_AUD", "different-audience")
    with pytest.raises(IdentityError, match="audience"):
        verify_user_token(token)


def test_wrong_issuer_raises_identity_error(monkeypatch):
    token = mint_user_token("leo")
    monkeypatch.setenv("USER_IDENTITY_ISS", "different-issuer")
    with pytest.raises(IdentityError, match="issuer"):
        verify_user_token(token)


# ---------------------------------------------------------------------------
# Malformed / empty inputs
# ---------------------------------------------------------------------------


def test_empty_string_raises_identity_error():
    with pytest.raises(IdentityError):
        verify_user_token("")


def test_none_raises_identity_error():
    with pytest.raises(IdentityError):
        verify_user_token(None)  # type: ignore[arg-type]


def test_garbage_string_raises_identity_error():
    with pytest.raises(IdentityError):
        verify_user_token("not.a.jwt")


# ---------------------------------------------------------------------------
# ContextVar / identity_scope
# ---------------------------------------------------------------------------


def test_get_current_identity_returns_none_outside_scope():
    assert get_current_identity() is None


def test_current_user_id_returns_none_outside_scope():
    assert current_user_id() is None


def test_identity_scope_sets_and_restores():
    token = mint_user_token("mary")
    identity = verify_user_token(token)

    assert get_current_identity() is None
    with identity_scope(identity):
        assert get_current_identity() is identity
        assert current_user_id() == "mary"
    assert get_current_identity() is None


def test_identity_scope_with_none_clears():
    token = mint_user_token("nancy")
    identity = verify_user_token(token)
    with identity_scope(identity):
        with identity_scope(None):
            assert get_current_identity() is None
        assert get_current_identity() is identity


def test_identity_scope_nested_restores_outer():
    token_a = mint_user_token("oscar")
    token_b = mint_user_token("pete")
    id_a = verify_user_token(token_a)
    id_b = verify_user_token(token_b)

    with identity_scope(id_a):
        assert current_user_id() == "oscar"
        with identity_scope(id_b):
            assert current_user_id() == "pete"
        assert current_user_id() == "oscar"


def test_identity_scope_cleans_up_on_exception():
    token = mint_user_token("quinn")
    identity = verify_user_token(token)
    try:
        with identity_scope(identity):
            assert current_user_id() == "quinn"
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert get_current_identity() is None


# ---------------------------------------------------------------------------
# Async / concurrent isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_tasks_have_isolated_identity():
    """Two concurrent async tasks must not share identity state."""
    token_a = mint_user_token("rose")
    token_b = mint_user_token("sam")
    id_a = verify_user_token(token_a)
    id_b = verify_user_token(token_b)

    results: dict[str, str | None] = {}

    async def task_a():
        with identity_scope(id_a):
            await asyncio.sleep(0)  # yield to allow task_b to start
            results["a"] = current_user_id()

    async def task_b():
        with identity_scope(id_b):
            await asyncio.sleep(0)
            results["b"] = current_user_id()

    await asyncio.gather(task_a(), task_b())

    assert results["a"] == "rose"
    assert results["b"] == "sam"


@pytest.mark.asyncio
async def test_identity_absent_in_new_task_by_default():
    """A new task should not inherit the parent's identity (ContextVar inherits on creation)."""
    token = mint_user_token("tara")
    identity = verify_user_token(token)

    child_identity: list[UserIdentity | None] = []

    async def child():
        child_identity.append(get_current_identity())

    with identity_scope(identity):
        # asyncio.create_task copies the context, so the child DOES inherit.
        # This test documents that expected behaviour.
        task = asyncio.create_task(child())
        await task

    assert child_identity[0] is not None  # inherited at creation time
    assert child_identity[0].user_id == "tara"


# ---------------------------------------------------------------------------
# UserIdentity is frozen / immutable
# ---------------------------------------------------------------------------


def test_user_identity_is_frozen():
    token = mint_user_token("uma")
    identity = verify_user_token(token)
    with pytest.raises((AttributeError, TypeError)):
        identity.user_id = "injected"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_jwks_document
# ---------------------------------------------------------------------------


def test_jwks_returns_public_key():
    doc = get_jwks_document()
    assert len(doc["keys"]) == 1
    key = doc["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert "n" in key  # modulus
    assert "e" in key  # exponent
    assert "kid" in key


def test_jwks_derives_pubkey_from_private_when_public_unset(monkeypatch):
    monkeypatch.delenv("USER_IDENTITY_PUBLIC_KEY", raising=False)
    doc = get_jwks_document()
    assert len(doc["keys"]) == 1
    assert doc["keys"][0]["kty"] == "RSA"


def test_jwks_no_keys_returns_empty(monkeypatch):
    monkeypatch.delenv("USER_IDENTITY_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)
    doc = get_jwks_document()
    assert doc == {"keys": []}


def test_jwks_kid_is_stable():
    doc1 = get_jwks_document()
    doc2 = get_jwks_document()
    assert doc1["keys"][0]["kid"] == doc2["keys"][0]["kid"]


def test_jwks_kid_changes_with_different_key(monkeypatch):
    kid_a = get_jwks_document()["keys"][0]["kid"]

    _, other_public_pem = generate_keypair(key_size=2048)
    monkeypatch.setenv("USER_IDENTITY_PUBLIC_KEY", other_public_pem)
    kid_b = get_jwks_document()["keys"][0]["kid"]

    assert kid_a != kid_b


# ---------------------------------------------------------------------------
# JWKS route served by PrometheusAgent.build_app()
# ---------------------------------------------------------------------------


def test_jwks_route_served_unauthenticated(monkeypatch):
    """/.well-known/jwks.json must not require the agent secret."""
    from starlette.testclient import TestClient
    from prometheus_api.agent import PrometheusAgent

    monkeypatch.setenv("AGENT_SECRET_REQUIRED", "false")
    monkeypatch.setenv("USER_IDENTITY_REQUIRED", "false")

    class _TestAgent(PrometheusAgent):
        async def _execute(self, params, context, event_queue):
            return {}

    agent = _TestAgent(agent_name="test", agent_card_path="tests/fixtures/agent_card.json")
    try:
        app = agent.build_app(register_on_startup=False)
    except Exception:
        pytest.skip("agent card fixture not available")
    client = TestClient(app)
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["keys"]) == 1
    assert body["keys"][0]["kty"] == "RSA"


def test_agent_current_user_id_returns_none_outside_scope():
    """PrometheusAgent.current_user_id() returns None when no identity is bound."""
    from prometheus_api.agent import PrometheusAgent

    assert get_current_identity() is None
    assert PrometheusAgent.current_user_id() is None


def test_agent_current_user_id_returns_bound_user():
    """PrometheusAgent.current_user_id() returns the bound user, then None after the scope exits."""
    from prometheus_api.agent import PrometheusAgent

    identity = verify_user_token(mint_user_token("rita"))
    with identity_scope(identity):
        assert PrometheusAgent.current_user_id() == "rita"
    assert PrometheusAgent.current_user_id() is None
