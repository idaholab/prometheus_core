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

"""Tests for custom exceptions."""

from prometheus_api.storage_client.exceptions import (
    StorageClientError,
    AuthenticationError,
    ItemNotFoundError,
    ValidationError,
    APIError,
)


def test_storage_client_error():
    """Test base StorageClientError."""
    error = StorageClientError("Test error", details={"key": "value"})

    assert str(error) == "Test error"
    assert error.message == "Test error"
    assert error.details == {"key": "value"}


def test_authentication_error():
    """Test AuthenticationError."""
    error = AuthenticationError("Invalid credentials")

    assert str(error) == "Invalid credentials"
    assert isinstance(error, StorageClientError)


def test_item_not_found_error():
    """Test ItemNotFoundError."""
    error = ItemNotFoundError(item_id=123)

    assert error.item_id == 123
    assert "123" in str(error)
    assert isinstance(error, StorageClientError)


def test_item_not_found_error_custom_message():
    """Test ItemNotFoundError with custom message."""
    error = ItemNotFoundError(item_id=456, message="Custom not found message")

    assert error.item_id == 456
    assert str(error) == "Custom not found message"


def test_validation_error():
    """Test ValidationError."""
    error = ValidationError("Invalid input", details={"field": "name"})

    assert str(error) == "Invalid input"
    assert error.details == {"field": "name"}
    assert isinstance(error, StorageClientError)


def test_api_error():
    """Test APIError."""
    error = APIError(
        "Server error", status_code=500, response_data={"error": "Internal server error"}
    )

    assert str(error) == "Server error"
    assert error.status_code == 500
    assert error.response_data == {"error": "Internal server error"}
    assert isinstance(error, StorageClientError)
