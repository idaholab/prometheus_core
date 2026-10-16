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

"""Admin API: generate/activate/retire RS256 signing keys for the identity plane.

Postgres becomes authoritative for minting once an admin generates and
activates a key here -- app/identity.py::mint_for_user() prefers the DB's
active key, falling back to USER_IDENTITY_PRIVATE_KEY only while no active
row exists. The public keyset is served at GET /.well-known/jwks.json
(app/routers/jwks.py), unauthenticated, from every row in the table (see
app/db/models.py::SigningKey's docstring -- retired keys are not pruned from
it automatically).

Private key material never leaves this file: every response here carries only
metadata plus the public key -- the encrypted private key is decrypted only
inside app/identity.py at mint time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_responses import ADMIN_RESPONSES, ENCRYPTION_RESPONSES
from app.crypto import encrypt
from app.db import get_db_session
from app.db.models import SigningKey
from app.security import require_admin
from app.signing_keys import generate_signing_key, invalidate_active_key_cache

router = APIRouter(
    prefix="/api/admin/signing-keys",
    tags=["admin-signing-keys"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_RESPONSES,
)


class SigningKeyOut(BaseModel):
    id: str
    kid: str
    public_key_pem: str
    is_active: bool
    created_at: datetime
    retired_at: Optional[datetime] = None


def _out(row: SigningKey) -> SigningKeyOut:
    return SigningKeyOut(
        id=str(row.id),
        kid=row.kid,
        public_key_pem=row.public_key_pem,
        is_active=row.is_active,
        created_at=row.created_at,
        retired_at=row.retired_at,
    )


async def _get_or_404(db: AsyncSession, key_id: uuid.UUID) -> SigningKey:
    row = await db.get(SigningKey, key_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signing key not found")
    return row


@router.get("", response_model=list[SigningKeyOut])
async def list_keys(db: AsyncSession = Depends(get_db_session)) -> list[SigningKeyOut]:
    rows = (await db.scalars(select(SigningKey).order_by(SigningKey.created_at.desc()))).all()
    return [_out(row) for row in rows]


@router.post("", response_model=SigningKeyOut, status_code=status.HTTP_201_CREATED, responses=ENCRYPTION_RESPONSES)
async def create_key(db: AsyncSession = Depends(get_db_session)) -> SigningKeyOut:
    """Generate a new RS256 keypair. Does not activate it -- see .../activate."""
    kid, private_pem, public_pem = generate_signing_key()
    row = SigningKey(
        kid=kid,
        private_key_encrypted=encrypt(private_pem),
        public_key_pem=public_pem,
        is_active=False,
    )
    db.add(row)
    await db.commit()
    return _out(row)


@router.post("/{key_id}/activate", response_model=SigningKeyOut)
async def activate_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> SigningKeyOut:
    """Make this the one key mint_for_user() signs with.

    Deactivates whichever key was active before -- it stays in the table and
    keeps appearing in the JWKS, un-retired, until an admin explicitly retires
    it (see /retire below).
    """
    row = await _get_or_404(db, key_id)
    if row.retired_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot activate a retired key")

    if not row.is_active:
        currently_active = (await db.scalars(select(SigningKey).where(SigningKey.is_active.is_(True)))).all()
        for other in currently_active:
            other.is_active = False
        row.is_active = True
        await db.commit()

    invalidate_active_key_cache()
    return _out(row)


@router.post("/{key_id}/retire", response_model=SigningKeyOut)
async def retire_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> SigningKeyOut:
    """Mark this key as done -- it keeps verifying (still served in the JWKS)
    but is no longer eligible for /activate.

    Refuses to retire the currently active key with no replacement: that would
    leave mint_for_user() with no active DB row at all, silently falling back
    to the (usually unconfigured) env var. Activate a replacement first.
    """
    row = await _get_or_404(db, key_id)
    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot retire the active key -- activate a replacement first",
        )

    if row.retired_at is None:
        row.retired_at = datetime.now(timezone.utc)
        await db.commit()

    invalidate_active_key_cache()
    return _out(row)
