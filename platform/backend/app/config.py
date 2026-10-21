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

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings

CONFIG_PATH = os.environ.get(
    "PROMETHEUS_CONFIG_PATH",
    str(Path(__file__).parent / "config.yml"),
)
MAX_UPLOAD_BYTES_ENV = "PROMETHEUS_MAX_UPLOAD_BYTES"
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def read_config(config_file_path: str) -> dict[str, Any]:
    try:
        with open(config_file_path, "r") as f:
            data = yaml.safe_load(f) or {}
        return data
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_file_path}")
    except yaml.YAMLError as e:
        raise RuntimeError(f"Invalid YAML: {e}")


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def get_max_upload_bytes(data: dict[str, Any]) -> int:
    env_value = os.environ.get(MAX_UPLOAD_BYTES_ENV)
    if env_value is not None and env_value.strip():
        return _positive_int(env_value, MAX_UPLOAD_BYTES_ENV)
    return _positive_int(data.get("max-upload-bytes", DEFAULT_MAX_UPLOAD_BYTES), "max-upload-bytes")


def _jwt_secret(data: dict[str, Any]) -> str:
    # Prefer the env secret, then the config file value.
    return os.environ.get("BACKEND_JWT_SECRET") or data.get("jwt-secret", "")


def _dev_cors_origins() -> list[str]:
    """Explicit dev CORS origins (AU-9).

    A wildcard ``*`` with credentials is rejected by browsers and is a footgun, so in
    debug we enumerate the local dev origins instead. Override via
    ``BACKEND_DEV_ORIGINS`` (comma-separated); defaults cover the Vite dev server
    on its common ports.
    """
    raw = os.environ.get("BACKEND_DEV_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5150",
        "http://127.0.0.1:5150",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def _with_redis_password(url: str) -> str:
    """Fold ``REDIS_PASSWORD`` into ``url`` when the URL carries no credentials.

    The documented setup embeds the password directly in ``REDIS_URL`` (``.env.example``),
    in which case this is a no-op. It only activates the footgun case (DEP-1): a deploy
    sets ``REDIS_PASSWORD`` but leaves ``REDIS_URL`` at a password-less default, which
    would otherwise hit ``NOAUTH`` (or, with RESP3, a ``HELLO`` auth error) on every
    Redis-backed feature. The password is URL-encoded since this code path constructs
    the userinfo itself.
    """
    password = os.environ.get("REDIS_PASSWORD")
    if password and "@" not in urlsplit(url).netloc:
        parts = urlsplit(url)
        netloc = f":{quote(password, safe='')}@{parts.netloc}"
        url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


def _redis_url(data: dict[str, Any]) -> str:
    """Resolve the Redis URL (env ``REDIS_URL`` > ``config.yml`` > localhost), folding
    in ``REDIS_PASSWORD`` via :func:`_with_redis_password`."""
    return _with_redis_password(os.environ.get("REDIS_URL", data.get("redis-url", "redis://localhost:6379")))


def _cookie_secure(data: dict) -> bool:
    """Whether to mark auth cookies ``Secure``, derived from the browser-facing scheme.

    This used to be ``not settings.debug``, which is wrong for the default dev
    setup: ``debug`` is ``false`` in ``config.yml`` while ``BACKEND_PUBLIC_URL`` is
    ``http://localhost:5150``, so the cookie went out marked ``Secure`` over plain
    http. Chrome and Firefox special-case ``http://localhost`` and keep it anyway;
    **Safari does not**, and no browser keeps it for ``http://<LAN-IP>:5150``. The
    cookie is then dropped silently, every ``/api`` call 401s, and the UI bounces to
    Login with nothing to explain it.

    ``BACKEND_COOKIE_SECURE`` / ``cookie-secure`` wins if set (needed when the
    browser-facing scheme is https but this process cannot know it -- e.g. TLS
    terminated by an ingress that does not set ``BACKEND_PUBLIC_URL``). Otherwise
    the scheme of ``BACKEND_PUBLIC_URL`` decides. With no public URL configured
    there is nothing to derive from, so the old ``not debug`` behaviour stands.
    """
    raw = os.environ.get("BACKEND_COOKIE_SECURE", data.get("cookie-secure"))
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    public = os.environ.get("BACKEND_PUBLIC_URL", "").strip().lower()
    if public.startswith("https://"):
        return True
    if public.startswith("http://"):
        return False
    return not bool(data.get("debug", False))


class Settings(BaseSettings):
    data: dict[str, Any] = read_config(CONFIG_PATH)

    # Content / suggestions
    workflow_suggestions: list[str] = data.get("workflow-suggestions", [])
    chat_suggestion_title: str = data.get("chat-suggestion-title", "")
    chat_intro: str = data.get("chat-intro", "")

    # Upstream client-agent + Redis (env overrides)
    agent_url: str = os.environ.get("CLIENT_AGENT_URL", data.get("agent-url", "http://localhost:8001"))
    agent_secret: str = os.environ.get("AGENT_SECRET", data.get("agent-secret", ""))
    redis_url: str = _redis_url(data)

    # ``BaseSettings`` also reads the ``REDIS_URL`` env var into this field, which
    # replaces the default above and would skip the ``REDIS_PASSWORD`` folding.
    # Re-apply it to whatever value won.
    @field_validator("redis_url")
    @classmethod
    def _fold_redis_password(cls, v: str) -> str:
        return _with_redis_password(v)

    # Uploads
    max_upload_bytes: int = get_max_upload_bytes(data)

    # Mesh (Exodus/STL) → VTP conversion cache root (empty = <tempdir>/prometheus-mesh).
    # Overridden by env PROMETHEUS_MESH_CACHE_DIR. Should point at a persistent volume:
    # the cache is content-hash keyed, so anything it keeps is a conversion never repeated.
    mesh_cache_dir: str = os.environ.get("PROMETHEUS_MESH_CACHE_DIR", data.get("mesh-cache-dir", ""))
    # Size of the VTK conversion subprocess pool (app/services/mesh/service.py).
    # NOTE FOR OPERATORS: this is *per web worker*. Running uvicorn with --workers N
    # gives N × mesh_workers VTK children at peak, so size the container memory limit
    # against that product, not against this number alone.
    mesh_workers: int = _positive_int(
        (os.environ.get("PROMETHEUS_MESH_WORKERS") or "").strip() or data.get("mesh-workers", 2),
        "mesh-workers",
    )
    # Wall-clock budget for one Exodus/STL → VTP conversion. On expiry the pool is
    # killed and the artifact degrades to a file download; see _discard_executor.
    mesh_timeout_seconds: int = _positive_int(
        (os.environ.get("PROMETHEUS_MESH_TIMEOUT_SECONDS") or "").strip() or data.get("mesh-timeout-seconds", 120),
        "mesh-timeout-seconds",
    )

    # Behavior
    debug: bool = data.get("debug", False)
    auto_approve_steps: bool = data.get("auto-approve-steps", False)
    dev_cors_origins: list[str] = _dev_cors_origins()

    # Auth / session
    jwt_secret: str = _jwt_secret(data)
    cookie_name: str = os.environ.get("BACKEND_COOKIE_NAME", data.get("cookie-name", "prometheus_session"))
    # See _cookie_secure: gated on the browser-facing scheme, not on `debug`.
    cookie_secure: bool = _cookie_secure(data)
    token_ttl_seconds: int = _positive_int(
        os.environ.get("BACKEND_TOKEN_TTL_SECONDS", data.get("token-ttl-seconds", 86400)),
        "token-ttl-seconds",
    )

    # Admin plane (local users, OIDC provider config, RS256 signing keys).
    # See app/db/__init__.py. No config.yml equivalent -- infra URL, env-only.
    admin_database_url: str = os.environ.get(
        "ADMIN_DATABASE_URL", "postgresql+asyncpg://admin:admin@admin-db:5432/admin"
    )
    # Encrypts OidcProvider.client_secret and SigningKey.private_key at rest
    # (Fernet). Required to actually store/read those tables -- see app/crypto.py.
    admin_db_encryption_key: str = os.environ.get("ADMIN_DB_ENCRYPTION_KEY", "")

    # Base URL for the OIDC redirect_uri sent to identity providers
    # (app/security.py::_callback_url). request.base_url reflects whatever
    # host a reverse proxy (Vite dev server, nginx) used to reach this
    # container *internally* -- never the browser-facing origin -- so it
    # can't be trusted for this (and blindly trusting a forwarded-host header
    # here would be an open-redirect risk in an OAuth flow). Empty falls back
    # to request.base_url, correct only when nothing proxies /api requests
    # (e.g. hitting this backend directly on its own port with no frontend in
    # front). Must exactly match what's registered as the redirect URI with
    # every configured OIDC provider.
    backend_public_url: str = os.environ.get("BACKEND_PUBLIC_URL", "").rstrip("/")

    # Platform settings file (optional, operator-owned; app/email_settings.py reads its
    # smtp section). No config.yml equivalent -- env-only.
    platform_settings_path: str = (
        os.environ.get("PROMETHEUS_SETTINGS_PATH") or "/app/settings/platform-settings.yml"
    ).strip()


settings = Settings()
