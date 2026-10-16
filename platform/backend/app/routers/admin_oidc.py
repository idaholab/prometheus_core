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

"""Admin API: CRUD for OIDC identity providers (app/db/models.py::OidcProvider).

``client_secret`` is write-only -- accepted on create/update, Fernet-encrypted
at rest (app/crypto.py), never returned in any response. ``provider_id`` is
immutable after creation (it's the URL slug in GET /api/auth/login/{provider_id}
and the value stored in users.provider for accounts created through it --
renaming it would orphan those rows' provider column).

Registry side-effects: create registers a GenericOidcProvider so
GET /api/auth/login/{provider_id} resolves it immediately; delete
unregisters it. Update needs no registry action -- GenericOidcProvider reads
its row fresh from the DB on every call (see app/security.py).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_responses import ADMIN_RESPONSES, ENCRYPTION_RESPONSES
from app.crypto import encrypt
from app.db import get_db_session
from app.db.models import OidcProvider
from app.security import GenericOidcProvider, register_provider, require_admin, unregister_provider

router = APIRouter(
    prefix="/api/admin/oidc-providers",
    tags=["admin-oidc-providers"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_RESPONSES,
)

_ROLES = {"admin", "user"}
# provider_id is a URL path segment (GET /api/auth/login/{provider_id}) and a
# users.provider value -- lowercase alnum segments joined by single hyphens,
# no leading/trailing hyphen. Length capped to match the DB column (String(64)).
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_MAX_LEN = 64


class OidcProviderOut(BaseModel):
    id: str
    provider_id: str
    display_name: str
    issuer_url: str
    client_id: str
    scopes: str
    default_role: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    # client_secret intentionally omitted -- write-only, never read back.


class OidcProviderCreate(BaseModel):
    provider_id: str
    display_name: str
    issuer_url: str
    client_id: str
    client_secret: str
    scopes: str = "openid profile email"
    default_role: str = "user"
    is_enabled: bool = True


class OidcProviderUpdate(BaseModel):
    """Partial update -- every field optional. ``client_secret`` omitted keeps
    the existing one; ``provider_id`` isn't editable at all (see module docstring)."""

    display_name: Optional[str] = None
    issuer_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scopes: Optional[str] = None
    default_role: Optional[str] = None
    is_enabled: Optional[bool] = None


def _out(row: OidcProvider) -> OidcProviderOut:
    return OidcProviderOut(
        id=str(row.id),
        provider_id=row.provider_id,
        display_name=row.display_name,
        issuer_url=row.issuer_url,
        client_id=row.client_id,
        scopes=row.scopes,
        default_role=row.default_role,
        is_enabled=row.is_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_role(role: Optional[str]) -> None:
    if role is not None and role not in _ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"default_role must be one of {sorted(_ROLES)}"
        )


async def _get_or_404(db: AsyncSession, provider_row_id: uuid.UUID) -> OidcProvider:
    row = await db.get(OidcProvider, provider_row_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC provider not found")
    return row


@router.get("", response_model=list[OidcProviderOut])
async def list_providers(db: AsyncSession = Depends(get_db_session)) -> list[OidcProviderOut]:
    rows = (await db.scalars(select(OidcProvider).order_by(OidcProvider.display_name))).all()
    return [_out(row) for row in rows]


@router.post("", response_model=OidcProviderOut, status_code=status.HTTP_201_CREATED, responses=ENCRYPTION_RESPONSES)
async def create_provider(payload: OidcProviderCreate, db: AsyncSession = Depends(get_db_session)) -> OidcProviderOut:
    provider_id = payload.provider_id.strip()
    if len(provider_id) > _SLUG_MAX_LEN or not _SLUG_RE.match(provider_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider_id must be lowercase letters, digits, and hyphens (e.g. 'okta', 'my-idp')",
        )
    if not payload.client_secret:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="client_secret is required")
    _validate_role(payload.default_role)

    row = OidcProvider(
        provider_id=provider_id,
        display_name=payload.display_name,
        issuer_url=payload.issuer_url,
        client_id=payload.client_id,
        client_secret_encrypted=encrypt(payload.client_secret),
        scopes=payload.scopes,
        default_role=payload.default_role,
        is_enabled=payload.is_enabled,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="provider_id already exists") from None

    register_provider(GenericOidcProvider(row.provider_id))
    return _out(row)


@router.patch("/{provider_row_id}", response_model=OidcProviderOut, responses=ENCRYPTION_RESPONSES)
async def update_provider(
    provider_row_id: uuid.UUID, payload: OidcProviderUpdate, db: AsyncSession = Depends(get_db_session)
) -> OidcProviderOut:
    row = await _get_or_404(db, provider_row_id)
    _validate_role(payload.default_role)

    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.issuer_url is not None:
        row.issuer_url = payload.issuer_url
    if payload.client_id is not None:
        row.client_id = payload.client_id
    if payload.client_secret:
        row.client_secret_encrypted = encrypt(payload.client_secret)
    if payload.scopes is not None:
        row.scopes = payload.scopes
    if payload.default_role is not None:
        row.default_role = payload.default_role
    if payload.is_enabled is not None:
        row.is_enabled = payload.is_enabled

    await db.commit()
    # updated_at's onupdate=func.now() (app/db/models.py) leaves it expired
    # after an UPDATE (no RETURNING round-trip the way INSERT gets one) --
    # refresh explicitly rather than let _out()'s attribute access trigger an
    # implicit lazy-load, which AsyncSession doesn't support outside a greenlet.
    await db.refresh(row)
    # No registry change needed -- GenericOidcProvider re-reads this row fresh
    # on every call, so the edit (including is_enabled) takes effect immediately.
    return _out(row)


@router.delete("/{provider_row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_row_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> None:
    row = await _get_or_404(db, provider_row_id)
    provider_id = row.provider_id
    await db.delete(row)
    await db.commit()
    unregister_provider(provider_id)
