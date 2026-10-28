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

"""Connection configuration for the storage client."""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ConnectionConfig(BaseModel):
    """Configuration for connecting to the storage backend.

    This class stores all necessary connection parameters including authentication
    credentials and backend-specific identifiers (hidden from end users).
    """

    # Backend configuration (hidden from users)
    organization_id: int = Field(..., description="Organization identifier")
    project_id: int = Field(..., description="Project identifier")
    data_source_id: Optional[int] = Field(None, description="Data source identifier (optional)")

    # Base URL
    base_url: str = Field(
        default="https://deeplynx.inl.gov/api/v1",
        description="Base URL for the storage backend API",
    )

    # Authentication (either API key pair or JWT token)
    api_key: Optional[str] = Field(default=None, description="API key for authentication")
    api_secret: Optional[str] = Field(default=None, description="API secret for authentication")
    jwt_token: Optional[str] = Field(default=None, description="JWT token for authentication")

    # Connection settings
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum number of retries for failed requests")
    verify_ssl: bool = Field(default=True, description="Whether to verify SSL certificates")

    model_config = {
        "frozen": True,  # Make instances immutable
        "extra": "forbid",  # Reject unknown fields
    }

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base URL doesn't end with a slash."""
        return v.rstrip("/")

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        """Ensure timeout is positive."""
        if v <= 0:
            raise ValueError("Timeout must be positive")
        return v

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        """Ensure max_retries is non-negative."""
        if v < 0:
            raise ValueError("max_retries must be non-negative")
        return v

    def model_post_init(self, __context) -> None:
        """Validate that at least one authentication method is provided."""
        if not self.jwt_token and not (self.api_key and self.api_secret):
            raise ValueError("Must provide either jwt_token or both api_key and api_secret")

        if self.jwt_token and (self.api_key or self.api_secret):
            raise ValueError("Cannot provide both jwt_token and api_key/api_secret")

    @property
    def uses_api_key(self) -> bool:
        """Check if configuration uses API key authentication."""
        return bool(self.api_key and self.api_secret)

    @property
    def uses_jwt(self) -> bool:
        """Check if configuration uses JWT authentication."""
        return bool(self.jwt_token)

    @classmethod
    def from_env(
        cls,
        env_file: Optional[Path] = None,
        organization_id: Optional[int] = None,
        project_id: Optional[int] = None,
        **kwargs,
    ) -> "ConnectionConfig":
        """Create configuration from environment variables.

        Loads credentials from environment variables or a .env file.

        Expected environment variables:
        - DEEPLYNX_KEY: API key for authentication
        - DEEPLYNX_SECRET: API secret for authentication
        - DEEPLYNX_ORG_ID: Organization ID (optional if passed as parameter)
        - DEEPLYNX_PROJECT_ID: Project ID (optional if passed as parameter)
        - DEEPLYNX_BASE_URL: Base URL (optional)
        - DEEPLYNX_JWT_TOKEN: JWT token (alternative to API key/secret)

        Args:
            env_file: Optional path to .env file (default: searches for .env in current dir)
            organization_id: Organization ID (overrides env var)
            project_id: Project ID (overrides env var)
            **kwargs: Additional ConnectionConfig parameters

        Returns:
            ConnectionConfig instance

        Raises:
            ValueError: If required credentials are missing

        Example:
            ```python
            # Load from .env file in current directory
            config = ConnectionConfig.from_env()

            # Load from specific .env file
            config = ConnectionConfig.from_env(env_file=Path("/path/to/.env"))

            # Override with parameters
            config = ConnectionConfig.from_env(
                organization_id=123,
                project_id=456
            )
            ```
        """
        # Load .env file if it exists
        env_vars = {}
        if env_file and env_file.exists():
            try:
                from dotenv import dotenv_values

                env_vars = dotenv_values(env_file)
            except ImportError:
                raise ImportError(
                    "python-dotenv is required for .env file support. "
                    "Install it with: pip install python-dotenv"
                )
        elif env_file is None:
            # Try to load from default .env location
            default_env = Path.cwd() / ".env"
            if default_env.exists():
                try:
                    from dotenv import dotenv_values

                    env_vars = dotenv_values(default_env)
                except ImportError:
                    pass  # Silently skip if dotenv not installed

        # Get values from env file vars, with fallback to os.environ, then kwargs
        api_key = (
            env_vars.get("DEEPLYNX_KEY") or os.getenv("DEEPLYNX_KEY") or kwargs.pop("api_key", None)
        )
        api_secret = (
            env_vars.get("DEEPLYNX_SECRET")
            or os.getenv("DEEPLYNX_SECRET")
            or kwargs.pop("api_secret", None)
        )
        jwt_token = (
            env_vars.get("DEEPLYNX_JWT_TOKEN")
            or os.getenv("DEEPLYNX_JWT_TOKEN")
            or kwargs.pop("jwt_token", None)
        )

        # Organization and project IDs
        # An empty or whitespace-only value counts as unset.
        org_id = (
            organization_id
            or (env_vars.get("DEEPLYNX_ORG_ID") or os.getenv("DEEPLYNX_ORG_ID") or "").strip()
            or None
        )
        proj_id = (
            project_id
            or (
                env_vars.get("DEEPLYNX_PROJECT_ID") or os.getenv("DEEPLYNX_PROJECT_ID") or ""
            ).strip()
            or None
        )
        ds_id = (
            kwargs.pop("data_source_id", None)
            or (
                env_vars.get("DEEPLYNX_DATA_SOURCE_ID")
                or os.getenv("DEEPLYNX_DATA_SOURCE_ID")
                or ""
            ).strip()
            or None
        )

        if org_id is not None:
            org_id = int(org_id)
        if proj_id is not None:
            proj_id = int(proj_id)
        if ds_id is not None:
            ds_id = int(ds_id)

        # Base URL (optional)
        base_url = (
            env_vars.get("DEEPLYNX_BASE_URL")
            or os.getenv("DEEPLYNX_BASE_URL")
            or kwargs.pop("base_url", "https://deeplynx.inl.gov/api/v1")
        )

        # Validate required fields
        if org_id is None:
            raise ValueError(
                "organization_id must be provided either as parameter or "
                "in DEEPLYNX_ORG_ID environment variable"
            )
        if proj_id is None:
            raise ValueError(
                "project_id must be provided either as parameter or "
                "in DEEPLYNX_PROJECT_ID environment variable"
            )

        # Create config
        return cls(
            organization_id=org_id,
            project_id=proj_id,
            data_source_id=ds_id,
            api_key=api_key,
            api_secret=api_secret,
            jwt_token=jwt_token,
            base_url=base_url,
            **kwargs,
        )

    @classmethod
    def from_credential(
        cls,
        credential,
        *,
        organization_id: Optional[int] = None,
        project_id: Optional[int] = None,
        base_url: Optional[str] = None,
    ) -> "ConnectionConfig":
        """Build a :class:`ConnectionConfig` from a broker-issued credential.

        The *credential* is a :class:`~prometheus_api.credentials.Credential`
        returned by the credential broker for the ``"deeplynx"`` resource.
        Its ``value`` dict is expected to contain the keys that match the
        parameters of :meth:`from_env`.

        Org/project/base_url fall back to environment variables when not
        supplied in the credential value or as explicit arguments, so
        callers can override at any level.

        Args:
            credential: A broker-issued DeepLynx credential.
            organization_id: Override; takes precedence over ``credential.value``
                and env.
            project_id: Override; takes precedence over ``credential.value`` and env.
            base_url: Override; takes precedence over ``credential.value`` and env.

        Returns:
            A fully-populated :class:`ConnectionConfig`.
        """
        import os as _os

        value = dict(getattr(credential, "value", {}) or {})

        # Resolve org/project: explicit arg > credential value > env var.
        def _resolve_int(explicit, cred_key, env_key) -> Optional[int]:
            if explicit is not None:
                return int(explicit)
            from_cred = value.get(cred_key)
            if from_cred is not None:
                return int(from_cred)
            from_env = _os.getenv(env_key, "").strip()
            return int(from_env) if from_env else None

        org_id = _resolve_int(organization_id, "org_id", "DEEPLYNX_ORG_ID")
        proj_id = _resolve_int(project_id, "project_id", "DEEPLYNX_PROJECT_ID")

        if org_id is None:
            raise ValueError(
                "organization_id must be provided via argument, credential value "
                "(org_id), or DEEPLYNX_ORG_ID environment variable"
            )
        if proj_id is None:
            raise ValueError(
                "project_id must be provided via argument, credential value "
                "(project_id), or DEEPLYNX_PROJECT_ID environment variable"
            )

        # Build the ConnectionConfig directly to avoid double-passing kwargs.
        resolved_base_url = (
            base_url
            or value.get("base_url")
            or _os.getenv("DEEPLYNX_BASE_URL", "https://deeplynx.inl.gov/api/v1").strip()
        )
        ds_id_raw = _os.getenv("DEEPLYNX_DATA_SOURCE_ID", "").strip()
        data_source_id = int(ds_id_raw) if ds_id_raw else None

        return cls(
            organization_id=org_id,
            project_id=proj_id,
            data_source_id=data_source_id,
            api_key=value.get("key") or None,
            api_secret=value.get("secret") or None,
            jwt_token=value.get("jwt_token") or None,
            base_url=resolved_base_url,
        )
