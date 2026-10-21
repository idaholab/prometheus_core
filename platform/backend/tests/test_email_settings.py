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

"""The ``smtp`` section of the platform settings file.

``load_email_settings`` MUST load every valid configuration of the ``smtp`` section with
its defaults, and MUST mark a configuration invalid, with an error that names the field,
when a field breaks the rule table.
"""

import pytest
import yaml

from app.config import settings
from app.email_settings import get_email_settings, load_email_settings


def _relay(**overrides):
    config = {"host": "mailrelay.example.org", "from_address": "prometheus@example.org"}
    config.update(overrides)
    return config


def _write(tmp_path, smtp):
    path = tmp_path / "platform-settings.yml"
    path.write_text(yaml.safe_dump({"smtp": smtp}))
    return str(path)


# --------------------------------------------------------------------------- #
# Schema: valid configurations, defaults, per-configuration errors
# --------------------------------------------------------------------------- #


def test_two_valid_configurations_load_with_their_defaults(tmp_path):
    path = _write(
        tmp_path,
        {
            "default": "relay",
            "configurations": {
                "relay": _relay(),
                "mailpit": {"host": "mailpit", "port": 1025, "security": "none", "from_address": "dev@example.org"},
            },
        },
    )

    loaded = load_email_settings(path, env={})

    assert loaded.error is None
    assert loaded.invalid == {}
    assert set(loaded.configurations) == {"relay", "mailpit"}
    relay = loaded.configurations["relay"].config
    assert relay.port == 587
    assert relay.security == "starttls"
    mailpit = loaded.configurations["mailpit"].config
    assert mailpit.port == 1025
    assert mailpit.security == "none"
    assert loaded.configured is True


@pytest.mark.parametrize(
    ("name", "config", "field"),
    [
        pytest.param("bad", _relay(port=0), "port", id="port-zero"),
        pytest.param("bad", _relay(port=70000), "port", id="port-too-large"),
        pytest.param("bad", _relay(security="tls"), "security", id="security-tls"),
        pytest.param("bad", _relay(from_address="not-an-email"), "from_address", id="from-address-not-email"),
        pytest.param("bad", _relay(tls=True), "tls", id="unknown-key"),
        pytest.param("Bad_Name", _relay(), "configuration name", id="bad-name"),
    ],
)
def test_bad_field_marks_only_that_configuration_invalid(tmp_path, name, config, field):
    path = _write(tmp_path, {"default": "good", "configurations": {"good": _relay(), name: config}})

    loaded = load_email_settings(path, env={})

    assert name in loaded.invalid
    assert name not in loaded.configurations
    error, _password_env = loaded.invalid[name]
    assert field in error
    assert set(loaded.configurations) == {"good"}
    assert loaded.configured is True


@pytest.mark.parametrize(
    "smtp",
    [
        pytest.param({"configurations": {"a": _relay(), "b": _relay()}}, id="default-omitted-with-two"),
        pytest.param({"default": "nope", "configurations": {"a": _relay(), "b": _relay()}}, id="default-unknown"),
    ],
)
def test_unresolved_default_leaves_email_unconfigured_with_an_error(tmp_path, smtp):
    loaded = load_email_settings(_write(tmp_path, smtp), env={})

    assert loaded.configured is False
    assert loaded.error
    assert "smtp.default" in loaded.error


# --------------------------------------------------------------------------- #
# Password: an allow-listed os.environ/ reference, resolved at load, never shown
# --------------------------------------------------------------------------- #


def test_password_reference_resolves_from_the_environment_and_stays_out_of_repr(tmp_path):
    """A configuration password MUST be an ``os.environ/`` reference to ``SMTP_PASSWORD`` or
    ``SMTP_<NAME>_PASSWORD``, MUST resolve from the environment at load, and MUST NOT appear
    in a ``repr``."""
    path = _write(tmp_path, {"configurations": {"relay": _relay(password="os.environ/SMTP_RELAY_PASSWORD")}})

    state = load_email_settings(path, env={"SMTP_RELAY_PASSWORD": "s3cret-smtp"})

    relay = state.configurations["relay"]
    assert relay.password is not None
    assert relay.password.get_secret_value() == "s3cret-smtp"
    assert relay.password_env == "SMTP_RELAY_PASSWORD"
    assert state.configured is True
    assert "s3cret-smtp" not in repr(state)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("hunter2", id="literal"),
        pytest.param("os.environ/BACKEND_JWT_SECRET", id="not-an-smtp-variable"),
    ],
)
def test_password_that_is_not_an_allowed_reference_marks_the_configuration_invalid(tmp_path, password):
    """A configuration password MUST be an ``os.environ/`` reference to ``SMTP_PASSWORD`` or
    ``SMTP_<NAME>_PASSWORD`` and MUST NOT appear in an error message."""
    path = _write(tmp_path, {"configurations": {"relay": _relay(password=password)}})

    state = load_email_settings(path, env={"BACKEND_JWT_SECRET": "jwt-signing-value"})

    assert "relay" not in state.configurations
    error, _password_env = state.invalid["relay"]
    assert "password" in error
    assert "hunter2" not in error
    assert "jwt-signing-value" not in repr(state)
    assert state.configured is False


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="unset"),
        pytest.param({"SMTP_RELAY_PASSWORD": ""}, id="empty"),
    ],
)
def test_password_reference_to_an_unset_variable_marks_the_configuration_invalid(tmp_path, env):
    """A configuration password MUST resolve from the environment at load."""
    path = _write(tmp_path, {"configurations": {"relay": _relay(password="os.environ/SMTP_RELAY_PASSWORD")}})

    state = load_email_settings(path, env=env)

    assert "relay" not in state.configurations
    assert state.invalid["relay"] == ("SMTP_RELAY_PASSWORD is not set", "SMTP_RELAY_PASSWORD")
    assert state.configured is False


# --------------------------------------------------------------------------- #
# Missing or bad file: loading never raises
# --------------------------------------------------------------------------- #


@pytest.fixture
def clear_email_settings_cache():
    get_email_settings.cache_clear()
    yield
    get_email_settings.cache_clear()


def test_missing_file_turns_email_off_without_an_error(tmp_path):
    """``load_email_settings`` MUST NOT raise for a missing file, and returns no ``error`` for it."""
    state = load_email_settings(str(tmp_path / "absent.yml"), env={})

    assert state.file_present is False
    assert state.error is None
    assert state.configured is False


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("smtp: [\n", "not valid YAML", id="invalid-yaml"),
        pytest.param("- a\n", "must be a YAML mapping", id="not-a-mapping"),
    ],
)
def test_bad_file_turns_email_off_with_an_error(tmp_path, content, expected):
    """``load_email_settings`` MUST NOT raise for invalid YAML or a non-mapping file, and MUST
    return ``configured`` false with an ``error``."""
    path = tmp_path / "platform-settings.yml"
    path.write_text(content)

    state = load_email_settings(str(path), env={})

    assert state.file_present is True
    assert state.configured is False
    assert state.error is not None
    assert expected in state.error


def test_file_without_smtp_section_turns_email_off_without_an_error(tmp_path):
    """``load_email_settings`` MUST NOT raise for a missing ``smtp`` section, and returns no
    ``error`` for it."""
    path = tmp_path / "platform-settings.yml"
    path.write_text("other: 1\n")

    state = load_email_settings(str(path), env={})

    assert state.file_present is True
    assert state.configured is False
    assert state.error is None


def test_get_email_settings_does_not_raise_for_a_bad_file(tmp_path, monkeypatch, clear_email_settings_cache):
    """``get_email_settings`` reads the configured path and MUST NOT raise for a bad file."""
    path = tmp_path / "platform-settings.yml"
    path.write_text("smtp: [\n")
    monkeypatch.setattr(settings, "platform_settings_path", str(path))

    state = get_email_settings()

    assert state.settings_file == str(path)
    assert state.configured is False
    assert state.error is not None
    assert "not valid YAML" in state.error


# --------------------------------------------------------------------------- #
# The committed example file
# --------------------------------------------------------------------------- #


def test_example_settings_file_loads_without_errors():
    """The committed ``platform/settings/platform-settings.example.yml`` MUST load with no error
    and no invalid configuration when its password variables are set."""
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent.parent / "settings" / "platform-settings.example.yml"

    state = load_email_settings(str(example), env={"SMTP_MAILPIT_PASSWORD": "x"})

    assert state.file_present is True
    assert state.error is None
    assert state.invalid == {}
    assert state.configured is True
