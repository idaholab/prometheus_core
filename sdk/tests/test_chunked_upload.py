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

"""Tests for chunked uploads: the request shapes DeepLynx accepts and the completion count."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from prometheus_api.storage_client.exceptions import StorageClientError
from prometheus_api.storage_client.utils.streaming import AsyncChunkedUploader, ChunkedUploader


class Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


# What DeepLynx v0.8.0 answers. The start response suggests one 100 MB chunk whatever chunk size
# was sent, and it names the session ``uploadId``.
START_RESPONSE = {"uploadId": "sess-1", "chunkSize": 100000000, "totalChunks": 1}
FILE_RECORD = {"id": 41, "name": "big.bin", "fileSize": 7, "lastUpdatedAt": "2026-04-25T12:00:00Z"}


class FakeClient:
    """Answers the four chunked-upload routes and records every request."""

    def __init__(self, fail_on_chunk=None):
        self.config = SimpleNamespace(organization_id=1, project_id=2)
        self.files = SimpleNamespace(
            _base_path="/organizations/1/projects/2",
            _parse_file_metadata=lambda data: SimpleNamespace(**data),
        )
        self.calls = []
        self.fail_on_chunk = fail_on_chunk

    def _answer(self, method, path, kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/files/upload/start"):
            return Response(START_RESPONSE)
        if path.endswith("/files/upload/chunk"):
            if self.fail_on_chunk == kwargs["data"]["chunkNumber"]:
                raise StorageClientError("chunk refused")
            return Response({})
        if path.endswith("/files/upload/complete"):
            return Response(FILE_RECORD)
        return Response({})

    def _request(self, method, path, **kwargs):
        return self._answer(method, path, kwargs)


class AsyncFakeClient(FakeClient):
    async def _request(self, method, path, **kwargs):
        return self._answer(method, path, kwargs)


def _file(tmp_path, size):
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * size)
    return path


def _by_route(client):
    return {path.rsplit("/", 1)[-1]: (method, kwargs) for method, path, kwargs in client.calls}


async def test_requests_use_the_camel_case_names_the_server_accepts(tmp_path):
    """Covers REQ-003-17: start, chunk and complete send camelCase names, sync and async."""
    path = _file(tmp_path, 7)
    sync_client, async_client = FakeClient(), AsyncFakeClient()

    ChunkedUploader(sync_client, chunk_size=3).upload(path, description="why")
    await AsyncChunkedUploader(async_client, chunk_size=3).upload(path, description="why")

    assert sync_client.calls == async_client.calls
    start = sync_client.calls[0]
    assert start[:2] == ("POST", "/organizations/1/projects/2/files/upload/start")
    assert start[2]["json"] == {"fileName": "big.bin", "fileSize": 7, "chunkSize": 3}
    chunk = sync_client.calls[1]
    assert chunk[2]["data"] == {"uploadId": "sess-1", "chunkNumber": 0}
    assert chunk[2]["files"]["chunk"] == ("chunk_0", b"xxx")
    complete = sync_client.calls[-1]
    assert complete[2]["json"]["uploadId"] == "sess-1"
    assert complete[2]["json"]["fileName"] == "big.bin"


async def test_complete_uses_the_session_id_from_the_start_response(tmp_path):
    """Covers REQ-003-17: the start response names the session ``uploadId``, not ``upload_id``."""
    path = _file(tmp_path, 4)
    client = FakeClient()

    ChunkedUploader(client, chunk_size=2).upload(path)

    ids = {kwargs["data"]["uploadId"] for _, p, kwargs in client.calls if p.endswith("/chunk")}
    assert ids == {"sess-1"}
    assert client.calls[-1][2]["json"]["uploadId"] == "sess-1"


@pytest.mark.parametrize("size, chunk, expected", [(7, 3, 3), (6, 3, 2), (1, 5, 1), (10, 10, 1)])
async def test_complete_carries_the_number_of_chunks_actually_sent(tmp_path, size, chunk, expected):
    """Covers REQ-003-05: not the count the start response suggests, which truncates the file."""
    path = _file(tmp_path, size)
    sync_client, async_client = FakeClient(), AsyncFakeClient()

    ChunkedUploader(sync_client, chunk_size=chunk).upload(path)
    await AsyncChunkedUploader(async_client, chunk_size=chunk).upload(path)

    for client in (sync_client, async_client):
        route = _by_route(client)
        sent = [c for c in client.calls if c[1].endswith("/chunk")]
        assert len(sent) == expected
        assert [c[2]["data"]["chunkNumber"] for c in sent] == list(range(expected))
        assert route["complete"][1]["json"]["totalChunks"] == expected


async def test_description_travels_in_metadata_not_at_the_top_level(tmp_path):
    """Covers REQ-003-17: the server ignores a top-level description and invents its own."""
    path = _file(tmp_path, 3)
    sync_client, async_client = FakeClient(), AsyncFakeClient()

    ChunkedUploader(sync_client, chunk_size=3).upload(path, name="named.bin", description="why")
    await AsyncChunkedUploader(async_client, chunk_size=3).upload(
        path, name="named.bin", description="why"
    )

    for client in (sync_client, async_client):
        body = client.calls[-1][2]["json"]
        assert "description" not in body
        assert body["metadata"] == {"Name": "named.bin", "Description": "why", "Properties": {}}


async def test_no_metadata_is_sent_without_a_description(tmp_path):
    """Covers REQ-003-17: a plain upload sends no metadata part."""
    path = _file(tmp_path, 3)
    client = FakeClient()

    ChunkedUploader(client, chunk_size=3).upload(path)

    assert "metadata" not in client.calls[-1][2]["json"]


async def test_a_failed_chunk_cancels_the_session_and_reraises(tmp_path):
    """Covers REQ-003-05: the session is cancelled best-effort when an intermediate step fails."""
    path = _file(tmp_path, 7)
    sync_client, async_client = FakeClient(fail_on_chunk=1), AsyncFakeClient(fail_on_chunk=1)

    with pytest.raises(StorageClientError, match="chunk refused"):
        ChunkedUploader(sync_client, chunk_size=3).upload(path)
    with pytest.raises(StorageClientError, match="chunk refused"):
        await AsyncChunkedUploader(async_client, chunk_size=3).upload(path)

    for client in (sync_client, async_client):
        assert client.calls[-1][:2] == ("DELETE", "/organizations/1/projects/2/files/upload/sess-1")
        assert not any(p.endswith("/complete") for _, p, _ in client.calls)


async def test_a_start_response_without_an_id_falls_back_to_a_generated_uuid(tmp_path):
    """Covers REQ-003-06: the session ID is a UUID when the start response has none."""
    path = _file(tmp_path, 3)
    client = FakeClient()

    def answer(method, path_, kwargs):
        if path_.endswith("/files/upload/start"):
            client.calls.append((method, path_, kwargs))
            return Response({})
        return FakeClient._answer(client, method, path_, kwargs)

    client._answer = answer

    ChunkedUploader(client, chunk_size=3).upload(path)

    session = client.calls[1][2]["data"]["uploadId"]
    assert len(session) == 36 and session.count("-") == 4
    assert client.calls[-1][2]["json"]["uploadId"] == session


def test_a_missing_file_raises_before_any_request(tmp_path):
    """Covers REQ-003-05: a path that does not exist is rejected without starting a session."""
    client = FakeClient()

    with pytest.raises(ValueError, match="does not exist"):
        ChunkedUploader(client).upload(tmp_path / "nope.bin")

    assert client.calls == []


class ShrinkingFile:
    """A path whose size, as stat reports it, is larger than what the file holds when read."""

    def __init__(self, real, claimed_size):
        self._real, self._claimed = real, claimed_size

    def exists(self):
        return True

    @property
    def name(self):
        return self._real.name

    def stat(self):
        return SimpleNamespace(st_size=self._claimed)

    def __fspath__(self):
        return str(self._real)


async def test_a_file_that_shrinks_during_the_upload_completes_with_the_chunks_sent(tmp_path):
    """Covers REQ-003-05: the count is what was sent, not what stat promised."""
    real = _file(tmp_path, 4)  # 2 chunks of 2 bytes, but stat will claim 10 bytes (5 chunks)
    claimed = ShrinkingFile(real, 10)
    sync_client, async_client = FakeClient(), AsyncFakeClient()

    ChunkedUploader(sync_client, chunk_size=2).upload(claimed)
    await AsyncChunkedUploader(async_client, chunk_size=2).upload(claimed)

    for client in (sync_client, async_client):
        sent = [c for c in client.calls if c[1].endswith("/chunk")]
        assert len(sent) == 2
        assert client.calls[-1][2]["json"]["totalChunks"] == 2


async def test_a_missing_file_raises_before_any_request_in_async(tmp_path):
    """Covers REQ-003-05: the async uploader rejects a missing path without starting a session."""
    client = AsyncFakeClient()

    with pytest.raises(ValueError, match="does not exist"):
        await AsyncChunkedUploader(client).upload(tmp_path / "nope.bin")

    assert client.calls == []


async def test_a_failed_cancel_does_not_hide_the_original_error(tmp_path):
    """Covers REQ-003-05: if cancelling also fails, the chunk error is still the one raised."""
    path = _file(tmp_path, 4)

    class CancelFails(FakeClient):
        def _answer(self, method, path_, kwargs):
            if method == "DELETE":
                raise StorageClientError("cancel refused")
            return FakeClient._answer(self, method, path_, kwargs)

    class AsyncCancelFails(CancelFails):
        async def _request(self, method, path_, **kwargs):
            return self._answer(method, path_, kwargs)

    with pytest.raises(StorageClientError, match="chunk refused"):
        ChunkedUploader(CancelFails(fail_on_chunk=1), chunk_size=2).upload(path)
    with pytest.raises(StorageClientError, match="chunk refused"):
        await AsyncChunkedUploader(AsyncCancelFails(fail_on_chunk=1), chunk_size=2).upload(path)
