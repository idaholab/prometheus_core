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

"""Async items resource."""

import logging
from typing import AsyncIterator, Dict, List, Optional, Any
from importlib.metadata import version as pkg_version
from ..models.item import Item, ItemCreate, ItemUpdate, Tag
from ..models.pagination import Page, PageInfo
from .base import AsyncBaseResource

logger = logging.getLogger(__name__)


class AsyncItemsResource(AsyncBaseResource):
    """Handles async operations related to items."""

    async def create(self, item: ItemCreate) -> Item:
        """Create a new item asynchronously."""
        payload: Dict[str, Any] = {
            "name": item.name,
            # Required field; the server rejects an empty string, so default to the name
            "description": item.description or item.name,
            "properties": item.properties,
            "original_id": item.original_id or f"client-{item.name}-{id(item)}",
        }

        if item.class_id:
            payload["class_id"] = item.class_id

        params = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/records", json=payload, params=params
        )

        item_data = response.json()

        if item.tags:
            item_id = item_data.get("id")
            await self.add_tags(item_id, item.tags)
            return await self.get(item_id)

        return self._parse_item(item_data)

    async def get(self, item_id: int) -> Item:
        """Get an item by ID asynchronously."""
        response = await self._client._request("GET", f"{self._base_path}/records/{item_id}")

        return self._parse_item(response.json())

    async def update(self, item_id: int, update: ItemUpdate) -> Item:
        """Update an existing item asynchronously."""
        payload: Dict[str, Any] = {}

        if update.name is not None:
            payload["name"] = update.name
        if update.description is not None:
            payload["description"] = update.description
        if update.properties is not None:
            payload["properties"] = update.properties
        if update.class_id is not None:
            payload["class_id"] = update.class_id
        if update.original_id is not None:
            payload["original_id"] = update.original_id

        # Use PUT for full update (PATCH tries to unarchive which can fail)
        response = await self._client._request(
            "PUT", f"{self._base_path}/records/{item_id}", json=payload
        )

        return self._parse_item(response.json())

    async def delete(self, item_id: int) -> None:
        """Delete an item asynchronously."""
        await self._client._request("DELETE", f"{self._base_path}/records/{item_id}")

    async def list(
        self, page: int = 1, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Page[Item]:
        """List items with pagination asynchronously."""
        params: Dict[str, Any] = {"PageNumber": page, "PageSize": page_size}

        if filters:
            params.update(filters)

        response = await self._client._request(
            "GET", f"{self._base_path}/records/paginated", params=params
        )

        return self._parse_paginated_items(response.json(), page, page_size)

    async def iter_all(
        self, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Item]:
        """Iterate over all items with automatic pagination asynchronously."""
        page = 1
        while True:
            result = await self.list(page=page, page_size=page_size, filters=filters)
            for item in result.items:
                yield item

            if not result.page_info.has_next:
                break

            page += 1

    async def bulk_create(self, items: List[ItemCreate]) -> List[Item]:
        """Create multiple items in a single request asynchronously."""
        payload = [
            {
                "name": item.name,
                "description": item.description or item.name,
                "properties": item.properties,
                "original_id": item.original_id or f"client-{item.name}-{i}",
                "class_id": item.class_id,
            }
            for i, item in enumerate(items)
        ]

        params = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/records/bulk", json=payload, params=params
        )

        data = response.json()
        # API returns array directly
        if isinstance(data, list):
            return [self._parse_item(item_data) for item_data in data]
        else:
            return [self._parse_item(item_data) for item_data in data.get("records", [])]

    async def add_tags(self, item_id: int, tags: List[str]) -> Item:
        """Add tags to an item asynchronously. Tag names are resolved to IDs."""
        tag_ids = await self._client.tags.resolve_ids(tags)
        logger.info(
            "prometheus-api %s add_tags: item=%s names=%r resolved_ids=%r",
            pkg_version("prometheus-api"),
            item_id,
            tags,
            tag_ids,
        )
        if not tag_ids:
            return await self.get(item_id)
        for tag_id in tag_ids:
            await self._client._request(
                "POST",
                f"{self._base_path}/records/{item_id}/tags",
                params={"tagId": int(tag_id)},
            )

        return await self.get(item_id)

    async def remove_tags(self, item_id: int, tags: List[str]) -> Item:
        """Remove tags from an item asynchronously."""
        tag_ids = await self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return await self.get(item_id)
        for tag_id in tag_ids:
            await self._client._request(
                "DELETE",
                f"{self._base_path}/records/{item_id}/tags",
                params={"tagId": int(tag_id)},
            )

        return await self.get(item_id)

    def _parse_paginated_items(self, data: Any, page: int, page_size: int) -> Page[Item]:
        """Parse a ``PaginatedResponse<RecordResponseDto>`` into a ``Page[Item]``.

        The server returns ``items: null`` for an empty result, so a missing or null ``items``
        is an empty page. The server's own paging numbers are used when present.
        """
        items = [self._parse_item(item_data) for item_data in (data.get("items") or [])]
        total_count = data.get("totalCount", len(items))
        page_info = PageInfo(
            page_number=data.get("pageNumber", page),
            page_size=data.get("pageSize", page_size),
            total_count=total_count,
            has_next=data.get("hasNext", False),
            has_previous=data.get("hasPrevious", page > 1),
        )
        return Page(items=items, page_info=page_info)

    def _parse_item(self, data: Dict[str, Any]) -> Item:
        """Parse API response data into an Item model."""
        import json as json_lib
        from datetime import datetime

        # Parse properties if it's a JSON string
        properties = data.get("properties", {})
        if isinstance(properties, str):
            try:
                properties = json_lib.loads(properties)
            except (TypeError, ValueError):
                properties = {}

        # Parse timestamp
        timestamp_str = data.get("lastUpdatedAt")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Map DeepLynx fields to our generic model (API uses camelCase in response)
        return Item(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            properties=properties,
            class_id=data.get("classId"),
            original_id=data.get("originalId"),
            created_at=timestamp,
            updated_at=timestamp,
            tags=[Tag(id=t.get("id"), name=t.get("name", "")) for t in (data.get("tags") or [])],
            metatype_id=data.get("classId"),
            metatype_name=data.get("className"),
            data_source_id=data.get("dataSourceId"),
        )
