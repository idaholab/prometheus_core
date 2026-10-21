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

"""Admin email-settings API: GET /api/admin/email-settings.

Behind require_admin like admin_oidc.py. The settings dependency is overridden
with a fixed EmailSettings, so no test reads the host's settings file.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
import yaml
from fastapi.testclient import TestClient

from app.email_settings import EmailSettings, get_email_settings, load_email_settings


def _client_as(monkeypatch, *, role: str, sid: str) -> TestClient:
    from app import security
    from app.main import app

    monkeypatch.setattr(security.settings, "jwt_secret", "test-secret", raising=False)
    token = security.issue_token(security.User(identifier=f"{role}-{sid}", role=role), sid=sid)
    client = TestClient(app)
    client.cookies.set("prometheus_session", token)
    return client


@pytest.fixture
def no_email_settings():
    from app.main import app

    state = EmailSettings(
        settings_file="/nonexistent/platform-settings.yml",
        file_present=False,
        default=None,
        error=None,
        configurations={},
        invalid={},
    )
    app.dependency_overrides[get_email_settings] = lambda: state
    try:
        yield state
    finally:
        app.dependency_overrides.pop(get_email_settings, None)


# --------------------------------------------------------------------------- #
# require_admin gate
# --------------------------------------------------------------------------- #


def test_admin_email_settings_requires_admin_unauthenticated_gets_401(wire_db_session, no_email_settings):
    """GET /api/admin/email-settings MUST return 401 without a session."""
    from app.main import app

    assert TestClient(app).get("/api/admin/email-settings").status_code == 401


def test_admin_email_settings_requires_admin_non_admin_gets_403(monkeypatch, wire_db_session, no_email_settings):
    """GET /api/admin/email-settings MUST return 403 for a non-admin session."""
    client = _client_as(monkeypatch, role="user", sid="s-email-nonadmin")
    assert client.get("/api/admin/email-settings").status_code == 403


def test_admin_email_settings_requires_admin_admin_gets_200(monkeypatch, wire_db_session, no_email_settings):
    """An admin session passes the require_admin gate and reads the loaded settings."""
    client = _client_as(monkeypatch, role="admin", sid="s-email-admin")
    resp = client.get("/api/admin/email-settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["file_present"] is False
    assert body["settings_file"] == no_email_settings.settings_file
    assert body["configurations"] == []


# --------------------------------------------------------------------------- #
# redaction and response shape
# --------------------------------------------------------------------------- #

_CONFIGURATION_KEYS = {
    "name",
    "is_default",
    "valid",
    "error",
    "host",
    "port",
    "security",
    "verify_tls",
    "ca_bundle",
    "username",
    "from_address",
    "from_name",
    "has_password",
    "password_env",
}


@pytest.fixture
def override_email_settings():
    from app.main import app

    def _override(state: EmailSettings) -> None:
        app.dependency_overrides[get_email_settings] = lambda: state

    try:
        yield _override
    finally:
        app.dependency_overrides.pop(get_email_settings, None)


def _keys_at_any_depth(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys_at_any_depth(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys_at_any_depth(v) for v in value))
    return set()


def test_admin_email_settings_redacts_passwords_and_lists_every_configuration(
    monkeypatch, tmp_path, wire_db_session, override_email_settings
):
    """GET /api/admin/email-settings MUST return every loaded and invalid configuration with
    has_password and password_env, and MUST NOT return any password value."""
    path = tmp_path / "platform-settings.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "smtp": {
                    "default": "relay",
                    "configurations": {
                        "relay": {
                            "host": "mailrelay.example.com",
                            "port": 587,
                            "security": "starttls",
                            "from_address": "prometheus@example.com",
                            "from_name": "Prometheus",
                            "username": "prometheus",
                            "password": "os.environ/SMTP_RELAY_PASSWORD",
                        },
                        "other": {
                            "host": "smtp.example.com",
                            "from_address": "other@example.com",
                            "password": "os.environ/SMTP_OTHER_PASSWORD",
                        },
                    },
                }
            }
        )
    )
    override_email_settings(load_email_settings(str(path), env={"SMTP_RELAY_PASSWORD": "s3cret-smtp"}))

    client = _client_as(monkeypatch, role="admin", sid="s-email-redacts")
    resp = client.get("/api/admin/email-settings")

    assert resp.status_code == 200
    assert "s3cret-smtp" not in resp.text
    body = resp.json()
    assert "password" not in _keys_at_any_depth(body)
    assert set(body) == {"configured", "settings_file", "file_present", "default", "error", "configurations"}
    assert body["configured"] is True
    assert body["settings_file"] == str(path)
    assert body["file_present"] is True
    assert body["default"] == "relay"
    assert body["error"] is None
    assert [c["name"] for c in body["configurations"]] == ["other", "relay"]
    for configuration in body["configurations"]:
        assert set(configuration) == _CONFIGURATION_KEYS
    other, relay = body["configurations"]
    assert relay == {
        "name": "relay",
        "is_default": True,
        "valid": True,
        "error": None,
        "host": "mailrelay.example.com",
        "port": 587,
        "security": "starttls",
        "verify_tls": True,
        "ca_bundle": None,
        "username": "prometheus",
        "from_address": "prometheus@example.com",
        "from_name": "Prometheus",
        "has_password": True,
        "password_env": "SMTP_RELAY_PASSWORD",
    }
    assert other == {
        "name": "other",
        "is_default": False,
        "valid": False,
        "error": "SMTP_OTHER_PASSWORD is not set",
        "host": None,
        "port": None,
        "security": None,
        "verify_tls": None,
        "ca_bundle": None,
        "username": None,
        "from_address": None,
        "from_name": None,
        "has_password": False,
        "password_env": "SMTP_OTHER_PASSWORD",
    }


def test_admin_email_settings_redacts_with_no_file_returns_no_configurations(
    monkeypatch, tmp_path, wire_db_session, override_email_settings
):
    """With no settings file, the route returns 200 with configured false and no configurations."""
    path = tmp_path / "absent.yml"
    override_email_settings(load_email_settings(str(path), env={}))

    client = _client_as(monkeypatch, role="admin", sid="s-email-nofile")
    resp = client.get("/api/admin/email-settings")

    assert resp.status_code == 200
    assert resp.json() == {
        "configured": False,
        "settings_file": str(path),
        "file_present": False,
        "default": None,
        "error": None,
        "configurations": [],
    }


# --------------------------------------------------------------------------- #
# startup summary log
# --------------------------------------------------------------------------- #


def test_startup_logs_email_summary_at_info_on_a_uvicorn_logger(monkeypatch, tmp_path, caplog):
    """At backend startup the lifespan MUST log one INFO summary line `email: <n> configurations,
    default <name>, <k> invalid` on a logger that uvicorn's default log config shows at INFO, plus
    one WARNING per invalid configuration, and MUST NOT log a password value."""
    from uvicorn.config import LOGGING_CONFIG

    from app import main as app_main
    from app.config import settings

    path = tmp_path / "platform-settings.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "smtp": {
                    "default": "relay",
                    "configurations": {
                        "relay": {
                            "host": "mailrelay.example.com",
                            "from_address": "prometheus@example.com",
                            "password": "os.environ/SMTP_PASSWORD",
                        },
                        "other": {
                            "host": "smtp.example.com",
                            "from_address": "other@example.com",
                            "password": "os.environ/SMTP_OTHER_PASSWORD",
                        },
                    },
                }
            }
        )
    )
    state = load_email_settings(str(path), env={"SMTP_PASSWORD": "s3cret-smtp"})
    monkeypatch.setattr(app_main, "get_email_settings", lambda: state)
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32, raising=False)

    async def run() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    with caplog.at_level(logging.INFO):
        asyncio.run(run())

    summaries = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and r.getMessage() == "email: 1 configurations, default relay, 1 invalid"
    ]
    assert len(summaries) == 1
    name = summaries[0].name
    assert name == "uvicorn.error" or name.startswith("uvicorn.error."), name
    # uvicorn's default config shows uvicorn.error at INFO.
    assert LOGGING_CONFIG["loggers"]["uvicorn.error"]["level"] == "INFO"
    assert any(
        r.levelno == logging.WARNING and "configuration other is invalid" in r.getMessage() for r in caplog.records
    )
    assert not any("s3cret-smtp" in r.getMessage() for r in caplog.records)
