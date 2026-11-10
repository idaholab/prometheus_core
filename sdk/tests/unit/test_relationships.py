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

"""Tests for relationship parsing against DeepLynx edge responses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from prometheus_api.storage_client.async_resources.relationships import (
    AsyncRelationshipsResource,
)
from prometheus_api.storage_client.models.relationship import (
    Relationship,
    RelationshipCreate,
)
from prometheus_api.storage_client.resources.relationships import RelationshipsResource


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


def edge_payload(**overrides):
    """An edge as the DeepLynx v1 API returns it: ``properties`` is a JSON string."""
    payload = {
        "id": 11,
        "originId": 58,
        "destinationId": 59,
        "relationshipId": None,
        "dataSourceId": 91,
        "projectId": 67,
        "organizationId": 1,
        "properties": '{"strength": "strong"}',
        "lastUpdatedAt": "2026-10-28T22:44:04.4340215Z",
        "isArchived": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"strength": "strong"}', {"strength": "strong"}),
        ("{}", {}),
        ({"already": "a dict"}, {"already": "a dict"}),
        (None, {}),
        ("not json", {}),
        ("[1, 2]", {}),
    ],
)
def test_relationship_properties_accept_deeplynx_string_form(raw, expected):
    """Covers REQ-003-14: edge properties arrive as a JSON string or null."""
    relationship = Relationship(id=1, from_item_id=1, to_item_id=2, properties=raw)

    assert relationship.properties == expected


def test_relationship_create_still_requires_dict_properties():
    """The decoding applies to parsed responses, not to what callers send."""
    with pytest.raises(ValueError):
        RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="t", properties="{}")


async def test_create_parses_string_properties_in_sync_and_async():
    """Covers REQ-003-14: create must not fail on a stringified ``properties`` field."""
    request = RelationshipCreate(from_item_id=58, to_item_id=59, relationship_type="probe")

    sync = RelationshipsResource(SyncClient(edge_payload())).create(request)
    asynchronous = await AsyncRelationshipsResource(AsyncClient(edge_payload())).create(request)

    assert sync.model_dump() == asynchronous.model_dump()
    assert sync.id == 11
    assert (sync.from_item_id, sync.to_item_id) == (58, 59)
    assert sync.properties == {"strength": "strong"}
    assert sync.data_source_id == 91


async def test_get_parses_wrapped_and_string_properties_in_sync_and_async():
    """Covers REQ-003-10 and REQ-003-14: wrapped responses with string properties parse."""
    payload = {"value": edge_payload(properties="{}")}

    sync = RelationshipsResource(SyncClient(payload)).get(11)
    asynchronous = await AsyncRelationshipsResource(AsyncClient(payload)).get(11)

    assert sync.model_dump() == asynchronous.model_dump()
    assert sync.properties == {}


async def test_bulk_create_parses_string_properties_in_sync_and_async():
    """Covers REQ-003-14 for the bulk endpoint."""
    payload = [edge_payload(id=1), edge_payload(id=2, properties=None)]
    requests = [
        RelationshipCreate(from_item_id=58, to_item_id=59, relationship_type="a"),
        RelationshipCreate(from_item_id=59, to_item_id=58, relationship_type="b"),
    ]

    sync = RelationshipsResource(SyncClient(payload)).bulk_create(requests)
    asynchronous = await AsyncRelationshipsResource(AsyncClient(payload)).bulk_create(requests)

    assert [r.model_dump() for r in sync] == [r.model_dump() for r in asynchronous]
    assert [r.properties for r in sync] == [{"strength": "strong"}, {}]


async def test_item_relationship_listing_parses_string_properties_in_sync_and_async():
    """Covers REQ-003-14 for the simplified list format (``relatedRecordId``)."""
    payload = [
        {
            "id": 5,
            "relatedRecordId": 59,
            "name": "linked",
            "properties": '{"k": 1}',
            "relationshipId": 3,
            "dataSourceId": 91,
        }
    ]

    sync = RelationshipsResource(SyncClient(payload)).get_item_relationships(58, "outgoing")
    asynchronous = await AsyncRelationshipsResource(AsyncClient(payload)).get_item_relationships(
        58, "outgoing"
    )

    assert [r.model_dump() for r in sync] == [r.model_dump() for r in asynchronous]
    assert (sync[0].from_item_id, sync[0].to_item_id) == (58, 59)
    assert sync[0].properties == {"k": 1}
