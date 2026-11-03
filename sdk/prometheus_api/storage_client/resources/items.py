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

"""Items resource for synchronous operations."""

from typing import Dict, Iterator, List, Optional, Any
from ..models.item import Item, ItemCreate, ItemUpdate, Tag
from ..models.pagination import Page, PageInfo
from .base import BaseResource


class ItemsResource(BaseResource):
    """Handles operations related to items (records in DeepLynx)."""

    def create(self, item: ItemCreate) -> Item:
        """Create a new item.

        Args:
            item: Item creation data

        Returns:
            Created item with ID and timestamps

        Example:
            ```python
            item = client.items.create(ItemCreate(
                name="Test Item",
                properties={"key": "value"},
                tags=["important"]
            ))
            ```
        """
        # Prepare payload with snake_case field names for DeepLynx API
        payload: Dict[str, Any] = {
            "name": item.name,
            # Required field; the server rejects an empty string, so default to the name
            "description": item.description or item.name,
            "properties": item.properties,  # Required field
            "original_id": item.original_id or f"client-{item.name}-{id(item)}",  # Required field
        }

        if item.class_id:
            payload["class_id"] = item.class_id

        # Create the item (dataSourceId query parameter required)
        params = {"dataSourceId": self._client._get_data_source_id()}

        response = self._client._request(
            "POST", f"{self._base_path}/records", json=payload, params=params
        )

        item_data = response.json()

        # Handle tags if provided
        if item.tags:
            item_id = item_data.get("id")
            self.add_tags(item_id, item.tags)
            # Refetch to get tags
            return self.get(item_id)

        return self._parse_item(item_data)

    def get(self, item_id: int) -> Item:
        """Get an item by ID.

        Args:
            item_id: Item identifier

        Returns:
            Item data

        Raises:
            ItemNotFoundError: If item doesn't exist
        """
        response = self._client._request("GET", f"{self._base_path}/records/{item_id}")

        return self._parse_item(response.json())

    def update(self, item_id: int, update: ItemUpdate) -> Item:
        """Update an existing item.

        Args:
            item_id: Item identifier
            update: Fields to update

        Returns:
            Updated item

        Example:
            ```python
            updated = client.items.update(
                item_id=123,
                update=ItemUpdate(name="New Name")
            )
            ```
        """
        # Build payload with only provided fields
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
        response = self._client._request(
            "PUT", f"{self._base_path}/records/{item_id}", json=payload
        )

        return self._parse_item(response.json())

    def delete(self, item_id: int) -> None:
        """Delete an item.

        Args:
            item_id: Item identifier

        Raises:
            ItemNotFoundError: If item doesn't exist
        """
        self._client._request("DELETE", f"{self._base_path}/records/{item_id}")

    def list(
        self, page: int = 1, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Page[Item]:
        """List items with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            filters: Optional filters to apply

        Returns:
            Paginated list of items

        Example:
            ```python
            page = client.items.list(page=1, page_size=50)
            for item in page.items:
                print(item.name)
            ```
        """
        params: Dict[str, Any] = {"PageNumber": page, "PageSize": page_size}

        if filters:
            params.update(filters)

        response = self._client._request(
            "GET", f"{self._base_path}/records/paginated", params=params
        )

        return self._parse_paginated_items(response.json(), page, page_size)

    def iter_all(
        self, page_size: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> Iterator[Item]:
        """Iterate over all items with automatic pagination.

        Args:
            page_size: Number of items per page
            filters: Optional filters to apply

        Yields:
            Individual items

        Example:
            ```python
            for item in client.items.iter_all(page_size=50):
                print(item.name)
            ```
        """
        page = 1
        while True:
            result = self.list(page=page, page_size=page_size, filters=filters)
            yield from result.items

            if not result.page_info.has_next:
                break

            page += 1

    def bulk_create(self, items: List[ItemCreate]) -> List[Item]:
        """Create multiple items in a single request.

        Args:
            items: List of items to create

        Returns:
            List of created items

        Example:
            ```python
            items = client.items.bulk_create([
                ItemCreate(name="Item 1"),
                ItemCreate(name="Item 2")
            ])
            ```
        """
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

        params = {"dataSourceId": self._client._get_data_source_id()}

        response = self._client._request(
            "POST", f"{self._base_path}/records/bulk", json=payload, params=params
        )

        data = response.json()
        # API returns array directly
        if isinstance(data, list):
            return [self._parse_item(item_data) for item_data in data]
        else:
            return [self._parse_item(item_data) for item_data in data.get("records", [])]

    def add_tags(self, item_id: int, tags: List[str]) -> Item:
        """Add tags to an item.

        Args:
            item_id: Item identifier
            tags: List of tag names to add

        Returns:
            Updated item with tags

        Example:
            ```python
            item = client.items.add_tags(123, ["important", "reviewed"])
            ```
        """
        tag_ids = self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return self.get(item_id)
        for tag_id in tag_ids:
            self._client._request(
                "POST",
                f"{self._base_path}/records/{item_id}/tags",
                params={"tagId": int(tag_id)},
            )

        return self.get(item_id)

    def remove_tags(self, item_id: int, tags: List[str]) -> Item:
        """Remove tags from an item.

        Args:
            item_id: Item identifier
            tags: List of tag names to remove

        Returns:
            Updated item without specified tags

        Example:
            ```python
            item = client.items.remove_tags(123, ["old-tag"])
            ```
        """
        tag_ids = self._client.tags.resolve_ids(tags)
        if not tag_ids:
            return self.get(item_id)
        for tag_id in tag_ids:
            self._client._request(
                "DELETE",
                f"{self._base_path}/records/{item_id}/tags",
                params={"tagId": int(tag_id)},
            )

        return self.get(item_id)

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
        """Parse API response data into an Item model.

        Args:
            data: Raw API response data

        Returns:
            Parsed Item object
        """
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
            # Handle ISO format with optional microseconds
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
            created_at=timestamp,  # Use lastUpdatedAt as both created and updated
            updated_at=timestamp,
            tags=[Tag(id=t.get("id"), name=t.get("name", "")) for t in (data.get("tags") or [])],
            metatype_id=data.get("classId"),
            metatype_name=data.get("className"),
            data_source_id=data.get("dataSourceId"),
        )
