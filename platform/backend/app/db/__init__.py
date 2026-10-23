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

"""Async SQLAlchemy engine/session for the admin plane (users, OIDC providers,
signing keys).

This is a separate datastore from Redis (chat/session/artifact state and agent
registrations, all ephemeral-ish). The admin plane is the one place in this platform that needs a
real relational store with migrations -- see ``app/db/models.py`` for the
schema and ``alembic/`` for migrations.

Schema is managed by Alembic in real deployments (``alembic upgrade head``);
``create_all()`` below exists only for tests, which use an in-memory SQLite
engine and skip Alembic entirely (see ``tests/conftest.py``).
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all admin-plane ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.admin_database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session, committing on success.

    On an unhandled exception the session is rolled back and the exception
    re-raised (FastAPI's exception handling then converts it to a response) --
    callers never need to manage transactions themselves for the common
    single-request-scoped-unit-of-work case.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_for_tests() -> None:
    """Create all tables against the current engine. Tests only -- real
    deployments use Alembic migrations (``alembic upgrade head``)."""
    # Import models so they register on Base.metadata before create_all.
    from app.db import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose the engine's connection pool. Call on app shutdown / test teardown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
