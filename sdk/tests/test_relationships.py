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
        # Types used by the parsing tests resolve from the cache, not the network.
        self._relationship_type_ids = {"probe": 3, "t": 3, "a": 4, "b": 5}

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


class RoutedClient:
    """Fake DeepLynx with a project relationship-type table and an edge endpoint."""

    def __init__(self, types=None, create_error=None):
        self.config = SimpleNamespace(organization_id=1, project_id=2)
        self._relationship_type_ids = {}
        self.types = list(types or [])
        self.create_error = create_error
        self.calls = []

    def _get_data_source_id(self):
        return 7

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/projects/2/relationships" and method == "GET":
            return Response(list(self.types))
        if path == "/projects/2/relationships" and method == "POST":
            if self.create_error is not None:
                self.types.append({"id": 99, "name": kwargs["json"]["name"]})
                raise self.create_error
            created = {"id": 40 + len(self.types), "name": kwargs["json"]["name"]}
            self.types.append(created)
            return Response(created)
        body = kwargs.get("json")
        if path.endswith("/edges/bulk"):
            return Response([edge_payload(relationshipId=e.get("relationship_id")) for e in body])
        return Response(edge_payload(relationshipId=body.get("relationship_id")))

    def edge_bodies(self):
        return [kwargs["json"] for _, path, kwargs in self.calls if "/edges" in path]


class AsyncRoutedClient(RoutedClient):
    async def _get_data_source_id(self):
        return 7

    async def _request(self, method, path, **kwargs):
        return RoutedClient._request(self, method, path, **kwargs)


def _named(name="input_to", **kw):
    return RelationshipCreate(from_item_id=58, to_item_id=59, relationship_type=name, **kw)


async def test_create_sends_relationship_id_for_existing_type_in_sync_and_async():
    """Covers REQ-003-15: an edge's type is sent as the project relationship ID."""
    existing = [{"id": 5, "name": "input_to"}]
    sync = RoutedClient(types=existing)
    RelationshipsResource(sync).create(_named())
    asynchronous = AsyncRoutedClient(types=existing)
    await AsyncRelationshipsResource(asynchronous).create(_named())

    for client in (sync, asynchronous):
        body = client.edge_bodies()[0]
        assert body["relationship_id"] == 5
        assert "name" not in body
        assert not any(m == "POST" and p.endswith("/relationships") for m, p, _ in client.calls)


async def test_missing_type_is_created_once_and_cached():
    """Covers REQ-003-15: a missing type is created, then reused from the client cache."""
    client = AsyncRoutedClient()
    resource = AsyncRelationshipsResource(client)

    await resource.create(_named())
    await resource.create(_named())

    creates = [
        kw["json"] for m, p, kw in client.calls if m == "POST" and p.endswith("/relationships")
    ]
    assert creates == [{"name": "input_to", "description": "input_to"}]
    assert [b["relationship_id"] for b in client.edge_bodies()] == [40, 40]
    lookups = [p for m, p, _ in client.calls if m == "GET"]
    assert lookups == ["/projects/2/relationships"]


def test_type_created_concurrently_is_looked_up_instead_of_failing():
    """Covers REQ-003-15: losing the create race reuses the winner's type."""
    from prometheus_api.storage_client.exceptions import APIError

    client = RoutedClient(create_error=APIError("already exists", status_code=500))

    RelationshipsResource(client).create(_named())

    assert client.edge_bodies()[0]["relationship_id"] == 99


def test_type_create_failure_propagates_when_type_still_missing():
    from prometheus_api.storage_client.exceptions import APIError

    class Failing(RoutedClient):
        def _request(self, method, path, **kwargs):
            if method == "POST" and path.endswith("/relationships"):
                raise APIError("boom", status_code=500)
            return super()._request(method, path, **kwargs)

    with pytest.raises(APIError):
        RelationshipsResource(Failing()).create(_named())


def test_archived_type_is_not_reused():
    client = RoutedClient(types=[{"id": 5, "name": "input_to", "isArchived": True}])

    RelationshipsResource(client).create(_named())

    assert client.edge_bodies()[0]["relationship_id"] == 41


async def test_bulk_create_resolves_each_type_in_sync_and_async():
    """Covers REQ-003-15 for the bulk endpoint."""
    rels = [_named("input_to"), _named("generated"), _named("input_to")]
    sync = RoutedClient()
    RelationshipsResource(sync).bulk_create(rels)
    asy = AsyncRoutedClient()
    await AsyncRelationshipsResource(asy).bulk_create(rels)

    for client in (sync, asy):
        ids = [e["relationship_id"] for e in client.edge_bodies()[0]]
        assert ids == [40, 41, 40]


def test_untyped_edge_sends_no_relationship_id():
    client = RoutedClient()

    RelationshipsResource(client).create(_named(""))

    assert "relationship_id" not in client.edge_bodies()[0]
    assert not [c for c in client.calls if c[1].endswith("/relationships")]


def test_listed_edges_read_relationship_name():
    """Covers REQ-003-15: names come back from the record-edges listing."""
    listing = [{"relatedRecordId": 59, "relationshipName": "generated", "relationshipId": 3}]

    (edge,) = RelationshipsResource(SyncClient(listing)).get_item_relationships(58, "outgoing")

    assert edge.relationship_type == "generated"
    assert (edge.from_item_id, edge.to_item_id) == (58, 59)
