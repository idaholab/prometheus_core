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

"""Tests for storage client request handling: status mapping and retries (no network)."""

from __future__ import annotations

import httpx
import pytest

from prometheus_api.storage_client import AsyncStorageClient, ConnectionConfig, StorageClient
from prometheus_api.storage_client.auth import AsyncAuthHandler, AuthHandler
from prometheus_api.storage_client.exceptions import (
    APIError,
    AuthenticationError,
    ItemNotFoundError,
    StorageClientError,
    ValidationError,
)

STATUS_CASES = [
    (401, AuthenticationError),
    (404, ItemNotFoundError),
    (400, ValidationError),
    (422, ValidationError),
    (500, APIError),
    (503, APIError),
]


def make_config(max_retries: int = 2) -> ConnectionConfig:
    # A JWT config never contacts the token endpoint, so only the request under test is sent.
    return ConnectionConfig(
        organization_id=1,
        project_id=2,
        jwt_token="test-token",
        base_url="http://nexus.test/api/v1",
        max_retries=max_retries,
    )


def sync_client(handler, max_retries: int = 2) -> StorageClient:
    config = make_config(max_retries)
    client = StorageClient(config)
    client._http_client = httpx.Client(
        base_url=config.base_url, transport=httpx.MockTransport(handler)
    )
    client._auth_handler = AuthHandler(config, client._http_client)
    return client


def async_client(handler, max_retries: int = 2) -> AsyncStorageClient:
    config = make_config(max_retries)
    client = AsyncStorageClient(config)
    client._http_client = httpx.AsyncClient(
        base_url=config.base_url, transport=httpx.MockTransport(handler)
    )
    client._auth_handler = AsyncAuthHandler(config, client._http_client)
    return client


@pytest.mark.parametrize(("status", "expected"), STATUS_CASES)
def test_sync_request_maps_status_to_specific_exception(status, expected):
    """Covers REQ-001-10: the mapped exception type must reach the caller unchanged."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": f"boom {status}"})

    client = sync_client(handler)
    with pytest.raises(expected) as excinfo:
        client._request("GET", "/organizations/1/projects/2/records/9")

    assert type(excinfo.value) is expected
    assert str(excinfo.value) == f"boom {status}"
    assert len(calls) == 1, "HTTP error responses must not be retried"


@pytest.mark.parametrize(("status", "expected"), STATUS_CASES)
async def test_async_request_maps_status_to_specific_exception(status, expected):
    """Covers REQ-001-10: the async client maps statuses exactly like the sync client."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": f"boom {status}"})

    client = async_client(handler)
    with pytest.raises(expected) as excinfo:
        await client._request("GET", "/organizations/1/projects/2/records/9")

    assert type(excinfo.value) is expected
    assert str(excinfo.value) == f"boom {status}"
    assert len(calls) == 1, "HTTP error responses must not be retried"


def test_sync_request_keeps_response_details_on_mapped_errors():
    """Covers REQ-001-10: the response body stays available on ValidationError and APIError."""
    body = {"error": "name is required", "field": "name"}
    client = sync_client(lambda request: httpx.Response(400, json=body))
    with pytest.raises(ValidationError) as validation:
        client._request("POST", "/records")
    assert validation.value.details == body

    client = sync_client(lambda request: httpx.Response(502, json={"message": "bad gateway"}))
    with pytest.raises(APIError) as api:
        client._request("GET", "/records")
    assert api.value.status_code == 502
    assert str(api.value) == "bad gateway"


def test_sync_request_falls_back_to_status_text_for_non_json_errors():
    """Covers REQ-001-10: a non-JSON error body still maps by status."""
    client = sync_client(lambda request: httpx.Response(500, text="<html>oops</html>"))
    with pytest.raises(APIError) as excinfo:
        client._request("GET", "/records")
    assert "oops" in str(excinfo.value)


def test_sync_request_retries_connection_errors_then_raises_storage_client_error():
    """Covers REQ-001-10: connection failures retry max_retries times, then fail generically."""
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    client = sync_client(handler, max_retries=2)
    with pytest.raises(StorageClientError, match="after 2 retries") as excinfo:
        client._request("GET", "/records")

    assert type(excinfo.value) is StorageClientError
    assert len(calls) == 3


async def test_async_request_retries_timeouts_then_succeeds():
    """Covers REQ-001-10: a transient timeout is retried and the later success is returned."""
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"id": 1})

    client = async_client(handler, max_retries=2)
    response = await client._request("GET", "/records/1")

    assert response.json() == {"id": 1}
    assert len(calls) == 2


def test_sync_request_sends_bearer_token_and_merges_caller_headers():
    """Covers REQ-001-09: auth header present and caller headers merged, not replaced."""
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={})

    client = sync_client(handler)
    client._request("GET", "/records", headers={"X-Trace": "abc"})

    assert seen["authorization"] == "Bearer test-token"
    assert seen["x-trace"] == "abc"


def test_sync_request_requires_context_manager():
    """Covers REQ-001-07: requests before initialization raise StorageClientError."""
    client = StorageClient(make_config())
    with pytest.raises(StorageClientError, match="not initialized"):
        client._request("GET", "/records")
