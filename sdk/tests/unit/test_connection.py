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

"""Tests for connection configuration."""

import pytest
from prometheus_api.storage_client import ConnectionConfig


def test_connection_config_with_api_key():
    """Test creating connection config with API key."""
    config = ConnectionConfig(
        organization_id=123, project_id=456, api_key="test-key", api_secret="test-secret"
    )

    assert config.organization_id == 123
    assert config.project_id == 456
    assert config.api_key == "test-key"
    assert config.api_secret == "test-secret"
    assert config.uses_api_key is True
    assert config.uses_jwt is False


def test_connection_config_with_jwt():
    """Test creating connection config with JWT token."""
    config = ConnectionConfig(organization_id=123, project_id=456, jwt_token="test-token")

    assert config.jwt_token == "test-token"
    assert config.uses_api_key is False
    assert config.uses_jwt is True


def test_connection_config_requires_auth():
    """Test that connection config requires authentication."""
    with pytest.raises(ValueError, match="Must provide either jwt_token"):
        ConnectionConfig(organization_id=123, project_id=456)


def test_connection_config_rejects_both_auth_methods():
    """Test that connection config rejects both auth methods."""
    with pytest.raises(ValueError, match="Cannot provide both"):
        ConnectionConfig(
            organization_id=123,
            project_id=456,
            api_key="key",
            api_secret="secret",
            jwt_token="token",
        )


def test_connection_config_base_url_normalization():
    """Test that base URL is normalized."""
    config = ConnectionConfig(
        organization_id=123,
        project_id=456,
        api_key="key",
        api_secret="secret",
        base_url="https://example.com/",
    )

    assert config.base_url == "https://example.com"


def test_connection_config_immutable():
    """Test that connection config is immutable."""
    config = ConnectionConfig(
        organization_id=123, project_id=456, api_key="key", api_secret="secret"
    )

    with pytest.raises(Exception):  # Pydantic will raise an error
        config.organization_id = 999


def test_connection_config_default_values():
    """Test default configuration values."""
    config = ConnectionConfig(
        organization_id=123, project_id=456, api_key="key", api_secret="secret"
    )

    assert config.timeout == 30.0
    assert config.max_retries == 3
    assert config.verify_ssl is True
    assert config.base_url == "https://deeplynx.inl.gov/api/v1"
