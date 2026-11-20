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

"""The shared ``deeplynx://`` item URI format."""

import pytest

from prometheus_api.storage_client.uri import ItemRef, item_uri, parse_item_uri


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("deeplynx://organizations/1/projects/2/items/42", ItemRef(1, 2, 42)),
        ("deeplynx://organizations/7/projects/8/items/9/", ItemRef(7, 8, 9)),
        # fsspec strips the scheme before the filesystem sees the path
        ("organizations/1/projects/2/items/42", ItemRef(1, 2, 42)),
        ("/organizations/1/projects/2/items/42", ItemRef(1, 2, 42)),
        ("deeplynx://organizations/1/projects/2/items/x", None),
        ("deeplynx://organizations/x/projects/2/items/1", None),
        ("deeplynx://organizations/1/projects/2/files/1", None),
        ("deeplynx://organizations/1/projects/2/items", None),
        ("deeplynx://session-abc/moose/input.i", None),
        ("memory://organizations/1/projects/2/items/42", None),
        ("session-abc/moose/input.i", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_item_uri(value, expected):
    assert parse_item_uri(value) == expected


def test_item_uri_round_trips():
    uri = item_uri(1, 2, 42)
    assert uri == "deeplynx://organizations/1/projects/2/items/42"
    assert parse_item_uri(uri) == ItemRef(organization_id=1, project_id=2, item_id=42)
