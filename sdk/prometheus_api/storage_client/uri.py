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

"""The ``deeplynx://`` item URI format, in one place.

``send_deeplynx_artifact`` emits ``deeplynx://organizations/{org}/projects/{project}/items/{item}``.
The fsspec filesystem and the agent lineage code both read it back through
:func:`parse_item_uri`.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

SCHEME = "deeplynx"


class ItemRef(NamedTuple):
    """The organization, project and item that a ``deeplynx://`` item URI names."""

    organization_id: int
    project_id: int
    item_id: int


def item_uri(organization_id: int, project_id: int, item_id: int) -> str:
    """Return the ``deeplynx://`` URI of an item."""
    return f"{SCHEME}://organizations/{organization_id}/projects/{project_id}/items/{item_id}"


def parse_item_uri(value: Optional[str]) -> Optional[ItemRef]:
    """Parse a ``deeplynx://`` item URI, or the same path with the scheme already removed.

    Returns ``None`` for anything else: another scheme, another path shape, or IDs that
    are not integers. fsspec strips ``deeplynx://`` before the filesystem sees a path, so
    both forms are accepted.
    """
    text = str(value or "").strip()
    prefix = f"{SCHEME}://"
    if "://" in text:
        if not text.startswith(prefix):
            return None
        text = text[len(prefix) :]
    parts = text.strip("/").split("/")
    if len(parts) != 6 or parts[0::2] != ["organizations", "projects", "items"]:
        return None
    try:
        return ItemRef(int(parts[1]), int(parts[3]), int(parts[5]))
    except ValueError:
        return None
