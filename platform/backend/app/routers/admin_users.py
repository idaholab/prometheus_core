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

"""Admin API: manage local users in the admin-plane ``users`` table.

Every route here is gated by :func:`app.security.require_admin`. Only local
(``provider="credentials"``) accounts are *created* through this API -- OIDC
accounts auto-provision themselves on first login (Phase 4); their role/active
status can still be edited here like any other row.

A recurring guard throughout: never let an action leave the platform with zero
active admins (mirrors ``routers/setup.py``'s bootstrap-always-admin rule --
that's how the *first* admin exists; this is what stops the *last* one from
locking everyone out).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_responses import ADMIN_RESPONSES
from app.db import get_db_session
from app.db.models import User as UserRow
from app.passwords import hash_password
from app.security import require_admin

router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_admin)],
    responses=ADMIN_RESPONSES,
)

_ROLES = {"admin", "user"}


class AdminUserOut(BaseModel):
    id: str
    username: str
    role: str
    provider: str
    external_subject: Optional[str] = None
    email: Optional[str] = None
    display_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class AdminUserUpdate(BaseModel):
    """Partial update -- every field is optional; only the ones sent are applied."""

    role: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None
    email: Optional[str] = None


def _out(row: UserRow) -> AdminUserOut:
    return AdminUserOut(
        id=str(row.id),
        username=row.username,
        role=row.role,
        provider=row.provider,
        external_subject=row.external_subject,
        email=row.email,
        display_name=row.display_name,
        is_active=row.is_active,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


def _validate_role(role: Optional[str]) -> None:
    if role is not None and role not in _ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"role must be one of {sorted(_ROLES)}"
        )


async def _active_admin_count(db: AsyncSession, *, exclude_id: Optional[uuid.UUID] = None) -> int:
    stmt = select(func.count()).select_from(UserRow).where(UserRow.role == "admin", UserRow.is_active.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(UserRow.id != exclude_id)
    return await db.scalar(stmt) or 0


async def _get_or_404(db: AsyncSession, user_id: uuid.UUID) -> UserRow:
    row = await db.get(UserRow, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return row


@router.get("", response_model=list[AdminUserOut])
async def list_users(db: AsyncSession = Depends(get_db_session)) -> list[AdminUserOut]:
    rows = (await db.scalars(select(UserRow).order_by(UserRow.username))).all()
    return [_out(row) for row in rows]


@router.post("", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: AdminUserCreate, db: AsyncSession = Depends(get_db_session)) -> AdminUserOut:
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="username and password required")
    _validate_role(payload.role)

    row = UserRow(
        username=username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        provider="credentials",
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from None
    return _out(row)


@router.patch("/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: uuid.UUID, payload: AdminUserUpdate, db: AsyncSession = Depends(get_db_session)
) -> AdminUserOut:
    row = await _get_or_404(db, user_id)
    _validate_role(payload.role)

    # Only matters if this row is *currently* counted as an active admin, and this
    # update would take that away from it (role change off "admin", or deactivation).
    if row.role == "admin" and row.is_active:
        losing_admin_status = (payload.role is not None and payload.role != "admin") or payload.is_active is False
        if losing_admin_status and await _active_admin_count(db, exclude_id=row.id) < 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot remove the last active admin")

    if payload.role is not None:
        row.role = payload.role
    if payload.password:
        row.password_hash = hash_password(payload.password)
    if payload.is_active is not None:
        row.is_active = payload.is_active
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.email is not None:
        row.email = payload.email

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Update violates a uniqueness constraint"
        ) from None
    return _out(row)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> None:
    row = await _get_or_404(db, user_id)
    if row.role == "admin" and row.is_active and await _active_admin_count(db, exclude_id=row.id) < 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot remove the last active admin")
    await db.delete(row)
    await db.commit()
