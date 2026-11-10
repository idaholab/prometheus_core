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

"""Unit tests for prometheus_api.credentials."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from prometheus_api.credentials.broker import (
    Credential,
    CredentialError,
    CredentialRequest,
)
from prometheus_api.credentials.env_broker import EnvCredentialBroker
from prometheus_api.credentials.factory import get_broker, _create_broker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_TOKEN = "fake.user.token"


@pytest.fixture(autouse=True)
def clear_broker_singleton():
    """Reset the module-level broker singleton between tests."""
    import prometheus_api.credentials.factory as fac

    original = fac._broker
    fac._broker = None
    yield
    fac._broker = original


# ---------------------------------------------------------------------------
# EnvCredentialBroker — DeepLynx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_broker_deeplynx_jwt(monkeypatch):
    monkeypatch.setenv("DEEPLYNX_JWT_TOKEN", "dl-token-123")
    monkeypatch.setenv("DEEPLYNX_ORG_ID", "org-1")
    monkeypatch.setenv("DEEPLYNX_PROJECT_ID", "proj-1")
    broker = EnvCredentialBroker()
    cred = await broker.get_credential(
        CredentialRequest(user_id="alice", resource="deeplynx"),
        user_token=USER_TOKEN,
    )
    assert cred.resource == "deeplynx"
    assert cred.value["jwt_token"] == "dl-token-123"
    assert cred.value["org_id"] == "org-1"
    assert cred.value["project_id"] == "proj-1"


@pytest.mark.asyncio
async def test_env_broker_deeplynx_key_secret(monkeypatch):
    monkeypatch.delenv("DEEPLYNX_JWT_TOKEN", raising=False)
    monkeypatch.setenv("DEEPLYNX_KEY", "my-key")
    monkeypatch.setenv("DEEPLYNX_SECRET", "my-secret")
    broker = EnvCredentialBroker()
    cred = await broker.get_credential(
        CredentialRequest(user_id="bob", resource="deeplynx"),
        user_token=USER_TOKEN,
    )
    assert cred.value["key"] == "my-key"
    assert cred.value["secret"] == "my-secret"


@pytest.mark.asyncio
async def test_env_broker_deeplynx_missing_creds_raises(monkeypatch):
    monkeypatch.delenv("DEEPLYNX_JWT_TOKEN", raising=False)
    monkeypatch.delenv("DEEPLYNX_KEY", raising=False)
    monkeypatch.delenv("DEEPLYNX_SECRET", raising=False)
    broker = EnvCredentialBroker()
    with pytest.raises(CredentialError, match="DeepLynx credentials not configured"):
        await broker.get_credential(
            CredentialRequest(user_id="carol", resource="deeplynx"),
            user_token=USER_TOKEN,
        )


# ---------------------------------------------------------------------------
# EnvCredentialBroker — SLURM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_broker_slurm(monkeypatch):
    monkeypatch.setenv("SLURM_JWT_TOKEN", "slurm-tok-xyz")
    monkeypatch.setenv("SLURM_USER", "dave")
    monkeypatch.setenv("SLURM_REST_URL", "http://slurm.hpc/slurm/v0.0.40")
    broker = EnvCredentialBroker()
    cred = await broker.get_credential(
        CredentialRequest(user_id="dave", resource="slurm"),
        user_token=USER_TOKEN,
    )
    assert cred.resource == "slurm"
    assert cred.value["token"] == "slurm-tok-xyz"
    assert cred.value["user"] == "dave"


@pytest.mark.asyncio
async def test_env_broker_slurm_missing_token_raises(monkeypatch):
    monkeypatch.delenv("SLURM_JWT_TOKEN", raising=False)
    broker = EnvCredentialBroker()
    with pytest.raises(CredentialError, match="SLURM_JWT_TOKEN"):
        await broker.get_credential(
            CredentialRequest(user_id="eve", resource="slurm"),
            user_token=USER_TOKEN,
        )


# ---------------------------------------------------------------------------
# EnvCredentialBroker — user_token not validated (env mode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_broker_ignores_user_token(monkeypatch):
    """EnvCredentialBroker does not verify the user_token (dev mode)."""
    monkeypatch.setenv("DEEPLYNX_JWT_TOKEN", "dl-tok")
    broker = EnvCredentialBroker()
    # Works even with an empty token
    cred = await broker.get_credential(
        CredentialRequest(user_id="frank", resource="deeplynx"),
        user_token="",
    )
    assert cred.resource == "deeplynx"


# ---------------------------------------------------------------------------
# EnvCredentialBroker — unknown resource falls back gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_broker_unknown_resource_returns_empty():
    broker = EnvCredentialBroker()
    cred = await broker.get_credential(
        CredentialRequest(user_id="grace", resource="unknown-resource"),
        user_token=USER_TOKEN,
    )
    assert cred.resource == "unknown-resource"
    assert cred.value == {}


# ---------------------------------------------------------------------------
# Credential.expires_at is in the future for env broker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_broker_credential_expires_in_future(monkeypatch):
    monkeypatch.setenv("DEEPLYNX_JWT_TOKEN", "tok")
    broker = EnvCredentialBroker()
    cred = await broker.get_credential(
        CredentialRequest(user_id="harry", resource="deeplynx"),
        user_token=USER_TOKEN,
    )
    assert cred.expires_at > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# factory.get_broker
# ---------------------------------------------------------------------------


def test_get_broker_returns_env_broker_by_default(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_BROKER", raising=False)
    broker = get_broker()
    from prometheus_api.credentials.env_broker import EnvCredentialBroker

    assert isinstance(broker, EnvCredentialBroker)


def test_get_broker_returns_env_broker_explicitly(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_BROKER", "env")
    broker = _create_broker()
    from prometheus_api.credentials.env_broker import EnvCredentialBroker

    assert isinstance(broker, EnvCredentialBroker)


def test_get_broker_returns_vault_broker(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_BROKER", "vault")
    broker = _create_broker()
    from prometheus_api.credentials.vault_broker import VaultCredentialBroker

    assert isinstance(broker, VaultCredentialBroker)


def test_get_broker_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_BROKER", "nonsense")
    with pytest.raises(CredentialError, match="Unknown CREDENTIAL_BROKER"):
        _create_broker()


def test_get_broker_is_singleton():
    b1 = get_broker()
    b2 = get_broker()
    assert b1 is b2


# ---------------------------------------------------------------------------
# CredentialRequest is frozen
# ---------------------------------------------------------------------------


def test_credential_request_frozen():
    req = CredentialRequest(user_id="ivan", resource="deeplynx")
    with pytest.raises((AttributeError, TypeError)):
        req.user_id = "injected"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConnectionConfig.from_credential
# ---------------------------------------------------------------------------


def test_connection_config_from_credential(monkeypatch):
    monkeypatch.setenv("DEEPLYNX_ORG_ID", "42")
    monkeypatch.setenv("DEEPLYNX_PROJECT_ID", "7")

    cred = Credential(
        resource="deeplynx",
        value={"jwt_token": "tok-abc"},
        expires_at=datetime.now(timezone.utc),
    )
    from prometheus_api.storage_client.connection import ConnectionConfig

    config = ConnectionConfig.from_credential(cred)
    assert config.jwt_token == "tok-abc"
    assert config.organization_id == 42
    assert config.project_id == 7


def test_connection_config_from_credential_overrides_env(monkeypatch):
    monkeypatch.setenv("DEEPLYNX_ORG_ID", "1")
    monkeypatch.setenv("DEEPLYNX_PROJECT_ID", "2")

    cred = Credential(
        resource="deeplynx",
        value={"jwt_token": "tok-xyz", "org_id": "100", "project_id": "200"},
        expires_at=datetime.now(timezone.utc),
    )
    from prometheus_api.storage_client.connection import ConnectionConfig

    config = ConnectionConfig.from_credential(cred)
    # Credential value takes precedence over env for org/project
    assert config.organization_id == 100
    assert config.project_id == 200


def test_connection_config_from_credential_explicit_override(monkeypatch):
    monkeypatch.setenv("DEEPLYNX_ORG_ID", "1")
    monkeypatch.setenv("DEEPLYNX_PROJECT_ID", "2")

    cred = Credential(
        resource="deeplynx",
        value={"jwt_token": "tok", "org_id": "99"},
        expires_at=datetime.now(timezone.utc),
    )
    from prometheus_api.storage_client.connection import ConnectionConfig

    config = ConnectionConfig.from_credential(cred, organization_id=999)
    # Explicit argument takes precedence over credential value
    assert config.organization_id == 999
