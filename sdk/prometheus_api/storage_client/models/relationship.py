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

"""Relationship models for the storage client."""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class RelationshipBase(BaseModel):
    """Base model for relationship data."""

    from_item_id: int = Field(..., description="Source item ID")
    to_item_id: int = Field(..., description="Target item ID")
    relationship_type: str = Field(..., description="Type of relationship")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Custom properties for the relationship"
    )

    model_config = {"from_attributes": True}

    @field_validator("properties", mode="before")
    @classmethod
    def _decode_json_properties(cls, value: Any) -> Any:
        """Decode the JSON-string ``properties`` that some DeepLynx versions return."""
        if not isinstance(value, str):
            return value
        if not value.strip():
            return {}
        decoded = json.loads(value)
        return {} if decoded is None else decoded


class RelationshipCreate(RelationshipBase):
    """Model for creating a new relationship."""

    pass


class Relationship(RelationshipBase):
    """Full relationship model including system fields."""

    id: int = Field(default=0, description="Relationship ID")
    relationship_type: str = Field(default="", description="Type of relationship")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    # System fields (from DeepLynx)
    relationship_pair_id: Optional[int] = Field(None, description="Internal relationship pair ID")
    data_source_id: Optional[int] = Field(None, description="Source data identifier")

    model_config = {"from_attributes": True}


class BulkRelationshipCreate(BaseModel):
    """Wrapper for bulk relationship creation operations."""

    relationships: List[RelationshipCreate] = Field(
        ..., description="List of relationships to create"
    )

    model_config = {"from_attributes": True}
