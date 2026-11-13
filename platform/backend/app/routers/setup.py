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

"""First-run setup: is the platform bootstrapped yet, and create the first admin.

Both routes are deliberately unauthenticated — they exist precisely to get the
platform from "no admin exists" to "an admin can log in", before any session
cookie could exist. Once a single ``users`` row exists (bootstrapped here, or
provisioned any other way), ``/bootstrap`` refuses forever; ongoing user
management is the admin API (``routers/admin_users.py``, not yet built).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.db.models import User as UserRow
from app.openapi import TAG_SETUP
from app.passwords import hash_password
from app.security import User, issue_token, set_session_cookie, verify_token
from app.sessions import get_store

router = APIRouter(prefix="/api/setup", tags=[TAG_SETUP])

# Arbitrary constant advisory-lock key, scoped to this one use (bootstrap must
# happen at most once). Any fixed int works; it just has to not collide with a
# lock key used elsewhere in this database.
_BOOTSTRAP_LOCK_KEY = 0x50524F4D_00000001


class SetupStatus(BaseModel):
    needs_setup: bool


class BootstrapRequest(BaseModel):
    username: str
    password: str


class BootstrapResult(BaseModel):
    user: User


async def _user_count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(UserRow)) or 0


@router.get("/status", response_model=SetupStatus)
async def get_setup_status(db: AsyncSession = Depends(get_db_session)) -> SetupStatus:
    """``needs_setup`` is true iff no ``users`` row exists yet."""
    return SetupStatus(needs_setup=await _user_count(db) == 0)


@router.post("/bootstrap", response_model=BootstrapResult)
async def bootstrap(
    payload: BootstrapRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> BootstrapResult:
    """Create the first admin user, once, and log them in immediately.

    Closing the race between two concurrent first requests matters here more than
    almost anywhere else in the app (it's the one window where *anyone* can create
    an admin account) so, on Postgres, this takes a transaction-scoped advisory
    lock before checking the count -- a second concurrent request blocks until the
    first commits (at which point its own count check correctly sees >0). SQLite
    (used in tests, and only in tests) has no advisory locks; the plain
    check-then-insert below is fine there since TestClient issues requests
    sequentially, not concurrently.
    """
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="username and password required")

    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY})

    if await _user_count(db) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup has already been completed")

    row = UserRow(
        username=username,
        password_hash=hash_password(payload.password),
        role="admin",
        provider="credentials",
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Username collision (or, absent the advisory lock, a genuine race) --
        # either way setup is no longer this request's to complete.
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup has already been completed") from None

    user = User(identifier=row.username, role=row.role, provider=row.provider)
    token = issue_token(user)
    await get_store(request).get_or_create(verify_token(token).sid)
    set_session_cookie(response, token)
    return BootstrapResult(user=user)
