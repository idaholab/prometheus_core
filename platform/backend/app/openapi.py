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

"""App-level OpenAPI metadata: the API overview and the tag catalog.

Documentation only -- nothing here affects routing or request handling. Served at
the FastAPI defaults: ``/docs`` (Swagger UI), ``/redoc`` and ``/openapi.json``.
Every tag a router uses must be listed in :data:`TAGS` so it gets a description
and a stable position in the docs.
"""

from __future__ import annotations

from typing import Any

API_TITLE = "Prometheus Backend"

# Hard-coded rather than read from package metadata: the image installs
# dependencies with --no-install-project, so there is no distribution to query.
API_VERSION = "0.1.0"

API_DESCRIPTION = """\
The JSON/SSE API behind the Prometheus Platform's React frontend. The backend
authenticates users, holds per-browser session state, relays chat turns to the
client-agent orchestrator, and streams progress back over Server-Sent Events.

## Authentication

Authentication is a session cookie (`prometheus_session` by default; the name is
configurable). It is an HttpOnly, `SameSite=Lax` JWT issued by a successful login
and sent automatically by the browser on every request. Routes that need it answer
`401` without a valid, unrevoked cookie; `/api/admin/*` routes additionally answer
`403` unless the user has the `admin` role.

Public routes: `/healthz`, `/.well-known/jwks.json`, `/api/setup/*`, and every
`/api/auth/*` route except `GET /api/auth/me`.

## Typical flow

1. **First run:** `GET /api/setup/status`; if not bootstrapped,
   `POST /api/setup/bootstrap` creates the first admin and logs them in.
2. **Log in:** `GET /api/auth/providers` lists the login options. Then either
   `POST /api/auth/login` (username and password), or follow the browser redirect
   from `GET /api/auth/login/{provider_id}` (OIDC).
3. **Start a conversation:** `POST /api/sessions` binds a new `conversation_id` to
   the session. The id lives server-side and is never sent in a request body.
4. **Open the event stream:** `GET /api/events` (one per browser session) for
   status updates and background-task progress.
5. **Chat:** `POST /api/chat/messages`, optionally attaching files staged with
   `POST /api/uploads`. Fetch artifacts with
   `GET /api/artifacts/{artifact_id}/content`.
6. **History:** `/api/conversations/*` lists, reopens, renames and deletes past
   conversations.

## Errors

Errors are JSON of the form `{"detail": "<message>"}`, and the message is meant to
be shown to the user. The exception is request validation performed by the
framework itself, which returns `422` with `detail` as a list of field errors.

A chat turn that fails while talking to the agent is **not** an HTTP error: it
returns `200` with `status: "error"` and a `message`, so the conversation can render
it inline.

## Wire contract

Every payload is defined by the Pydantic models in `app/contract.py` and explained,
with examples, in `CONTRACT.md` alongside this service.
"""

TAGS: list[dict[str, Any]] = [
    {"name": "health", "description": "Liveness probe for load balancers and orchestrators."},
    {
        "name": "identity",
        "description": (
            "Public signing keys (JWKS) that agents use to verify the short-lived identity "
            "tokens the backend mints for each chat turn."
        ),
    },
    {
        "name": "setup",
        "description": (
            "First-run bootstrap: check whether the platform has an admin yet and create the "
            "first one. Unauthenticated, and closed for good once any user exists."
        ),
    },
    {
        "name": "auth",
        "description": (
            "Log in with a username and password or an OIDC provider, log out, and identify "
            "the current user. Login sets the session cookie."
        ),
    },
    {
        "name": "config",
        "description": (
            "Settings the UI reads at startup: chat profiles, intro text, suggestions and the upload size limit."
        ),
    },
    {
        "name": "sessions",
        "description": "Start a new conversation and bind it to the browser session.",
    },
    {
        "name": "chat",
        "description": (
            "Send a chat turn to the agent orchestrator. Progress for the turn streams over `GET /api/events`."
        ),
    },
    {
        "name": "events",
        "description": (
            "The per-session Server-Sent Events stream: turn status updates and "
            "background-task progress and completion."
        ),
    },
    {"name": "uploads", "description": "Stage files to attach to the next chat turn."},
    {
        "name": "artifacts",
        "description": "Download artifact content produced by agents, and converted mesh files for the 3D viewer.",
    },
    {
        "name": "conversations",
        "description": "Conversation history: list recent conversations, reopen, resume, rename and delete them.",
    },
    {
        "name": "admin-users",
        "description": "Manage local user accounts and roles. Requires the `admin` role.",
    },
    {
        "name": "admin-oidc-providers",
        "description": "Configure the OIDC identity providers offered at login. Requires the `admin` role.",
    },
    {
        "name": "admin-signing-keys",
        "description": (
            "Create, activate and retire the RS256 keys that sign per-turn identity tokens. Requires the `admin` role."
        ),
    },
]
