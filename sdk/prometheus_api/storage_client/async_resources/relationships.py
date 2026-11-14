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

"""Async relationships resource."""

from typing import Any, Dict, List, Optional
from ..models.relationship import Relationship, RelationshipCreate
from ..exceptions import StorageClientError
from .base import AsyncBaseResource


class AsyncRelationshipsResource(AsyncBaseResource):
    """Handles async operations related to relationships between items."""

    async def create(self, relationship: RelationshipCreate) -> Relationship:
        """Create a new relationship between two items asynchronously."""
        payload = await self._edge_payload(relationship)

        params: Dict[str, Any] = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/edges", json=payload, params=params
        )

        data = response.json()

        # Some DeepLynx endpoints wrap response in 'value' field
        if isinstance(data, dict) and "value" in data:
            data = data["value"]

        return self._parse_relationship(data)

    async def _edge_payload(self, relationship: RelationshipCreate) -> Dict[str, Any]:
        """Build an edge-create body. DeepLynx types an edge only by ``relationship_id``."""
        payload: Dict[str, Any] = {
            "origin_id": relationship.from_item_id,
            "destination_id": relationship.to_item_id,
            "properties": relationship.properties,
        }
        if relationship.relationship_type:
            payload["relationship_id"] = await self.get_or_create_relationship_type(
                relationship.relationship_type
            )
        return payload

    async def get_or_create_relationship_type(self, name: str) -> int:
        """Return the project's relationship-type ID for *name*, creating the type if needed.

        DeepLynx stores an edge's type as a project-level relationship record, and an
        edge-create request that names a missing type fails, so the type is created
        first. IDs are cached per client. A concurrent creator can win the race; the
        type is then looked up again rather than failing.
        """
        cache = self._client._relationship_type_ids
        if name in cache:
            return cache[name]
        type_id = await self._find_relationship_type(name)
        if type_id is None:
            try:
                response = await self._client._request(
                    "POST",
                    self._relationship_types_path,
                    json={"name": name, "description": name},
                )
                type_id = int(response.json()["id"])
            except StorageClientError:
                type_id = await self._find_relationship_type(name)
                if type_id is None:
                    raise
        cache[name] = type_id
        return type_id

    async def _find_relationship_type(self, name: str) -> Optional[int]:
        response = await self._client._request("GET", self._relationship_types_path)
        data = response.json()
        for relationship_type in data if isinstance(data, list) else []:
            if relationship_type.get("name") == name and not relationship_type.get("isArchived"):
                return int(relationship_type["id"])
        return None

    @property
    def _relationship_types_path(self) -> str:
        return f"/projects/{self._client.config.project_id}/relationships"

    async def get(self, relationship_id: int) -> Relationship:
        """Get a relationship by ID asynchronously."""
        response = await self._client._request("GET", f"{self._base_path}/edges/{relationship_id}")

        data = response.json()

        # Some DeepLynx endpoints wrap response in 'value' field
        if isinstance(data, dict) and "value" in data:
            data = data["value"]

        return self._parse_relationship(data)

    async def delete(self, relationship_id: int) -> None:
        """Delete a relationship asynchronously."""
        await self._client._request("DELETE", f"{self._base_path}/edges/{relationship_id}")

    async def bulk_create(self, relationships: List[RelationshipCreate]) -> List[Relationship]:
        """Create multiple relationships in a single request asynchronously."""
        payload = [await self._edge_payload(rel) for rel in relationships]

        params = {"dataSourceId": await self._client._get_data_source_id()}

        response = await self._client._request(
            "POST", f"{self._base_path}/edges/bulk", json=payload, params=params
        )

        data = response.json()

        # API may return edges directly as a list or wrapped in a dict
        if isinstance(data, list):
            edges = data
        else:
            edges = data.get("edges", [])

        return [self._parse_relationship(rel_data) for rel_data in edges]

    async def get_item_relationships(
        self, item_id: int, direction: Optional[str] = None
    ) -> List[Relationship]:
        """Get all relationships for an item asynchronously."""
        # If direction not specified, get both outgoing and incoming
        if direction is None:
            outgoing = await self.get_item_relationships(item_id, "outgoing")
            incoming = await self.get_item_relationships(item_id, "incoming")
            return outgoing + incoming

        params: Dict[str, Any] = {
            "page": 1,
            "pageSize": 100,  # Maximum allowed by DeepLynx API
        }

        # Map direction to isOrigin boolean
        # outgoing: this item is the origin (isOrigin=true)
        # incoming: this item is the destination (isOrigin=false)
        if direction == "outgoing":
            params["isOrigin"] = "true"
        elif direction == "incoming":
            params["isOrigin"] = "false"

        response = await self._client._request(
            "GET", f"{self._base_path}/records/{item_id}/edges", params=params
        )

        data = response.json()

        # API may return edges directly as a list or wrapped in a dict
        if isinstance(data, list):
            edges = data
        else:
            edges = data.get("edges", [])

        # Parse relationships, handling different response formats
        relationships = []
        for rel_data in edges:
            # Check if this is the simplified format (from list endpoint)
            if "relatedRecordId" in rel_data:
                # Simplified format: reconstruct full relationship
                if direction == "outgoing":
                    from_id = item_id
                    to_id = rel_data.get("relatedRecordId")
                else:  # incoming
                    from_id = rel_data.get("relatedRecordId")
                    to_id = item_id

                relationships.append(
                    Relationship(
                        id=rel_data.get("id", 0),
                        from_item_id=from_id,
                        to_item_id=to_id,
                        relationship_type=rel_data.get("relationshipName")
                        or rel_data.get("name")
                        or "",
                        properties=rel_data.get("properties", {}),
                        created_at=rel_data.get("createdAt"),
                        updated_at=rel_data.get("lastUpdatedAt"),
                        relationship_pair_id=rel_data.get("relationshipId"),
                        data_source_id=rel_data.get("dataSourceId"),
                    )
                )
            else:
                # Full format: use standard parser
                relationships.append(self._parse_relationship(rel_data))

        return relationships

    async def get_item_graph(self, item_id: int, depth: int = 1) -> Dict[str, Any]:
        """Get a graph of relationships starting from an item asynchronously."""
        response = await self._client._request(
            "GET", f"{self._base_path}/records/{item_id}/graph", params={"depth": depth}
        )

        data = response.json()
        return data if isinstance(data, dict) else {"result": data}

    def _parse_relationship(self, data: Dict[str, Any]) -> Relationship:
        """Parse API response data into a Relationship model.

        Note:
            created_at and updated_at are optional as some DeepLynx
            deployments may not return these fields.

        Raises:
            ValueError: If required fields are missing from API response
        """
        # DeepLynx API returns camelCase field names per API docs
        from_item_id = data.get("originId")
        to_item_id = data.get("destinationId")

        # Validate required fields
        if from_item_id is None or to_item_id is None:
            import json
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                f"Failed to parse relationship - missing node IDs. Response data: {json.dumps(data, indent=2)}"
            )
            raise ValueError(
                f"API response missing required node ID fields. "
                f"Response keys: {list(data.keys())}. "
                f"Expected 'originId' and 'destinationId'."
            )

        return Relationship(
            id=data["id"],
            from_item_id=from_item_id,
            to_item_id=to_item_id,
            relationship_type=data.get("relationshipName") or data.get("name") or "",
            properties=data.get("properties", {}),
            created_at=data.get("createdAt"),
            updated_at=data.get("lastUpdatedAt"),
            relationship_pair_id=data.get("relationshipId"),
            data_source_id=data.get("dataSourceId"),
        )
