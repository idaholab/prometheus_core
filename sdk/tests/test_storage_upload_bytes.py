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

"""Tests for files.upload_bytes on the sync and async storage clients."""

from __future__ import annotations

import tempfile

import httpx
import pytest

from prometheus_api.storage_client.async_client import AsyncStorageClient
from prometheus_api.storage_client.auth import AsyncAuthHandler, AuthHandler
from prometheus_api.storage_client.client import StorageClient
from prometheus_api.storage_client.connection import ConnectionConfig

BASE_URL = "http://deeplynx.test/api/v1"
FILES_PATH = "/api/v1/organizations/1/projects/2/files"
CHUNK_SIZE = 5 * 1024 * 1024


def payload(size: int) -> bytes:
    # A period of 251 does not divide the chunk size, so misordered chunks differ.
    return (bytes(range(251)) * (size // 251 + 1))[:size]


def config() -> ConnectionConfig:
    return ConnectionConfig(organization_id=1, project_id=2, base_url=BASE_URL, jwt_token="t")


def multipart_parts(request: httpx.Request) -> dict[str, tuple[str | None, bytes]]:
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data")
    boundary = content_type.split("boundary=", 1)[1].encode()
    parts: dict[str, tuple[str | None, bytes]] = {}
    for raw in request.content.split(b"--" + boundary)[1:-1]:
        head, body = raw[2:].split(b"\r\n\r\n", 1)
        disposition = head.split(b"\r\n")[0].decode()
        fields = dict(
            item.strip().split("=", 1) for item in disposition.split(";")[1:] if "=" in item
        )
        filename = fields.get("filename")
        parts[fields["name"].strip('"')] = (
            filename.strip('"') if filename else None,
            body[: -len(b"\r\n")],
        )
    return parts


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == f"{FILES_PATH}/upload/start":
            return httpx.Response(200, json={"upload_id": "up-1"})
        if path == f"{FILES_PATH}/upload/chunk":
            return httpx.Response(200, json={})
        if path in (FILES_PATH, f"{FILES_PATH}/upload/complete"):
            return httpx.Response(200, json={"id": 42, "name": "blob.bin"})
        return httpx.Response(404, json={"error": path})


@pytest.fixture(autouse=True)
def no_tempfile(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("upload_bytes must not write a temporary file")

    for name in (
        "NamedTemporaryFile",
        "TemporaryFile",
        "SpooledTemporaryFile",
        "TemporaryDirectory",
        "mkstemp",
        "mkdtemp",
    ):
        monkeypatch.setattr(tempfile, name, refuse)


def sync_client(recorder: Recorder) -> StorageClient:
    client = StorageClient(config())
    client._http_client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(recorder))
    client._auth_handler = AuthHandler(client.config, client._http_client)
    return client


def async_client(recorder: Recorder) -> AsyncStorageClient:
    client = AsyncStorageClient(config())
    client._http_client = httpx.AsyncClient(
        base_url=BASE_URL, transport=httpx.MockTransport(recorder)
    )
    client._auth_handler = AsyncAuthHandler(client.config, client._http_client)
    return client


def assert_single_post(recorder: Recorder, data: bytes) -> None:
    assert [(r.method, r.url.path) for r in recorder.requests] == [("POST", FILES_PATH)]
    parts = multipart_parts(recorder.requests[0])
    assert parts["file"] == ("blob.bin", data)
    assert parts["description"] == (None, b"in memory")


def assert_chunked(recorder: Recorder, data: bytes) -> None:
    paths = [(r.method, r.url.path) for r in recorder.requests]
    assert paths == [
        ("POST", f"{FILES_PATH}/upload/start"),
        ("POST", f"{FILES_PATH}/upload/chunk"),
        ("POST", f"{FILES_PATH}/upload/chunk"),
        ("POST", f"{FILES_PATH}/upload/complete"),
    ]
    start, *chunks, complete = recorder.requests
    assert httpx.Response(200, content=start.content).json()["file_size"] == len(data)
    uploaded = b""
    for number, request in enumerate(chunks):
        parts = multipart_parts(request)
        assert parts["upload_id"] == (None, b"up-1")
        assert parts["chunk_number"] == (None, str(number).encode())
        uploaded += parts["chunk"][1]
    assert uploaded == data
    body = httpx.Response(200, content=complete.content).json()
    assert body == {
        "upload_id": "up-1",
        "file_name": "blob.bin",
        "total_chunks": 2,
        "description": "in memory",
    }


def test_sync_upload_bytes_small_is_one_multipart_post():
    """Covers REQ-003-14."""
    recorder = Recorder()
    data = payload(1024)

    meta = sync_client(recorder).files.upload_bytes(data, "blob.bin", "in memory")

    assert meta.id == 42
    assert_single_post(recorder, data)


def test_sync_upload_bytes_large_uses_chunked_uploader():
    """Covers REQ-003-14."""
    recorder = Recorder()
    data = payload(6 * 1024 * 1024)

    meta = sync_client(recorder).files.upload_bytes(data, "blob.bin", "in memory")

    assert meta.id == 42
    assert_chunked(recorder, data)


async def test_async_upload_bytes_small_is_one_multipart_post():
    """Covers REQ-003-14."""
    recorder = Recorder()
    data = payload(1024)

    meta = await async_client(recorder).files.upload_bytes(data, "blob.bin", "in memory")

    assert meta.id == 42
    assert_single_post(recorder, data)


async def test_async_upload_bytes_large_uses_chunked_uploader():
    """Covers REQ-003-14."""
    recorder = Recorder()
    data = payload(6 * 1024 * 1024)

    meta = await async_client(recorder).files.upload_bytes(data, "blob.bin", "in memory")

    assert meta.id == 42
    assert_chunked(recorder, data)
