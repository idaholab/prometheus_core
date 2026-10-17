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

"""Unit tests for app.signing_keys.ensure_active_signing_key() -- the startup
bootstrap that creates one active RS256 signing key on a fresh install."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import jwt
import pytest
from sqlalchemy import func, select

from app import signing_keys
from app.crypto import decrypt
from app.db.models import SigningKey


@pytest.fixture(autouse=True)
def no_static_identity_key(monkeypatch):
    """The bootstrap skips when USER_IDENTITY_PRIVATE_KEY is set; keep it unset."""
    monkeypatch.delenv("USER_IDENTITY_PRIVATE_KEY", raising=False)


@pytest.mark.asyncio
async def test_bootstrap_creates_one_active_key(db_session):
    # A fresh cache entry the bootstrap must invalidate.
    signing_keys.set_cached_active_key(("stale-kid", "stale-pem"))

    kid = await signing_keys.ensure_active_signing_key(db_session)

    assert kid is not None
    rows = (await db_session.scalars(select(SigningKey))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.is_active is True
    assert row.kid == kid

    private_pem = decrypt(row.private_key_encrypted)
    token = jwt.encode({"sub": "bootstrap-check"}, private_pem, algorithm="RS256", headers={"kid": kid})
    claims = jwt.decode(token, row.public_key_pem, algorithms=["RS256"])
    assert claims["sub"] == "bootstrap-check"

    is_fresh, _ = signing_keys.cached_active_key()
    assert is_fresh is False

    assert await signing_keys.ensure_active_signing_key(db_session) is None
    assert await db_session.scalar(select(func.count()).select_from(SigningKey)) == 1


_RETIRED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


async def _key_rows(db_session) -> dict[str, tuple[bool, datetime | None]]:
    """Every signing_keys row as ``{kid: (is_active, retired_at)}``, read fresh from the table."""
    result = await db_session.execute(select(SigningKey.kid, SigningKey.is_active, SigningKey.retired_at))
    return {kid: (is_active, retired_at) for kid, is_active, retired_at in result.all()}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seed", "static_key", "creates"),
    [
        pytest.param([("active-kid", True, None)], False, False, id="active_key_present"),
        pytest.param([], True, False, id="static_key_set"),
        pytest.param(
            [("inactive-kid", False, None), ("retired-kid", False, _RETIRED_AT)],
            False,
            True,
            id="only_inactive_and_retired",
        ),
    ],
)
async def test_bootstrap_respects_existing_and_static_keys(db_session, monkeypatch, seed, static_key, creates):
    for kid, is_active, retired_at in seed:
        db_session.add(
            SigningKey(
                kid=kid,
                private_key_encrypted=b"unused-in-this-test",
                public_key_pem=f"pem-{kid}",
                is_active=is_active,
                retired_at=retired_at,
            )
        )
    await db_session.commit()
    if static_key:
        monkeypatch.setenv("USER_IDENTITY_PRIVATE_KEY", "static-key-placeholder")
    before = await _key_rows(db_session)

    kid = await signing_keys.ensure_active_signing_key(db_session)

    after = await _key_rows(db_session)
    if not creates:
        assert kid is None
        assert after == before
        return

    assert kid is not None
    assert kid not in before
    assert after.pop(kid) == (True, None)
    # The old rows keep is_active=False and their retired_at; none was activated.
    assert after == before


@pytest.mark.asyncio
async def test_bootstrap_survives_missing_encryption_key(db_session, monkeypatch, caplog):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_db_encryption_key", "")
    caplog.set_level(logging.WARNING, logger="app.signing_keys")

    kid = await signing_keys.ensure_active_signing_key(db_session)

    assert kid is None
    assert await _key_rows(db_session) == {}
    warnings = [r for r in caplog.records if r.name == "app.signing_keys" and r.levelno == logging.WARNING]
    assert any("ADMIN_DB_ENCRYPTION_KEY" in r.getMessage() for r in warnings)
