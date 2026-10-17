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

"""Encrypt-at-rest for admin-plane secrets: OIDC client secrets and RS256
private signing keys stored in Postgres.

Distinct from every other secret in this codebase: ``BACKEND_JWT_SECRET``
signs the session cookie, ``USER_IDENTITY_PRIVATE_KEY`` signs the identity
JWT -- this key (``ADMIN_DB_ENCRYPTION_KEY``) encrypts *other* secrets before
they're written to ``admin-db``, so a database dump or a read-only SQL
console alone can't recover them.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class EncryptionError(Exception):
    """Raised when ADMIN_DB_ENCRYPTION_KEY is unconfigured or a value fails to decrypt."""


def _fernet() -> Fernet:
    if not settings.admin_db_encryption_key:
        raise EncryptionError(
            "ADMIN_DB_ENCRYPTION_KEY is not configured. Generate one with: "
            'python3 -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(settings.admin_db_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionError(f"ADMIN_DB_ENCRYPTION_KEY is not a valid Fernet key: {exc}") from exc


def ensure_configured() -> None:
    """Raise :class:`EncryptionError` now if ADMIN_DB_ENCRYPTION_KEY is missing or invalid."""
    _fernet()


def encrypt(plaintext: str) -> bytes:
    """Encrypt a secret for storage in an admin-plane table column."""
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt a value previously produced by :func:`encrypt`.

    Raises:
        EncryptionError: if the key is unconfigured, or *ciphertext* was
            encrypted under a different key (e.g. after key rotation without
            re-encrypting existing rows).
    """
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as exc:
        raise EncryptionError(
            "Could not decrypt value -- ADMIN_DB_ENCRYPTION_KEY may have changed since this row was written."
        ) from exc
