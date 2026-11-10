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

"""Tests for environment-based configuration.

Note: These tests use isolated .env files to avoid conflicts with
the real .env file in the project root.
"""

import pytest
from prometheus_api.storage_client import ConnectionConfig


def test_from_env_with_explicit_file(tmp_path):
    """Test loading from a specific .env file."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=test-key
DEEPLYNX_SECRET=test-secret
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456
""")

    config = ConnectionConfig.from_env(env_file=test_env)

    assert config.organization_id == 123
    assert config.project_id == 456
    assert config.api_key == "test-key"
    assert config.api_secret == "test-secret"
    assert config.uses_api_key is True


def test_from_env_with_parameter_override(tmp_path):
    """Test that manual parameters override .env values."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=env-key
DEEPLYNX_SECRET=env-secret
DEEPLYNX_ORG_ID=100
DEEPLYNX_PROJECT_ID=200
""")

    # Override org/project IDs
    config = ConnectionConfig.from_env(env_file=test_env, organization_id=999, project_id=888)

    assert config.organization_id == 999  # Overridden
    assert config.project_id == 888  # Overridden
    assert config.api_key == "env-key"  # From file


def test_from_env_with_jwt(tmp_path):
    """Test loading JWT token from .env."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_JWT_TOKEN=test-jwt-token-here
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456
""")

    config = ConnectionConfig.from_env(env_file=test_env)

    assert config.jwt_token == "test-jwt-token-here"
    assert config.uses_jwt is True
    assert config.uses_api_key is False


def test_from_env_missing_org_id(tmp_path):
    """Test error when org_id is missing."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=key
DEEPLYNX_SECRET=secret
DEEPLYNX_PROJECT_ID=456
""")

    with pytest.raises(ValueError, match="organization_id must be provided"):
        ConnectionConfig.from_env(env_file=test_env)


def test_from_env_missing_project_id(tmp_path):
    """Test error when project_id is missing."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=key
DEEPLYNX_SECRET=secret
DEEPLYNX_ORG_ID=123
""")

    with pytest.raises(ValueError, match="project_id must be provided"):
        ConnectionConfig.from_env(env_file=test_env)


def test_from_env_with_custom_settings(tmp_path):
    """Test custom connection settings from .env."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=key
DEEPLYNX_SECRET=secret
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456
DEEPLYNX_BASE_URL=https://custom.api.com/v1
""")

    config = ConnectionConfig.from_env(env_file=test_env, timeout=60.0, max_retries=5)

    assert config.base_url == "https://custom.api.com/v1"
    assert config.timeout == 60.0
    assert config.max_retries == 5


def test_from_env_with_data_source_id(tmp_path):
    """Test loading data_source_id from .env."""
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=key
DEEPLYNX_SECRET=secret
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456
DEEPLYNX_DATA_SOURCE_ID=789
""")

    config = ConnectionConfig.from_env(env_file=test_env)

    assert config.data_source_id == 789


def test_from_env_blank_data_source_id_is_unset(tmp_path, monkeypatch):
    """A blank DEEPLYNX_DATA_SOURCE_ID (compose ``${VAR:-}``) means unset."""
    monkeypatch.setenv("DEEPLYNX_DATA_SOURCE_ID", "")
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=key
DEEPLYNX_SECRET=secret
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456
DEEPLYNX_DATA_SOURCE_ID=
""")

    config = ConnectionConfig.from_env(env_file=test_env)

    assert config.data_source_id is None


def test_from_env_blank_org_id_raises_missing(tmp_path, monkeypatch):
    """A blank DEEPLYNX_ORG_ID reports the missing variable, not int('')."""
    monkeypatch.setenv("DEEPLYNX_ORG_ID", "")
    test_env = tmp_path / ".env.test"
    test_env.write_text("""
DEEPLYNX_KEY=key
DEEPLYNX_SECRET=secret
DEEPLYNX_ORG_ID=
DEEPLYNX_PROJECT_ID=456
""")

    with pytest.raises(ValueError, match="DEEPLYNX_ORG_ID"):
        ConnectionConfig.from_env(env_file=test_env)
