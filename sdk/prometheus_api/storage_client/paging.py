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

"""What the sync and async resources share about DeepLynx's paginated records routes.

``GET .../records/paginated`` (items) and ``GET /organizations/{org}/query/records/paginated``
(search) answer with the same ``PaginatedResponse`` envelope and accept the same paging limits.
The sync and async resources must behave the same, so the rules live here once.
"""

from typing import Any, Callable, Dict, List, Optional

from .exceptions import StorageClientError
from .models.item import Item
from .models.pagination import Page, PageInfo

# The server refuses a PageSize above 500 with a bare HTTP 400.
MAX_PAGE_SIZE = 500

# ``sortBy`` of the query route is an enum: 0 NameAZ, 1 NameZA, 2 DateNew, 3 DateOld.
SORT_DATE_NEW = 2

# Query parameters ``GET .../records/paginated`` accepts besides the paging ones. The server
# ignores any other parameter without an error, so an unknown filter would silently return
# unfiltered results.
LIST_FILTER_KEYS = frozenset({"dataSourceId", "fileType", "hideArchived", "isInsightEligible"})

_PAGING_KEYS = ("pageNumber", "pageSize", "totalCount", "hasNext", "hasPrevious")


def check_list_filters(filters: Optional[Dict[str, Any]]) -> None:
    """Raise ``ValueError`` for a filter key the paginated records route does not accept."""
    unknown = sorted(set(filters or {}) - LIST_FILTER_KEYS)
    if unknown:
        raise ValueError(
            f"Unsupported item filter(s) {unknown}: the server would ignore them and return "
            f"unfiltered items. Supported: {sorted(LIST_FILTER_KEYS)}. To filter on properties, "
            "use search.advanced_query(...)."
        )


def check_page_size(page_size: int) -> None:
    """Raise ``ValueError`` for a page size the records route rejects."""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")


def check_paginated_body(data: Any, route: str) -> Dict[str, Any]:
    """Return ``data`` if it is a paginated JSON object, else raise ``StorageClientError``.

    A paginated route that answers 200 with a list, a string or an HTML page would otherwise
    fail later with an ``AttributeError`` that hides which route misbehaved. An object that
    lacks a paging field is rejected too: a missing ``hasNext`` read as false would end paging
    after one page with no error. ``items`` may be null or absent (an empty project).
    """
    if not isinstance(data, dict):
        raise StorageClientError(
            f"Unexpected {route} response: expected a JSON object, got {type(data).__name__}"
        )
    missing = [key for key in _PAGING_KEYS if key not in data]
    if missing:
        raise StorageClientError(f"Unexpected {route} response: missing {', '.join(missing)}")
    return data


def parse_paginated(
    data: Any, route: str, parse_item: Callable[[Dict[str, Any]], Item]
) -> Page[Item]:
    """Parse a ``PaginatedResponse`` of records into a ``Page[Item]``.

    The server returns ``items: null`` for an empty result, so a missing or null ``items`` is an
    empty page. The paging fields are required and are taken from the server.

    Raises:
        StorageClientError: If the body is not an object or lacks a paging field
    """
    data = check_paginated_body(data, route)
    items: List[Item] = [parse_item(item_data) for item_data in (data.get("items") or [])]
    page_info = PageInfo(
        page_number=data["pageNumber"],
        page_size=data["pageSize"],
        total_count=data["totalCount"],
        has_next=data["hasNext"],
        has_previous=data["hasPrevious"],
    )
    return Page(items=items, page_info=page_info)
