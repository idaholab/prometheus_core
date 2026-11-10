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

"""Auth + hardening tests (remediation step 05).

Covers logout revocation (AU-1), the DB-backed password check (AU-3), the
authenticated ``/api/config`` (AU-5), the identity-provider registry / OAuth seam
(AU-6), and the non-wildcard dev CORS origins (AU-9).
"""

from fastapi.testclient import TestClient


def _authed(monkeypatch, *, sid: str) -> tuple[TestClient, object]:
    from app import security
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "jwt_secret", "test-secret", raising=False)
    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)

    token = security.issue_token(security.User(identifier="alice"), sid=sid)
    client = TestClient(app)
    client.cookies.set(settings.cookie_name, token)
    return client, settings


# --------------------------------------------------------------------------- #
# AU-1 — logout invalidates the JWT (not just the cookie)
# --------------------------------------------------------------------------- #


def test_logout_revokes_token_even_if_replayed(monkeypatch):
    client, settings = _authed(monkeypatch, sid="sid-logout-unique")
    token = client.cookies.get(settings.cookie_name)
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200

    # Replay the *same* token (delete_cookie only clears the browser copy). Revocation
    # must reject it, proving logout isn't merely client-side.
    client.cookies.set(settings.cookie_name, token)
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------- #
# AU-3 — password check: correctness against the DB-backed users table
# --------------------------------------------------------------------------- #


async def test_password_provider_authenticates_and_rejects(db_session):
    from app import security
    from app.db.models import User as UserRow
    from app.passwords import hash_password

    db_session.add(UserRow(username="u", password_hash=hash_password("s3cret"), role="admin", provider="credentials"))
    await db_session.commit()

    provider = security.PasswordIdentityProvider()
    ok = await provider.authenticate("u", "s3cret", db_session)
    assert ok is not None and ok.role == "admin"
    assert await provider.authenticate("u", "wrong", db_session) is None  # wrong password
    assert await provider.authenticate("nope", "s3cret", db_session) is None  # unknown user
    assert await provider.authenticate("u", "", db_session) is None  # empty password never matches


async def test_password_provider_rejects_inactive_user(db_session):
    from app import security
    from app.db.models import User as UserRow
    from app.passwords import hash_password

    db_session.add(
        UserRow(
            username="deactivated",
            password_hash=hash_password("s3cret"),
            role="user",
            provider="credentials",
            is_active=False,
        )
    )
    await db_session.commit()

    provider = security.PasswordIdentityProvider()
    assert await provider.authenticate("deactivated", "s3cret", db_session) is None


async def test_login_endpoint_authenticates_against_db(monkeypatch, wire_db_session):
    """End-to-end: POST /api/auth/login against a real (DB-backed) provider."""
    from app import security
    from app.db.models import User as UserRow
    from app.main import app
    from app.passwords import hash_password

    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    wire_db_session.add(
        UserRow(username="alice", password_hash=hash_password("s3cret"), role="admin", provider="credentials")
    )
    await wire_db_session.commit()

    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    assert resp.cookies.get("prometheus_session")  # session cookie was set

    bad = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert bad.status_code == 401


async def test_login_answers_as_its_openapi_entry_documents(monkeypatch, wire_db_session):
    """Login accepts both documented body types and gives the documented errors.

    The route reads its body itself, so its request body and 4xx responses are
    declared by hand in app/routers/auth.py; this keeps them true.
    """
    from app import security
    from app.db.models import User as UserRow
    from app.main import app
    from app.passwords import hash_password

    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    wire_db_session.add(
        UserRow(username="alice", password_hash=hash_password("s3cret"), role="admin", provider="credentials")
    )
    await wire_db_session.commit()

    operation = app.openapi()["paths"]["/api/auth/login"]["post"]
    assert set(operation["requestBody"]["content"]) == {"application/json", "application/x-www-form-urlencoded"}
    assert {"401", "422"} <= set(operation["responses"])

    client = TestClient(app)
    form = client.post("/api/auth/login", data={"username": "alice", "password": "s3cret"})
    assert form.status_code == 200

    wrong = client.post("/api/auth/login", data={"username": "alice", "password": "wrong"})
    assert (wrong.status_code, wrong.json()["detail"]) == (401, "Invalid credentials")

    missing = client.post("/api/auth/login", json={"username": "alice"})
    assert (missing.status_code, missing.json()["detail"]) == (422, "username and password required")


# --------------------------------------------------------------------------- #
# AU-5 — /api/config is authenticated
# --------------------------------------------------------------------------- #


def test_config_requires_auth():
    from app.main import app

    assert TestClient(app).get("/api/config").status_code == 401


def test_config_returns_settings_when_authed(monkeypatch):
    client, _ = _authed(monkeypatch, sid="sid-config")
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert "max_upload_bytes" in resp.json()


# --------------------------------------------------------------------------- #
# AU-6 — identity-provider registry / OAuth seam
# --------------------------------------------------------------------------- #


def test_provider_registry_resolves_credentials(monkeypatch):
    from app import security

    assert security.get_provider("credentials") is security.password_provider
    assert security.get_provider("does-not-exist") is None


def test_oauth_callback_not_implemented(monkeypatch):
    client, _ = _authed(monkeypatch, sid="sid-oauth")
    assert client.get("/api/auth/callback/okta").status_code == 501


# --------------------------------------------------------------------------- #
# AU-9 — dev CORS origins are explicit, never a credentialed wildcard
# --------------------------------------------------------------------------- #


def test_dev_cors_origins_are_explicit():
    from app.config import settings

    assert "*" not in settings.dev_cors_origins
    assert settings.dev_cors_origins  # non-empty
    assert all(o.startswith("http") for o in settings.dev_cors_origins)
