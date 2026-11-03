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

"""Async search resource."""

from typing import Any, Dict, List, Optional
from ..models.item import Item, Tag
from ..models.pagination import Page, PageInfo
from .base import AsyncBaseResource


# GET /organizations/{org}/query/records/paginated: the server caps PageSize at 500, and
# ``sortBy`` is an enum (0 NameAZ, 1 NameZA, 2 DateNew, 3 DateOld).
_MAX_PAGE_SIZE = 500
_SORT_DATE_NEW = 2


class AsyncSearchResource(AsyncBaseResource):
    """Handles async search and query operations."""

    async def query(self, query: str, page: int = 1, page_size: int = 100) -> Page[Item]:
        """Perform a simple text search across items asynchronously."""
        params = {
            "userQuery": query,
            "projectIds": [self._client.config.project_id],
        }

        response = await self._client._request(
            "GET",
            f"/organizations/{self._client.config.organization_id}/query/records",
            params=params,
        )

        data = response.json()
        if isinstance(data, list):
            items = data
        else:
            items = data.get("records", [])

        return self._parse_search_results(items, page, page_size)

    async def advanced_query(
        self,
        filters: List[Dict[str, Any]],
        project_ids: List[int],
        text_search: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Page[Item]:
        """Perform an advanced, server-paginated search asynchronously."""
        if not 1 <= page_size <= 500:
            raise ValueError("page_size must be between 1 and 500")
        if page < 1:
            raise ValueError("page must be 1 or greater")

        params: Dict[str, Any] = {
            "projects": project_ids,
            "PageNumber": page,
            "PageSize": page_size,
        }
        if text_search:
            params["textSearch"] = text_search

        response = await self._client._request(
            "POST",
            f"/organizations/{self._client.config.organization_id}/query/records/advanced/paginated",
            params=params,
            json=filters,
        )

        return self._parse_paginated_results(response.json())

    async def by_tags(
        self, tags: List[str], match_all: bool = False, page: int = 1, page_size: int = 100
    ) -> Page[Item]:
        """Search for items by tags asynchronously."""
        params = {
            "tags": ",".join(tags),
            "match_all": "true" if match_all else "false",
            "page": page,
            "limit": page_size,
        }

        response = await self._client._request(
            "GET", f"{self._base_path}/records/search/tags", params=params
        )

        return self._parse_search_results(response.json(), page, page_size)

    async def recent(self, limit: int = 100) -> List[Item]:
        """Get the most recently updated items in the active project, newest first.

        Mirrors ``SearchResource.recent``: pages through the paginated, date-sorted query route
        until ``limit`` items are collected or the server has no further page.

        Raises:
            ValueError: If ``limit`` is less than 1
        """
        if limit < 1:
            raise ValueError("limit must be 1 or greater")

        page_size = min(limit, _MAX_PAGE_SIZE)
        items: List[Item] = []
        page = 1
        while len(items) < limit:
            response = await self._client._request(
                "GET",
                f"/organizations/{self._client.config.organization_id}/query/records/paginated",
                params={
                    "projectIds": [self._client.config.project_id],
                    "sortBy": _SORT_DATE_NEW,
                    "PageNumber": page,
                    "PageSize": page_size,
                },
            )
            result = self._parse_paginated_results(response.json())
            items.extend(result.items)
            if not result.page_info.has_next:
                break
            page += 1

        return items[:limit]

    def _parse_search_results(self, data: Any, page: int, page_size: int) -> Page[Item]:
        """Parse search results into a Page object."""
        if isinstance(data, list):
            item_list = data
            total_count = len(data)
        else:
            item_list = data.get("records", [])
            total_count = data.get("total", len(item_list))

        items = [self._parse_item(item_data) for item_data in item_list]

        page_info = PageInfo(
            page_number=page,
            page_size=page_size,
            total_count=total_count,
            has_next=page * page_size < total_count,
            has_previous=page > 1,
        )

        return Page(items=items, page_info=page_info)

    def _parse_paginated_results(self, data: Dict[str, Any]) -> Page[Item]:
        """Parse a PaginatedResponse<QueryRecordViewResponseDto> payload."""
        items = [self._parse_item(item_data) for item_data in (data.get("items") or [])]

        page_info = PageInfo(
            page_number=data["pageNumber"],
            page_size=data["pageSize"],
            total_count=data["totalCount"],
            has_next=data["hasNext"],
            has_previous=data["hasPrevious"],
        )

        return Page(items=items, page_info=page_info)

    def _parse_item(self, data: Dict[str, Any]) -> Item:
        """Parse item data from search results."""
        import json as json_lib
        from datetime import datetime

        properties = data.get("properties", {})
        if isinstance(properties, str):
            try:
                properties = json_lib.loads(properties)
            except (TypeError, ValueError):
                properties = {}

        timestamp_str = data.get("lastUpdatedAt")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        tags_data = data.get("tags")
        tags = []
        if tags_data:
            if isinstance(tags_data, str):
                try:
                    tags_list = json_lib.loads(tags_data)
                    tags = [Tag(id=t.get("id"), name=t.get("name", "")) for t in tags_list]
                except (TypeError, ValueError):
                    tags = []
            elif isinstance(tags_data, list):
                tags = [Tag(id=t.get("id"), name=t.get("name", "")) for t in tags_data]

        return Item(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            properties=properties,
            class_id=data.get("classId"),
            original_id=data.get("originalId"),
            created_at=timestamp,
            updated_at=timestamp,
            tags=tags,
            metatype_id=data.get("classId"),
            metatype_name=data.get("className"),
            data_source_id=data.get("dataSourceId"),
        )
