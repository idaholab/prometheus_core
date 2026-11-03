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

"""Tests for timeseries queries over tabular file records (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from prometheus_api.storage_client import AsyncStorageClient, StorageClient
from prometheus_api.storage_client.async_resources.timeseries import AsyncTimeseriesResource
from prometheus_api.storage_client.models.timeseries import TimeseriesResult
from prometheus_api.storage_client.resources.timeseries import TimeseriesResource


class Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class SyncClient:
    def __init__(self, payload):
        self.config = SimpleNamespace(organization_id=1, project_id=2)
        self.calls = []
        self._payload = payload

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return Response(self._payload)


class AsyncClient(SyncClient):
    async def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return Response(self._payload)


# What olap/query returned on a real server: a bare {columns, data} object, with `{}` for
# a missing cell and a column that mixes numbers and `{}`
QUERY_RESPONSE = {
    "columns": ["Timestamp", "power"],
    "data": [["2026-08-20 23:10:26.444", 5.5], ["2026-08-20 23:10:28.344", {}], ["x", 0]],
}


async def run_both(payload, *args, **kwargs):
    """Run the same query through the sync and async resources; return both clients/results."""
    sync_client = SyncClient(payload)
    async_client = AsyncClient(payload)
    sync_result = TimeseriesResource(sync_client).query(*args, **kwargs)
    async_result = await AsyncTimeseriesResource(async_client).query(*args, **kwargs)
    return sync_client, async_client, sync_result, async_result


async def test_query_posts_to_olap_route_with_defaults_in_sync_and_async():
    """Covers REQ-003-12: a bare query sends the view name and an empty body."""
    sync_client, async_client, sync_result, async_result = await run_both(QUERY_RESPONSE, 123)

    assert sync_client.calls == async_client.calls
    method, path, kwargs = sync_client.calls[0]
    assert method == "POST"
    assert path == "/organizations/1/projects/2/records/123/olap/query"
    assert kwargs["params"] == {"viewName": "data"}
    assert kwargs["json"] == {}
    assert sync_result == async_result


async def test_query_sends_only_the_options_given_in_camel_case():
    """Covers REQ-003-12: provided options are sent with the server's camelCase names."""
    sync_client, async_client, _, _ = await run_both(
        QUERY_RESPONSE,
        7,
        "check_view",
        'SELECT "a.b" FROM check_view',
        limit=10,
        row_stride=2,
        start_row=5,
        stop_row=50,
        columns=["Timestamp", "power"],
    )

    assert sync_client.calls == async_client.calls
    _, _, kwargs = sync_client.calls[0]
    assert kwargs["params"] == {"viewName": "check_view"}
    assert kwargs["json"] == {
        "query": 'SELECT "a.b" FROM check_view',
        "limit": 10,
        "rowStride": 2,
        "startRow": 5,
        "stopRow": 50,
        "columns": ["Timestamp", "power"],
    }


async def test_query_keeps_zero_and_empty_string_options():
    """Covers REQ-003-12: only ``None`` is dropped; a falsy value the caller chose is sent."""
    sync_client, async_client, _, _ = await run_both(QUERY_RESPONSE, 7, sql_query="", start_row=0)

    assert sync_client.calls == async_client.calls
    assert sync_client.calls[0][2]["json"] == {"query": "", "startRow": 0}


async def test_query_returns_rows_untouched_in_sync_and_async():
    """Covers REQ-003-12: cells are not coerced, so ``{}`` and mixed types survive."""
    _, _, sync_result, async_result = await run_both(QUERY_RESPONSE, 123)

    assert isinstance(sync_result, TimeseriesResult)
    assert sync_result.model_dump() == async_result.model_dump()
    assert sync_result.columns == ["Timestamp", "power"]
    assert sync_result.data == QUERY_RESPONSE["data"]
    assert sync_result.data[1][1] == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"columns": ["n"], "data": []},
        {"columns": ["n"], "data": None},
        {"columns": None, "data": None},
        {},
    ],
)
async def test_query_treats_an_empty_window_as_an_empty_result(payload):
    """Covers REQ-003-12: a window past the end is an empty result, not an error."""
    _, _, sync_result, async_result = await run_both(payload, 123, start_row=10_000_000)

    assert sync_result.data == [] and async_result.data == []
    assert sync_result.model_dump() == async_result.model_dump()


def test_timeseries_upload_was_removed():
    """Covers REQ-003-12: the removed upload route has no replacement method."""
    assert not hasattr(TimeseriesResource, "upload")
    assert not hasattr(AsyncTimeseriesResource, "upload")


def test_clients_still_expose_the_timeseries_handlers():
    """Covers REQ-001-08: the ``timeseries`` property still builds its handler."""
    config = SimpleNamespace(organization_id=1, project_id=2)
    sync_client = StorageClient.__new__(StorageClient)
    sync_client.config = config
    sync_client._timeseries = None
    async_client = AsyncStorageClient.__new__(AsyncStorageClient)
    async_client.config = config
    async_client._timeseries = None

    assert isinstance(sync_client.timeseries, TimeseriesResource)
    assert sync_client.timeseries is sync_client.timeseries
    assert isinstance(async_client.timeseries, AsyncTimeseriesResource)
