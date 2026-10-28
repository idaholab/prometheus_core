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

"""Tests for relationship parsing and edge typing on the sync and async storage clients.

DeepLynx is an ``httpx.MockTransport`` fake. Its payloads use the field names of the DeepLynx
C# DTOs (RelationshipResponseDto.cs, RelatedRecordsResponseDto.cs, EdgeResponseDto.cs and
CreateEdgeRequestDto.cs in deeplynx.models), serialized in camelCase. They are NOT captured
from a live DeepLynx; the live capture comes from the stack phase.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from prometheus_api.storage_client.async_client import AsyncStorageClient
from prometheus_api.storage_client.async_resources import relationships as async_relationships
from prometheus_api.storage_client.auth import AsyncAuthHandler, AuthHandler
from prometheus_api.storage_client.client import StorageClient
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.relationship import Relationship, RelationshipCreate
from prometheus_api.storage_client.resources import relationships as sync_relationships

BASE_URL = "http://deeplynx.test/api/v1"
RELATIONSHIPS_PATH = "/api/v1/projects/2/relationships"
EDGES_BULK_PATH = "/api/v1/organizations/1/projects/2/edges/bulk"
RECORD_EDGES_PATH = "/api/v1/organizations/1/projects/2/records/10/edges"


@pytest.fixture(autouse=True)
def fresh_relationship_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test empty process-wide relationship caches in both resource trees."""
    for module in (sync_relationships, async_relationships):
        monkeypatch.setattr(module, "_relationship_ids", {})
        monkeypatch.setattr(module, "_relationship_names", {})


class FakeDeepLynx:
    """Project relationships, record edges and bulk edge creation, recording every request."""

    def __init__(
        self,
        relationships: list[dict[str, Any]] | None = None,
        record_edges: list[dict[str, Any]] | None = None,
        bulk_response: list[dict[str, Any]] | None = None,
    ) -> None:
        self.relationships = list(relationships or [])
        self.record_edges = record_edges or []
        self.bulk_response = bulk_response
        self.requests: list[httpx.Request] = []

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests]

    def bulk_bodies(self) -> list[list[dict[str, Any]]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == EDGES_BULK_PATH]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == RELATIONSHIPS_PATH and request.method == "GET":
            return httpx.Response(200, json=self.relationships)
        if path == RELATIONSHIPS_PATH and request.method == "POST":
            # RelationshipResponseDto: a new project relationship without origin or destination.
            created = {
                "id": 100 + len(self.relationships),
                "name": json.loads(request.content)["name"],
                "originId": None,
                "destinationId": None,
            }
            self.relationships.append(created)
            return httpx.Response(200, json=created)
        if path == RECORD_EDGES_PATH:
            return httpx.Response(200, json=self.record_edges)
        if path == EDGES_BULK_PATH:
            if self.bulk_response is not None:
                return httpx.Response(200, json=self.bulk_response)
            # EdgeResponseDto: the edge carries only relationshipId, properties as a string.
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 70 + n,
                        "originId": edge["origin_id"],
                        "destinationId": edge["destination_id"],
                        "relationshipId": edge["relationship_id"],
                        "properties": json.dumps(edge["properties"]),
                    }
                    for n, edge in enumerate(json.loads(request.content))
                ],
            )
        return httpx.Response(404, json={"error": path})


def _config() -> ConnectionConfig:
    return ConnectionConfig(
        organization_id=1, project_id=2, data_source_id=3, base_url=BASE_URL, jwt_token="t"
    )


def _client(kind: str, fake: FakeDeepLynx) -> StorageClient | AsyncStorageClient:
    if kind == "sync":
        sync = StorageClient(_config())
        sync._http_client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(fake))
        sync._auth_handler = AuthHandler(sync.config, sync._http_client)
        return sync
    client = AsyncStorageClient(_config())
    client._http_client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(fake))
    client._auth_handler = AsyncAuthHandler(client.config, client._http_client)
    return client


async def _call(client: StorageClient | AsyncStorageClient, method: str, *args: Any) -> Any:
    result = getattr(client.relationships, method)(*args)
    return await result if inspect.isawaitable(result) else result


CLIENTS = pytest.mark.parametrize("kind", ["sync", "async"])

GENERATED = {"id": 5, "name": "generated", "originId": None, "destinationId": None}
OTHER = {"id": 6, "name": "input_to", "originId": None, "destinationId": None}


def _edges(name: str = "generated") -> list[RelationshipCreate]:
    return [
        RelationshipCreate(
            from_item_id=10, to_item_id=20, relationship_type=name, properties={"k": 1}
        )
    ]


def relationship(properties: Any) -> Relationship:
    return Relationship(from_item_id=10, to_item_id=20, properties=properties)


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        pytest.param("{}", {}, id="empty-json-string"),
        pytest.param('{"a": 1}', {"a": 1}, id="json-object-string"),
        pytest.param({"a": 1, "b": [2]}, {"a": 1, "b": [2]}, id="dict-unchanged"),
    ],
)
def test_relationship_properties_decode_json_string(
    properties: Any, expected: dict[str, Any]
) -> None:
    """Covers REQ-003-10."""
    assert relationship(properties).properties == expected


def test_relationship_properties_invalid_json_string_fails_validation() -> None:
    """Covers REQ-003-10."""
    with pytest.raises(ValidationError):
        relationship("{not json")


@CLIENTS
async def test_bulk_create_parses_string_properties(kind: str) -> None:
    """Covers REQ-003-10: EdgeResponseDto.cs returns ``properties`` as a JSON string."""
    edge = {"id": 7, "originId": 10, "destinationId": 20, "relationshipId": 5}
    fake = FakeDeepLynx([GENERATED], bulk_response=[{**edge, "properties": "{}"}])

    created = await _call(_client(kind, fake), "bulk_create", _edges())

    assert [(r.id, r.properties) for r in created] == [(7, {})]


@CLIENTS
async def test_bulk_create_sends_listed_relationship_id(kind: str) -> None:
    """Covers REQ-003-10.

    CreateEdgeRequestDto.cs:14 takes ``relationship_id``; EdgeBusiness.cs (:200, :330-333)
    ignores ``relationship_name``. RelationshipProjectController.cs:43-47 lists the project
    relationships at ``/projects/{p}/relationships``.
    """
    fake = FakeDeepLynx([OTHER, GENERATED])

    await _call(_client(kind, fake), "bulk_create", _edges())

    assert fake.calls() == [("GET", RELATIONSHIPS_PATH), ("POST", EDGES_BULK_PATH)]
    bulk = fake.requests[-1]
    assert bulk.url.params["dataSourceId"] == "3"
    assert fake.bulk_bodies() == [
        [{"origin_id": 10, "destination_id": 20, "relationship_id": 5, "properties": {"k": 1}}]
    ]


@CLIENTS
async def test_bulk_create_creates_missing_relationship(kind: str) -> None:
    """Covers REQ-003-10: RelationshipProjectController.cs:103-107 creates ``{"name": X}``."""
    fake = FakeDeepLynx([OTHER])

    await _call(_client(kind, fake), "bulk_create", _edges())

    assert fake.calls() == [
        ("GET", RELATIONSHIPS_PATH),
        ("POST", RELATIONSHIPS_PATH),
        ("POST", EDGES_BULK_PATH),
    ]
    assert json.loads(fake.requests[1].content) == {"name": "generated"}
    created_id = fake.relationships[-1]["id"]
    assert [edge["relationship_id"] for edge in fake.bulk_bodies()[0]] == [created_id]


@CLIENTS
async def test_bulk_create_reuses_cached_relationship_id(kind: str) -> None:
    """Covers REQ-003-10: the second request for a name makes no second relationships GET."""
    fake = FakeDeepLynx([GENERATED])
    client = _client(kind, fake)

    await _call(client, "bulk_create", _edges())
    await _call(client, "bulk_create", _edges())

    assert fake.calls() == [
        ("GET", RELATIONSHIPS_PATH),
        ("POST", EDGES_BULK_PATH),
        ("POST", EDGES_BULK_PATH),
    ]
    assert [body[0]["relationship_id"] for body in fake.bulk_bodies()] == [5, 5]


@CLIENTS
async def test_bulk_create_maps_relationship_id_to_cached_name(kind: str) -> None:
    """Covers REQ-003-10: EdgeResponseDto.cs:17 carries only ``relationshipId``."""
    fake = FakeDeepLynx([GENERATED])

    created = await _call(_client(kind, fake), "bulk_create", _edges())

    assert [(r.from_item_id, r.to_item_id, r.relationship_type) for r in created] == [
        (10, 20, "generated")
    ]


@CLIENTS
@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param({"relationshipName": "generated"}, "generated", id="relationshipName"),
        pytest.param({"relationshipName": None}, "", id="relationshipName-null"),
        pytest.param({"name": "generated"}, "generated", id="name-fallback"),
    ],
)
async def test_get_item_relationships_reads_edge_type(
    kind: str, fields: dict[str, Any], expected: str
) -> None:
    """Covers REQ-003-09 and REQ-003-10.

    RelatedRecordsResponseDto.cs:5-8 (filled at GraphBusiness.cs:120-128) has a nullable
    ``relationshipName``.
    """
    edge = {
        "relatedRecordName": "dataset",
        "relatedRecordId": 20,
        "relatedRecordProjectId": 2,
        **fields,
    }
    fake = FakeDeepLynx(record_edges=[edge])

    found = await _call(_client(kind, fake), "get_item_relationships", 10, "outgoing")

    assert fake.calls() == [("GET", RECORD_EDGES_PATH)]
    assert fake.requests[0].url.params["isOrigin"] == "true"
    assert [(r.from_item_id, r.to_item_id, r.relationship_type) for r in found] == [
        (10, 20, expected)
    ]


@CLIENTS
async def test_bulk_create_without_edges_raises(kind: str) -> None:
    """Covers REQ-003-10."""
    fake = FakeDeepLynx([GENERATED], bulk_response=[])

    with pytest.raises(ValueError, match="DeepLynx created no edges"):
        await _call(_client(kind, fake), "bulk_create", _edges())

    assert fake.calls() == [("GET", RELATIONSHIPS_PATH), ("POST", EDGES_BULK_PATH)]
