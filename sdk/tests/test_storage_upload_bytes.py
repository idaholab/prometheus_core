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

"""Tests for uploading in-memory bytes through the sync and async storage clients."""

from __future__ import annotations

import json
import random
import tempfile

import httpx
import pytest

from prometheus_api.storage_client import AsyncStorageClient, ConnectionConfig, StorageClient
from prometheus_api.storage_client.auth import AsyncAuthHandler, AuthHandler

BASE_URL = "https://deeplynx.test/api/v1"
FILES_PATH = "/api/v1/organizations/1/projects/2/files"
CHUNK_SIZE = 5 * 1024 * 1024  # the ChunkedUploader default
LARGE_PAYLOAD = random.Random(0).randbytes(CHUNK_SIZE + 1024)
FILE_RESPONSE = {"id": 42, "name": "report.bin", "fileSize": 0}


def _config() -> ConnectionConfig:
    return ConnectionConfig(
        organization_id=1, project_id=2, base_url=BASE_URL, jwt_token="test-token"
    )


def _handler(requests: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == f"{FILES_PATH}/upload/start":
            return httpx.Response(200, json={"upload_id": "up-1"})
        if request.url.path == f"{FILES_PATH}/upload/chunk":
            return httpx.Response(200, json={})
        return httpx.Response(200, json=FILE_RESPONSE)

    return handle


def _sync_client(requests: list[httpx.Request]) -> StorageClient:
    # StorageClient has no transport seam, so the test wires its HTTP client the way
    # StorageClient.__enter__ does, with a MockTransport in place of the network.
    client = StorageClient(_config())
    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(_handler(requests)))
    client._http_client = http
    client._auth_handler = AuthHandler(client.config, http)
    return client


def _async_client(requests: list[httpx.Request]) -> AsyncStorageClient:
    client = AsyncStorageClient(_config())
    http = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(_handler(requests)))
    client._http_client = http
    client._auth_handler = AsyncAuthHandler(client.config, http)
    return client


@pytest.fixture(autouse=True)
def no_tempfile(monkeypatch):
    """Fail the test if the upload writes a temporary file."""

    def forbidden(*args, **kwargs):
        raise AssertionError("upload_bytes must not create a temporary file")

    for name in (
        "NamedTemporaryFile",
        "TemporaryFile",
        "SpooledTemporaryFile",
        "TemporaryDirectory",
        "mkstemp",
        "mkdtemp",
    ):
        monkeypatch.setattr(tempfile, name, forbidden)


def _assert_single_post(requests: list[httpx.Request], data: bytes) -> None:
    assert [(r.method, r.url.path) for r in requests] == [("POST", FILES_PATH)]
    request = requests[0]
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="report.bin"' in request.content
    assert data in request.content
    assert b'name="description"' in request.content
    assert b"Quarterly numbers" in request.content


def _assert_chunked(requests: list[httpx.Request], data: bytes) -> None:
    chunks = [data[:CHUNK_SIZE], data[CHUNK_SIZE:]]
    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", f"{FILES_PATH}/upload/start"),
        ("POST", f"{FILES_PATH}/upload/chunk"),
        ("POST", f"{FILES_PATH}/upload/chunk"),
        ("POST", f"{FILES_PATH}/upload/complete"),
    ]
    start, first, second, complete = requests
    assert json.loads(start.content)["file_size"] == len(data)
    assert chunks[0] in first.content
    assert chunks[1] in second.content
    assert chunks[1] not in first.content
    assert json.loads(complete.content) == {
        "upload_id": "up-1",
        "file_name": "report.bin",
        "total_chunks": 2,
        "description": "Quarterly numbers",
    }


@pytest.mark.parametrize(
    "data",
    [b"small payload bytes", random.Random(1).randbytes(CHUNK_SIZE)],
    ids=["small", "exactly-chunk-size"],
)
def test_sync_upload_bytes_up_to_chunk_size_sends_one_multipart_post(data):
    """Covers REQ-003-15."""
    requests: list[httpx.Request] = []
    client = _sync_client(requests)

    metadata = client.files.upload_bytes(data, "report.bin", "Quarterly numbers")
    client._http_client.close()

    assert metadata.id == 42
    _assert_single_post(requests, data)


def test_sync_upload_bytes_above_chunk_size_uses_chunked_uploader():
    """Covers REQ-003-15."""
    requests: list[httpx.Request] = []
    client = _sync_client(requests)

    metadata = client.files.upload_bytes(LARGE_PAYLOAD, "report.bin", "Quarterly numbers")
    client._http_client.close()

    assert metadata.id == 42
    _assert_chunked(requests, LARGE_PAYLOAD)


@pytest.mark.parametrize(
    "data",
    [b"small payload bytes", random.Random(1).randbytes(CHUNK_SIZE)],
    ids=["small", "exactly-chunk-size"],
)
async def test_async_upload_bytes_up_to_chunk_size_sends_one_multipart_post(data):
    """Covers REQ-003-15."""
    requests: list[httpx.Request] = []
    client = _async_client(requests)

    metadata = await client.files.upload_bytes(data, "report.bin", "Quarterly numbers")
    await client._http_client.aclose()

    assert metadata.id == 42
    _assert_single_post(requests, data)


async def test_async_upload_bytes_above_chunk_size_uses_chunked_uploader():
    """Covers REQ-003-15."""
    requests: list[httpx.Request] = []
    client = _async_client(requests)

    metadata = await client.files.upload_bytes(LARGE_PAYLOAD, "report.bin", "Quarterly numbers")
    await client._http_client.aclose()

    assert metadata.id == 42
    _assert_chunked(requests, LARGE_PAYLOAD)
