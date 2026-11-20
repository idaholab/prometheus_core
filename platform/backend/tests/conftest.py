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

"""Shared fixtures for the backend test suite.

Admin-plane tests (users, OIDC providers, signing keys) never touch a real
Postgres -- ``db_session`` gives each test its own in-memory SQLite engine
with the ORM schema created directly from ``Base.metadata`` (bypassing
Alembic, which is the production migration path; see ``app/db.py``).

Valkey-backed state (the session store, the SSE event bus, session revocation) is
served by ``fakeredis`` rather than a container. ``valkey_state`` is autouse: every
test gets ``app.state.redis`` / ``session_store`` / ``event_bus`` wired to a fresh
in-memory instance, because a bare ``TestClient(app)`` does not run the lifespan that
normally builds them. Ask for the ``session_store``, ``fake_redis`` or ``event_bus``
fixture to reach the objects that were installed.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.db import models  # noqa: F401  (registers models on Base.metadata)
from app.sessions import SessionStore


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A fresh in-memory SQLite session, schema created, torn down after the test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def wire_db_session(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Override the app's ``get_db_session`` dependency with the in-memory SQLite
    ``db_session`` above, for the duration of one test -- for tests that exercise a
    router through ``TestClient`` rather than the ORM layer directly."""
    from app.db import get_db_session
    from app.main import app

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    try:
        yield db_session
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def admin_db_encryption_key(monkeypatch):
    """Every test gets a valid Fernet key for app.crypto by default.

    Individual tests that need to exercise the "unconfigured" path should
    monkeypatch settings.admin_db_encryption_key back to "" themselves.
    """
    from cryptography.fernet import Fernet

    from app.config import settings

    monkeypatch.setattr(settings, "admin_db_encryption_key", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def no_real_signing_key_db_lookup(monkeypatch):
    """app.identity.mint_for_user() looks up admin-db's active signing key via its
    own ad-hoc session (app.db.get_session_factory()), not through the
    get_db_session dependency -- wire_db_session's override doesn't reach it.

    Stub the lookup to "no active key" by default so every other test (chat,
    uploads, anything that calls mint_for_user) never attempts a real network
    connection to admin-db, and reset the module-level active-key cache
    (app/signing_keys.py) so a value set by one test can't leak into the next.
    Tests exercising the DB-first minting path (test_identity.py) override
    ``app.identity._load_active_key_from_db`` themselves.
    """
    import app.identity as identity_mod
    from app import signing_keys

    signing_keys.invalidate_active_key_cache()

    async def _no_active_key() -> None:
        return None

    async def _no_public_key(kid: str) -> None:
        return None

    monkeypatch.setattr(identity_mod, "_load_active_key_from_db", _no_active_key)
    monkeypatch.setattr(identity_mod, "_load_public_key_from_db", _no_public_key)
    yield
    signing_keys.invalidate_active_key_cache()


@pytest.fixture(autouse=True)
def no_real_oidc_provider_registration(monkeypatch):
    """app.main.lifespan() queries admin-db for every configured OidcProvider
    row at startup (app.security.register_existing_oidc_providers) so they're
    resolvable via get_provider() immediately. No live admin-db in tests --
    stub it to a no-op like ``no_real_signing_key_db_lookup`` above. Tests exercising the
    OIDC flow register a GenericOidcProvider directly via
    ``app.security.register_provider`` and don't need this step at all.

    Also clears the provider registry back to just the password provider
    after each test, so a provider registered by one test can't leak into the
    next (module-level global, like the signing-key cache above).
    """
    import app.security as security_mod

    async def _no_op(db) -> None:
        return None

    monkeypatch.setattr(security_mod, "register_existing_oidc_providers", _no_op)
    yield
    security_mod._PROVIDERS.clear()
    security_mod._PROVIDERS[security_mod.password_provider.name] = security_mod.password_provider


@pytest.fixture(autouse=True)
def no_real_signing_key_bootstrap(monkeypatch):
    """app.main.lifespan() also ensures one active identity signing key in
    admin-db at startup (app.signing_keys.ensure_active_signing_key). No live
    admin-db in tests -- stub the lifespan's reference to a no-op, like
    ``no_real_oidc_provider_registration`` above. test_signing_key_bootstrap.py
    calls ``app.signing_keys.ensure_active_signing_key`` directly, so this
    patch on ``app.main`` does not reach it.
    """
    import app.main as main_mod

    async def _no_op(db) -> None:
        return None

    monkeypatch.setattr(main_mod, "ensure_active_signing_key", _no_op)


# --------------------------------------------------------------------------- #
# Valkey-backed state (sessions, SSE event bus, revocation)
# --------------------------------------------------------------------------- #


@pytest.fixture
def valkey_server() -> Any:
    """The in-memory datastore behind this test's Valkey clients.

    Exposed separately from :func:`fake_redis` so a test can build a *second* client
    over the same data (``FakeRedis(server=valkey_server, decode_responses=True)``) and
    model two uvicorn workers against one Valkey -- which is how the cross-worker
    pub/sub and shared-counter tests are written. Without an explicit server every
    ``FakeRedis()`` is its own isolated instance.
    """
    from fakeredis import FakeServer

    return FakeServer()


@pytest.fixture
def fake_redis(valkey_server: Any) -> Iterator[Any]:
    """A fresh in-memory Valkey for one test, decoding to ``str``.

    ``decode_responses=True`` matches ``app.redis_client.create_client``: the store
    reads hash fields as ``str``, and a bytes-decoding fake would pass tests the real
    client fails. The server is per-test, so state cannot leak between tests.
    """
    from fakeredis.aioredis import FakeRedis

    # Not closed: the fake holds no socket, and aclose() is a coroutine this sync
    # fixture has no loop to run.
    yield FakeRedis(server=valkey_server, decode_responses=True)


@pytest.fixture
def interleaving_redis(valkey_server: Any) -> Any:
    """A client over :func:`valkey_server` that yields to the event loop before each command.

    A plain ``FakeRedis`` answers a command without suspending, so coroutines under
    ``asyncio.gather`` run one after another and a check-then-write race never fires.
    This client suspends before each send, so every await on Redis is a point where
    another coroutine can run -- as it is against a real server. A pipeline or
    ``MULTI``/``EXEC`` is still one send, so it stays atomic. The connect handshake
    does not yield: a caller that opens a new pool connection would otherwise fall
    several commands behind one that reuses a connection, and the calls would not overlap.
    """
    from fakeredis.aioredis import FakeAsyncRedisConnection, FakeRedis

    class _YieldingConnection(FakeAsyncRedisConnection):
        _handshaking = False

        async def connect_check_health(self, *args: Any, **kwargs: Any) -> None:
            self._handshaking = True
            try:
                await super().connect_check_health(*args, **kwargs)
            finally:
                self._handshaking = False

        async def send_packed_command(self, *args: Any, **kwargs: Any) -> None:
            if not self._handshaking:
                await asyncio.sleep(0)
            await super().send_packed_command(*args, **kwargs)

    return FakeRedis(server=valkey_server, decode_responses=True, connection_class=_YieldingConnection)


@pytest.fixture
def session_store(fake_redis: Any) -> SessionStore:
    """The :class:`SessionStore` installed on ``app.state`` for this test."""
    return SessionStore(fake_redis)


@pytest.fixture
def event_bus(fake_redis: Any) -> Any:
    """The :class:`~app.services.events.EventBus` installed on ``app.state``."""
    from app.services.events import EventBus

    return EventBus(fake_redis)


@pytest.fixture(autouse=True)
def valkey_state(fake_redis: Any, session_store: SessionStore, event_bus: Any) -> Iterator[None]:
    """Install the Valkey-backed state objects on ``app.state`` for every test.

    ``app/main.py``'s lifespan builds these, but ``TestClient(app)`` used bare (as most
    of this suite does) never runs it -- so without this fixture ``get_redis`` and
    ``get_store`` would raise ``AttributeError`` on the first authenticated request.
    Autouse so a test only mentions these fixtures when it wants to inspect them.
    """
    from app.main import app

    app.state.redis = fake_redis
    app.state.session_store = session_store
    app.state.event_bus = event_bus
    yield
