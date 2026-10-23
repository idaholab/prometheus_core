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

"""Reusable OpenAPI ``responses=`` entries for the backend's error cases.

Documentation only: passing these to ``APIRouter(responses=...)`` or a route
decorator changes what ``/docs`` shows, never what a handler returns. Each entry
lists the exact ``detail`` strings the code raises as named examples, so a client
author can match on them -- keep them in sync with the ``HTTPException`` calls they
describe (the auth ones live in ``app/security.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi import status
from pydantic import BaseModel, Field

Responses = dict[int | str, dict[str, Any]]


class ErrorResponse(BaseModel):
    """Body of every error the backend raises itself."""

    detail: str = Field(description="Human-readable explanation, suitable for showing to the user.")


def error(status_code: int, description: str, *details: str) -> Responses:
    """One documented error status with an example per possible ``detail`` message."""
    content: dict[str, Any] = {}
    if details:
        content["application/json"] = {
            "examples": {
                f"example_{i}": {"summary": detail, "value": {"detail": detail}} for i, detail in enumerate(details, 1)
            }
        }
    return {status_code: {"model": ErrorResponse, "description": description, "content": content}}


# Raised by app.security.current_claims, and so by every route that depends on it
# (directly, or through current_user / require_admin).
AUTH_RESPONSES: Responses = error(
    status.HTTP_401_UNAUTHORIZED,
    "No valid session: the session cookie is missing, invalid or expired, or the session was logged out.",
    "Not authenticated",
    "Invalid or expired session",
    "Session has been logged out",
)

# app.security.require_admin, applied router-wide to every /api/admin/* router.
ADMIN_RESPONSES: Responses = {
    **AUTH_RESPONSES,
    **error(status.HTTP_403_FORBIDDEN, "The signed-in user does not have the `admin` role.", "Admin role required"),
}

# app.main's EncryptionError handler. Attach only to routes whose code path encrypts or
# decrypts an admin-plane secret without catching the error: signing-key creation, OIDC
# provider create/update (client secret) and the OIDC callback (token exchange).
# identity.mint_for_user also decrypts, but swallows the error, so chat and uploads
# never surface it.
ENCRYPTION_RESPONSES: Responses = error(
    status.HTTP_500_INTERNAL_SERVER_ERROR,
    "The server's admin-plane encryption key (`ADMIN_DB_ENCRYPTION_KEY`) is missing or invalid, or a stored "
    "secret was encrypted under a different key. A deployment problem for an administrator to fix; the "
    "`detail` says which.",
    "ADMIN_DB_ENCRYPTION_KEY is not configured. Generate one with: ...",
    "ADMIN_DB_ENCRYPTION_KEY is not a valid Fernet key: ...",
    "Could not decrypt value -- ADMIN_DB_ENCRYPTION_KEY may have changed since this row was written.",
)
