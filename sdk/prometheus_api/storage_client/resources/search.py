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

"""Search resource for synchronous operations."""

from typing import Any, Dict, List, Optional
from ..models.item import Item
from ..models.pagination import Page, PageInfo
from .base import BaseResource


# GET /organizations/{org}/query/records/paginated: the server caps PageSize at 500, and
# ``sortBy`` is an enum (0 NameAZ, 1 NameZA, 2 DateNew, 3 DateOld).
_MAX_PAGE_SIZE = 500
_SORT_DATE_NEW = 2


class SearchResource(BaseResource):
    """Handles search and query operations."""

    def query(self, query: str, page: int = 1, page_size: int = 100) -> Page[Item]:
        """Perform a simple text search across items.

        Args:
            query: Search query string
            page: Page number (1-indexed)
            page_size: Number of results per page

        Returns:
            Paginated search results

        Example:
            ```python
            results = client.search.query("experiment data", page_size=50)
            for item in results.items:
                print(item.name)
            ```
        """
        params = {
            "userQuery": query,
            "projectIds": [self._client.config.project_id],
        }

        response = self._client._request(
            "GET",
            f"/organizations/{self._client.config.organization_id}/query/records",
            params=params,
        )

        data = response.json()

        # API returns list directly
        if isinstance(data, list):
            items = data
        else:
            items = data.get("records", [])

        return self._parse_search_results(items, page, page_size)

    def advanced_query(
        self,
        filters: List[Dict[str, Any]],
        project_ids: List[int],
        text_search: Optional[str] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Page:
        """Perform an advanced, server-paginated search with structured filters.

        Args:
            filters: List of filter component dicts matching CustomQueryRequestDto, e.g.
                [{"Filter": "properties", "Operator": "LIKE", "Value": "active"},
                 {"Filter": "priority", "Operator": ">", "Value": "5", "Connector": "AND"}]
            project_ids: Project IDs to search across
            text_search: Optional full text search phrase
            page: Page number (1-indexed)
            page_size: Results per page (server max is 500)

        Returns:
            Paginated search results
        """
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

        response = self._client._request(
            "POST",
            f"/organizations/{self._client.config.organization_id}/query/records/advanced/paginated",
            params=params,
            json=filters,
        )

        return self._parse_paginated_results(response.json())

    def by_tags(
        self, tags: List[str], match_all: bool = False, page: int = 1, page_size: int = 100
    ) -> Page[Item]:
        """Search for items by tags.

        Args:
            tags: List of tag names to search for
            match_all: If True, items must have all tags; if False, any tag matches
            page: Page number (1-indexed)
            page_size: Number of results per page

        Returns:
            Paginated search results

        Example:
            ```python
            # Find items with any of these tags
            results = client.search.by_tags(["important", "urgent"])

            # Find items with all of these tags
            results = client.search.by_tags(["important", "urgent"], match_all=True)
            ```
        """
        params = {
            "tags": ",".join(tags),
            "match_all": "true" if match_all else "false",
            "page": page,
            "limit": page_size,
        }

        response = self._client._request(
            "GET", f"{self._base_path}/records/search/tags", params=params
        )

        return self._parse_search_results(response.json(), page, page_size)

    def recent(self, limit: int = 100) -> List[Item]:
        """Get the most recently updated items in the active project, newest first.

        Pages through ``GET /organizations/{org}/query/records/paginated`` sorted by date,
        ``_MAX_PAGE_SIZE`` items at a time, until ``limit`` items are collected or the server
        has no further page.

        Args:
            limit: Maximum number of items to return (at least 1)

        Returns:
            List of recent items, most recently updated first

        Raises:
            ValueError: If ``limit`` is less than 1

        Example:
            ```python
            recent_items = client.search.recent(limit=50)
            ```
        """
        if limit < 1:
            raise ValueError("limit must be 1 or greater")

        page_size = min(limit, _MAX_PAGE_SIZE)
        items: List[Item] = []
        page = 1
        while len(items) < limit:
            response = self._client._request(
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
        """Parse search results into a Page object.

        Args:
            data: Raw API response data (list or dict)
            page: Current page number
            page_size: Page size

        Returns:
            Paginated results
        """
        # Handle both list and dict responses
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
        """Parse a PaginatedResponse<QueryRecordViewResponseDto> payload.

        Args:
            data: Raw API response matching the C# PaginatedResponse<T> shape:
                {"items": [...], "pageNumber": int, "pageSize": int,
                "totalCount": int, "totalPages": int,
                "hasPrevious": bool, "hasNext": bool}

        Returns:
            Paginated results
        """
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
        """Parse item data from search results.

        Args:
            data: Raw item data

        Returns:
            Parsed Item object

        Note:
            DeepLynx API returns camelCase field names.
        """
        from ..models.item import Tag
        from datetime import datetime
        import json as json_lib

        # Parse timestamp
        timestamp_str = data.get("lastUpdatedAt")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Parse properties (API returns as JSON string)
        properties = data.get("properties", {})
        if isinstance(properties, str):
            try:
                properties = json_lib.loads(properties)
            except (TypeError, ValueError):
                properties = {}

        # Parse tags (API returns as JSON string)
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
