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

"""Regression tests that keep sync and async resource behavior aligned."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from prometheus_api.storage_client.async_resources.items import AsyncItemsResource
from prometheus_api.storage_client.async_resources.search import AsyncSearchResource
from prometheus_api.storage_client.models.item import ItemCreate, ItemUpdate
from prometheus_api.storage_client.resources.items import ItemsResource
from prometheus_api.storage_client.resources.search import SearchResource


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

    def _get_data_source_id(self):
        return 7

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return Response(self._payload)


class AsyncClient(SyncClient):
    async def _get_data_source_id(self):
        return 7

    async def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return Response(self._payload)


def item_payload(**overrides):
    payload = {
        "id": 123,
        "name": "Sample",
        "description": "A sample item",
        "properties": {"kind": "test"},
        "classId": 9,
        "originalId": "orig-1",
        "lastUpdatedAt": "2026-04-25T12:00:00Z",
        "tags": [],
        "dataSourceId": 7,
    }
    payload.update(overrides)
    return payload


async def test_item_create_payloads_match_between_sync_and_async():
    sync_client = SyncClient(item_payload())
    async_client = AsyncClient(item_payload())

    item = ItemCreate(
        name="Sample",
        description="A sample item",
        properties={"kind": "test"},
        class_id=9,
        original_id="orig-1",
    )

    ItemsResource(sync_client).create(item)
    await AsyncItemsResource(async_client).create(item)

    assert sync_client.calls == async_client.calls
    method, path, kwargs = sync_client.calls[0]
    assert method == "POST"
    assert path == "/organizations/1/projects/2/records"
    assert kwargs["json"] == {
        "name": "Sample",
        "description": "A sample item",
        "properties": {"kind": "test"},
        "original_id": "orig-1",
        "class_id": 9,
    }
    assert kwargs["params"] == {"dataSourceId": 7}


@pytest.mark.parametrize("description", [None, ""])
async def test_item_create_defaults_missing_description_to_name(description):
    """Covers REQ-002-02: DeepLynx rejects an empty description, so default to the item name."""
    sync_client = SyncClient(item_payload())
    async_client = AsyncClient(item_payload())
    item = ItemCreate(name="Sample", description=description)

    ItemsResource(sync_client).create(item)
    await AsyncItemsResource(async_client).create(item)

    sync_json = sync_client.calls[0][2]["json"]
    async_json = async_client.calls[0][2]["json"]
    assert sync_json["description"] == "Sample"
    assert async_json["description"] == "Sample"


@pytest.mark.parametrize("description", [None, ""])
async def test_item_bulk_create_defaults_missing_description_to_name(description):
    """Covers REQ-002-02 for the bulk endpoint, sync and async."""
    sync_client = SyncClient([item_payload(id=1), item_payload(id=2)])
    async_client = AsyncClient([item_payload(id=1), item_payload(id=2)])
    items = [
        ItemCreate(name="First", description=description),
        ItemCreate(name="Second", description="Kept as given"),
    ]

    ItemsResource(sync_client).bulk_create(items)
    await AsyncItemsResource(async_client).bulk_create(items)

    for client in (sync_client, async_client):
        payload = client.calls[0][2]["json"]
        assert [entry["description"] for entry in payload] == ["First", "Kept as given"]


def paginated_payload(items, **overrides):
    """A ``PaginatedResponse<RecordResponseDto>`` as DeepLynx returns it."""
    payload = {
        "items": items,
        "pageNumber": 1,
        "pageSize": 2,
        "totalCount": 3,
        "totalCountIsApproximate": False,
        "totalPages": 2,
        "hasPrevious": False,
        "hasNext": True,
    }
    payload.update(overrides)
    return payload


async def test_item_list_uses_paginated_route_and_server_paging_in_sync_and_async():
    """Covers REQ-002-05: list calls /records/paginated and trusts the server's paging."""
    payload = paginated_payload([item_payload(id=1), item_payload(id=2)])
    sync_client = SyncClient(payload)
    async_client = AsyncClient(payload)

    sync_page = ItemsResource(sync_client).list(page=1, page_size=2)
    async_page = await AsyncItemsResource(async_client).list(page=1, page_size=2)

    assert sync_client.calls == async_client.calls
    method, path, kwargs = sync_client.calls[0]
    assert method == "GET"
    assert path == "/organizations/1/projects/2/records/paginated"
    assert kwargs["params"] == {"PageNumber": 1, "PageSize": 2}
    assert sync_page.model_dump() == async_page.model_dump()
    assert [item.id for item in sync_page.items] == [1, 2]
    assert sync_page.page_info.total_count == 3
    assert sync_page.page_info.has_next is True
    assert sync_page.page_info.has_previous is False


async def test_item_list_passes_filters_through_in_sync_and_async():
    """Covers REQ-002-05: extra filters are sent alongside the paging parameters."""
    payload = paginated_payload([], totalCount=0, hasNext=False)
    sync_client = SyncClient(payload)
    async_client = AsyncClient(payload)

    ItemsResource(sync_client).list(page=2, page_size=5, filters={"fileType": "csv"})
    await AsyncItemsResource(async_client).list(page=2, page_size=5, filters={"fileType": "csv"})

    assert sync_client.calls == async_client.calls
    assert sync_client.calls[0][2]["params"] == {
        "PageNumber": 2,
        "PageSize": 5,
        "fileType": "csv",
    }


@pytest.mark.parametrize("empty_items", [None, []])
async def test_item_list_treats_null_or_empty_items_as_empty_page(empty_items):
    """Covers REQ-002-05: the server returns ``items: null`` for an empty result."""
    payload = paginated_payload(empty_items, totalCount=0, hasNext=False, totalPages=0)

    sync_page = ItemsResource(SyncClient(payload)).list()
    async_page = await AsyncItemsResource(AsyncClient(payload)).list()

    assert sync_page.items == [] and async_page.items == []
    assert sync_page.page_info.total_count == 0
    assert sync_page.page_info.has_next is False


async def test_item_iter_all_follows_has_next_across_pages_in_sync_and_async():
    """Covers REQ-002-06: iteration stops when the server says there is no next page."""
    pages = {
        1: paginated_payload([item_payload(id=1), item_payload(id=2)], pageNumber=1),
        2: paginated_payload([item_payload(id=3)], pageNumber=2, hasNext=False, hasPrevious=True),
    }

    class PagedSync(SyncClient):
        def _request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return Response(pages[kwargs["params"]["PageNumber"]])

    class PagedAsync(AsyncClient):
        async def _request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return Response(pages[kwargs["params"]["PageNumber"]])

    sync_client = PagedSync(None)
    async_client = PagedAsync(None)

    sync_ids = [item.id for item in ItemsResource(sync_client).iter_all(page_size=2)]
    async_ids = [item.id async for item in AsyncItemsResource(async_client).iter_all(page_size=2)]

    assert sync_ids == async_ids == [1, 2, 3]
    assert len(sync_client.calls) == len(async_client.calls) == 2


async def test_item_update_payloads_match_between_sync_and_async():
    sync_client = SyncClient(item_payload(name="Updated"))
    async_client = AsyncClient(item_payload(name="Updated"))

    update = ItemUpdate(
        name="Updated",
        description="Updated description",
        properties={"kind": "updated"},
        class_id=10,
        original_id="orig-2",
    )

    ItemsResource(sync_client).update(123, update)
    await AsyncItemsResource(async_client).update(123, update)

    assert sync_client.calls == async_client.calls
    assert sync_client.calls[0] == (
        "PUT",
        "/organizations/1/projects/2/records/123",
        {
            "json": {
                "name": "Updated",
                "description": "Updated description",
                "properties": {"kind": "updated"},
                "class_id": 10,
                "original_id": "orig-2",
            }
        },
    )


async def test_search_query_payloads_and_parsing_match_between_sync_and_async():
    response_payload = [
        item_payload(
            properties='{"kind": "search"}',
            tags='[{"id": 4, "name": "indexed"}]',
        )
    ]
    sync_client = SyncClient(response_payload)
    async_client = AsyncClient(response_payload)

    sync_result = SearchResource(sync_client).query("sample")
    async_result = await AsyncSearchResource(async_client).query("sample")

    assert sync_client.calls == async_client.calls
    assert sync_client.calls[0] == (
        "GET",
        "/organizations/1/query/records",
        {"params": {"userQuery": "sample", "projectIds": [2]}},
    )
    assert sync_result.items[0] == async_result.items[0]
    assert async_result.items[0].properties == {"kind": "search"}
    assert async_result.items[0].tags[0].name == "indexed"


async def test_advanced_query_payloads_and_parsing_match_between_sync_and_async():
    """Covers REQ-002-14 and BEH-002-04."""
    response_payload = {
        "items": [item_payload(properties='{"metadata": {"nexus": {"test_id": "abc"}}}')],
        "pageNumber": 2,
        "pageSize": 10,
        "totalCount": 11,
        "totalPages": 2,
        "hasPrevious": True,
        "hasNext": False,
    }
    sync_client = SyncClient(response_payload)
    async_client = AsyncClient(response_payload)
    filters = [
        {
            "filter": "properties",
            "operator": "KEY_VALUE",
            "json": '{"metadata": {"nexus": {"test_id": "abc"}}}',
        }
    ]

    sync_result = SearchResource(sync_client).advanced_query(
        filters=filters,
        project_ids=[2],
        text_search="sample",
        page=2,
        page_size=10,
    )
    async_result = await AsyncSearchResource(async_client).advanced_query(
        filters=filters,
        project_ids=[2],
        text_search="sample",
        page=2,
        page_size=10,
    )

    assert sync_client.calls == async_client.calls
    assert sync_client.calls[0] == (
        "POST",
        "/organizations/1/query/records/advanced/paginated",
        {
            "params": {
                "projects": [2],
                "PageNumber": 2,
                "PageSize": 10,
                "textSearch": "sample",
            },
            "json": filters,
        },
    )
    assert sync_result == async_result
    assert async_result.items[0].properties == {"metadata": {"nexus": {"test_id": "abc"}}}
    assert async_result.page_info.has_previous is True
    assert async_result.page_info.has_next is False


@pytest.mark.parametrize(
    ("page", "page_size", "message"),
    [
        (0, 25, "page must be 1 or greater"),
        (1, 0, "page_size must be between 1 and 500"),
        (1, 501, "page_size must be between 1 and 500"),
    ],
)
async def test_advanced_query_validation_matches_between_sync_and_async(page, page_size, message):
    """Covers REQ-002-14."""
    sync_resource = SearchResource(SyncClient({}))
    async_resource = AsyncSearchResource(AsyncClient({}))

    with pytest.raises(ValueError, match=message):
        sync_resource.advanced_query([], [2], page=page, page_size=page_size)
    with pytest.raises(ValueError, match=message):
        await async_resource.advanced_query([], [2], page=page, page_size=page_size)
