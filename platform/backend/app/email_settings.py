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

"""SMTP configurations from the optional platform settings file.

The file (``settings.platform_settings_path``) is a YAML mapping; this module reads only
its ``smtp`` section. A password is never stored in the file: a configuration names an
environment variable as ``password: os.environ/SMTP_<NAME>_PASSWORD``, and the value is
resolved at load into a ``SecretStr``. Loading never raises -- a missing or bad file, or
a bad configuration, turns email off (or skips that configuration) and records why.
"""

import functools
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, ValidationError

from app.config import settings

PASSWORD_ENV_RE = re.compile(r"^SMTP_([A-Z0-9]+_)*PASSWORD$")
CONFIGURATION_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
ENV_REFERENCE_PREFIX = "os.environ/"
SMTP_KEYS = frozenset({"default", "configurations"})


class SmtpConfiguration(BaseModel):
    """One named SMTP configuration, as written in the settings file."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255, pattern=r"^\S+$")
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["none", "starttls", "ssl"] = "starttls"
    from_address: EmailStr
    from_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    # The raw "os.environ/NAME" reference only, never a password value.
    password: str | None = None
    verify_tls: bool = True
    ca_bundle: str | None = Field(default=None, max_length=512)


@dataclass(frozen=True)
class LoadedSmtpConfiguration:
    name: str
    config: SmtpConfiguration
    password_env: str | None
    # Resolved from the environment at load.
    password: SecretStr | None


@dataclass(frozen=True)
class EmailSettings:
    settings_file: str
    file_present: bool
    default: str | None
    error: str | None
    configurations: dict[str, LoadedSmtpConfiguration]
    # name -> (error, password_env)
    invalid: dict[str, tuple[str, str | None]]

    @property
    def configured(self) -> bool:
        return self.default is not None and self.default in self.configurations

    def default_configuration(self) -> LoadedSmtpConfiguration | None:
        if self.default is None:
            return None
        return self.configurations.get(self.default)


def _off(path: str, file_present: bool, error: str | None) -> EmailSettings:
    return EmailSettings(
        settings_file=path,
        file_present=file_present,
        default=None,
        error=error,
        configurations={},
        invalid={},
    )


def _validation_error_text(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors(include_url=False, include_input=False, include_context=False):
        field = ".".join(str(loc) for loc in err["loc"]) or "configuration"
        parts.append(f"{field}: {err['msg']}")
    return "; ".join(parts)


def _password_env(reference: str) -> str | None:
    """The variable name of an allowed ``os.environ/NAME`` reference, else ``None``."""
    if not reference.startswith(ENV_REFERENCE_PREFIX):
        return None
    env_name = reference[len(ENV_REFERENCE_PREFIX) :]
    return env_name if PASSWORD_ENV_RE.match(env_name) else None


def _load_configuration(
    name: str, raw: Any, source: Mapping[str, str]
) -> LoadedSmtpConfiguration | tuple[str, str | None]:
    """One loaded configuration, or its ``(error, password_env)`` when it is invalid."""
    if not CONFIGURATION_NAME_RE.match(name):
        return ("configuration name must be 1-64 characters of a-z, 0-9 and -", None)
    try:
        config = SmtpConfiguration.model_validate(raw)
    except ValidationError as exc:
        return (_validation_error_text(exc), None)
    if config.password is None:
        return LoadedSmtpConfiguration(name=name, config=config, password_env=None, password=None)
    env_name = _password_env(config.password)
    if env_name is None:
        return (
            "password: must be os.environ/SMTP_PASSWORD or os.environ/SMTP_<NAME>_PASSWORD",
            None,
        )
    value = source.get(env_name)
    if not value:
        return (f"{env_name} is not set", env_name)
    return LoadedSmtpConfiguration(name=name, config=config, password_env=env_name, password=SecretStr(value))


def _read_settings_file(path: str) -> tuple[bool, Any, str | None]:
    """``(file_present, data, error)`` for the settings file; never raises."""
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return True, data, None
    except FileNotFoundError:
        return False, None, None
    except yaml.YAMLError as exc:
        # The YAML error text quotes the offending line, so name only its position.
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark is not None else ""
        return True, None, f"settings file is not valid YAML{where}"
    except (OSError, UnicodeDecodeError) as exc:
        return True, None, f"settings file cannot be read: {type(exc).__name__}"


def load_email_settings(path: str, env: Mapping[str, str] | None = None) -> EmailSettings:
    """Load the ``smtp`` section of the settings file at ``path``; never raises."""
    source = os.environ if env is None else env
    file_present, data, error = _read_settings_file(path)
    if error is not None or not file_present:
        return _off(path, file_present, error)
    if not isinstance(data, dict):
        return _off(path, True, "settings file must be a YAML mapping")
    smtp = data.get("smtp")
    if smtp is None:
        return _off(path, True, None)
    if not isinstance(smtp, dict):
        return _off(path, True, "smtp must be a mapping")
    unknown = sorted(str(key) for key in smtp if key not in SMTP_KEYS)
    if unknown:
        return _off(path, True, f"smtp has unknown keys: {', '.join(unknown)}")
    raw_configurations = smtp.get("configurations")
    if not isinstance(raw_configurations, dict) or not raw_configurations:
        return _off(path, True, "smtp.configurations must be a non-empty mapping")

    configurations: dict[str, LoadedSmtpConfiguration] = {}
    invalid: dict[str, tuple[str, str | None]] = {}
    for key, raw in raw_configurations.items():
        name = str(key)
        loaded = _load_configuration(name, raw, source)
        if isinstance(loaded, LoadedSmtpConfiguration):
            configurations[name] = loaded
        else:
            invalid[name] = loaded

    default = smtp.get("default")
    error = None
    if default is None:
        if len(raw_configurations) == 1:
            default = str(next(iter(raw_configurations)))
        else:
            error = "smtp.default is required when there is more than one configuration"
    elif not isinstance(default, str) or (default not in configurations and default not in invalid):
        default = None
        error = "smtp.default must name one of smtp.configurations"
    return EmailSettings(
        settings_file=path,
        file_present=True,
        default=default,
        error=error,
        configurations=configurations,
        invalid=invalid,
    )


@functools.lru_cache(maxsize=1)
def get_email_settings() -> EmailSettings:
    return load_email_settings(settings.platform_settings_path)
