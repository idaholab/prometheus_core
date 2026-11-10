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

"""Tests for data models."""

from datetime import datetime
from prometheus_api.storage_client.models.item import Item, ItemCreate, ItemUpdate, Tag
from prometheus_api.storage_client.models.pagination import Page, PageInfo
from prometheus_api.storage_client.models.relationship import RelationshipCreate


def test_item_create():
    """Test creating ItemCreate model."""
    item = ItemCreate(
        name="Test Item",
        description="Test description",
        properties={"key": "value"},
        tags=["tag1", "tag2"],
    )

    assert item.name == "Test Item"
    assert item.description == "Test description"
    assert item.properties == {"key": "value"}
    assert item.tags == ["tag1", "tag2"]


def test_item_create_minimal():
    """Test creating ItemCreate with minimal fields."""
    item = ItemCreate(name="Test")

    assert item.name == "Test"
    assert item.description is None
    assert item.properties == {}
    assert item.tags is None


def test_item_model():
    """Test full Item model."""
    item = Item(
        id=123,
        name="Test Item",
        properties={"key": "value"},
        created_at=datetime.now(),
        updated_at=datetime.now(),
        tags=[Tag(id=1, name="test")],
    )

    assert item.id == 123
    assert item.name == "Test Item"
    assert len(item.tags) == 1
    assert item.tags[0].name == "test"


def test_item_update():
    """Test ItemUpdate model."""
    update = ItemUpdate(name="New Name", properties={"new_key": "new_value"})

    assert update.name == "New Name"
    assert update.properties == {"new_key": "new_value"}
    assert update.description is None


def test_relationship_create():
    """Test creating RelationshipCreate model."""
    rel = RelationshipCreate(
        from_item_id=1,
        to_item_id=2,
        relationship_type="related_to",
        properties={"strength": "high"},
    )

    assert rel.from_item_id == 1
    assert rel.to_item_id == 2
    assert rel.relationship_type == "related_to"
    assert rel.properties == {"strength": "high"}


def test_page_info():
    """Test PageInfo model."""
    page_info = PageInfo(
        page_number=2, page_size=10, total_count=45, has_next=True, has_previous=True
    )

    assert page_info.page_number == 2
    assert page_info.page_size == 10
    assert page_info.total_count == 45
    assert page_info.total_pages == 5
    assert page_info.has_next is True
    assert page_info.has_previous is True


def test_page_model():
    """Test Page model."""
    items = [
        Item(
            id=i,
            name=f"Item {i}",
            properties={},
            created_at=datetime.now(),
            updated_at=datetime.now(),
            tags=[],
        )
        for i in range(10)
    ]

    page_info = PageInfo(
        page_number=1, page_size=10, total_count=10, has_next=False, has_previous=False
    )

    page = Page(items=items, page_info=page_info)

    assert len(page.items) == 10
    assert page.page_info.total_count == 10
