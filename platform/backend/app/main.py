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

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.crypto import EncryptionError
from app.db import get_session_factory
from app.openapi import API_DESCRIPTION, API_TITLE, API_VERSION, TAGS
from app.routers import (
    admin_keys,
    admin_oidc,
    admin_users,
    artifacts,
    auth,
    chat,
    config,
    conversations,
    events,
    health,
    jwks,
    sessions,
    setup,
    uploads,
)
from app import redis_client, security
from app.services.events import EventBus
from app.services.mesh.service import shutdown_mesh_executor
from app.sessions import SessionStore
from app.signing_keys import ensure_active_signing_key


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast on a misconfigured deploy: without a signing secret, issue_token
    # would raise a 500 on the first login rather than here. Crash on boot with an
    # actionable message instead. (Bare TestClient(app) does not run the lifespan,
    # so this never trips in the test suite.)
    if not settings.jwt_secret or settings.jwt_secret.startswith("change-me"):
        raise RuntimeError(
            "jwt_secret is not configured: set BACKEND_JWT_SECRET in .env to a generated "
            "value, not the .env.example placeholder (forwarded to the container in "
            "docker-compose.yml). If this deploy predates the Chainlit excision, copy "
            "the value from the retired CHAINLIT_AUTH_SECRET -- it is no longer accepted "
            "as a fallback. Refusing to start with an empty or placeholder signing key."
        )
    # Schema migrations are NOT run here. `alembic upgrade head` is a deploy step,
    # executed once by docker-entrypoint.sh before uvicorn starts -- running it in
    # the lifespan meant every `--workers N` process migrated the same database
    # concurrently. See backend/README.md ("Migrations run before the app").
    #
    # Every already-configured OIDC provider becomes resolvable via
    # security.get_provider() before the first request -- routers/admin_oidc.py
    # keeps this in sync afterward (create registers, delete unregisters; an
    # update needs no registry change, see GenericOidcProvider's docstring).
    session_factory = get_session_factory()
    async with session_factory() as db:
        await security.register_existing_oidc_providers(db)
        # A fresh install gets one active RS256 identity key, so mint_for_user()
        # works before an admin visits Admin > Signing Keys. See app/signing_keys.py.
        await ensure_active_signing_key(db)
    # One async Valkey client (a connection pool) shared by every subsystem that
    # needs one: sessions, the SSE event bus, session revocation and task events.
    # See app/redis_client.py.
    app.state.redis = redis_client.create_client()
    # Session state lives in Valkey (`session:{sid}`), so it survives a restart and
    # is consistent across workers. See app/sessions.py.
    app.state.session_store = SessionStore(app.state.redis)
    # SSE fan-out over Valkey pub/sub (`sse:{sid}`): routers/chat.py publishes,
    # routers/events.py drains a local queue fed by a per-sid relay. Publishing
    # through Valkey is what lets a tab on worker A see a turn running on worker B.
    app.state.event_bus = EventBus(app.state.redis)
    try:
        yield
    finally:
        # The VTK conversion pool is built lazily on first use, so this is a no-op on a
        # server that never converted a mesh. When it did, spawned workers would
        # otherwise outlive the server on a graceful stop and hold the container open
        # until Docker's kill timeout.
        shutdown_mesh_executor()
        await app.state.redis.aclose()


app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
)

# CORS for local dev only; in prod the frontend is served same-origin behind nginx.
# Explicit origins, not "*", because credentialed requests can't use a wildcard
# Access-Control-Allow-Origin (AU-9). Configure via BACKEND_DEV_ORIGINS.
if settings.debug:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dev_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(EncryptionError)
async def _encryption_error_handler(request: Request, exc: EncryptionError) -> JSONResponse:
    """ADMIN_DB_ENCRYPTION_KEY missing/invalid, or a row encrypted under a
    since-rotated key (app/crypto.py) -- a deployment misconfiguration, not a
    client error, but one an admin can act on immediately if the message
    actually reaches them. Without this handler these routes' encrypt()/
    decrypt() calls (admin_keys.py, admin_oidc.py) 500 with a bare,
    JSON-less "Internal Server Error" body -- the frontend's ApiError can't
    extract any detail from that, so this exact message is what shows up in
    the UI instead of a dead end.
    """
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(jwks.router)
app.include_router(setup.router)
app.include_router(auth.router)
app.include_router(config.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(events.router)
app.include_router(uploads.router)
app.include_router(artifacts.router)
app.include_router(conversations.router)
app.include_router(admin_users.router)
app.include_router(admin_keys.router)
app.include_router(admin_oidc.router)
