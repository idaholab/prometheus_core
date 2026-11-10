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

"""Unit tests for DeepLynx fsspec filesystem behavior."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from prometheus_api.storage_client.filesystem import DeepLynxFileSystem
from prometheus_api.storage_client.models.file import FileMetadata
from prometheus_api.storage_client.models.item import Item
from prometheus_api.storage_client.models.pagination import Page, PageInfo


def make_item(item_id: int, properties: dict) -> Item:
    """Build a minimal Item model for filesystem unit tests."""
    now = datetime.now(timezone.utc)
    return Item(
        id=item_id,
        name=f"item-{item_id}",
        description=None,
        properties=properties,
        class_id=None,
        original_id=f"orig-{item_id}",
        created_at=now,
        updated_at=now,
        tags=[],
        metatype_id=None,
        metatype_name=None,
        data_source_id=None,
    )


def make_page(items):
    """Build a single-page Page object from an iterable of items."""
    item_list = list(items)
    return Page(
        items=item_list,
        page_info=PageInfo(
            page_number=1,
            page_size=100,
            total_count=len(item_list),
            has_next=False,
            has_previous=False,
        ),
    )


def make_config(organization_id: int = 1, project_id: int = 2) -> SimpleNamespace:
    """Build a fake ConnectionConfig-like object.

    Required by any fake client exercising the search-fallback path, since
    ``_search_advanced_items`` reads ``self._client.config.project_id`` to
    satisfy ``SearchResource.advanced_query``'s required ``project_ids`` arg.
    """
    return SimpleNamespace(organization_id=organization_id, project_id=project_id)


def test_init_prefers_explicit_client(monkeypatch):
    """Explicit client should win over environment/config resolution."""
    fake_client = SimpleNamespace()
    from_env = Mock(side_effect=AssertionError("from_env should not be called"))
    monkeypatch.setattr(
        "prometheus_api.storage_client.filesystem.ConnectionConfig.from_env",
        from_env,
    )

    fs = DeepLynxFileSystem(client=fake_client)
    assert fs._client is fake_client
    assert fs._owns_client is False
    from_env.assert_not_called()


def test_init_builds_internal_client_from_config(monkeypatch):
    """Passing config should create and enter an internally owned client."""
    created = {}

    class FakeStorageClient:
        def __init__(self, config):
            created["config"] = config
            created["entered"] = False
            created["exited"] = False

        def __enter__(self):
            created["entered"] = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            created["exited"] = True

    cfg = SimpleNamespace(name="config")
    monkeypatch.setattr("prometheus_api.storage_client.filesystem.StorageClient", FakeStorageClient)

    fs = DeepLynxFileSystem(config=cfg)
    assert isinstance(fs._client, FakeStorageClient)
    assert created["config"] is cfg
    assert created["entered"] is True
    assert fs._owns_client is True

    fs.close()
    assert created["exited"] is True


def test_init_defaults_to_from_env(monkeypatch):
    """No client/config should default to ConnectionConfig.from_env()."""
    created = {}

    class FakeStorageClient:
        def __init__(self, config):
            created["config"] = config

        def __enter__(self):
            created["entered"] = True
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            created["exited"] = True

    cfg = SimpleNamespace(name="env-config")
    from_env = Mock(return_value=cfg)
    monkeypatch.setattr(
        "prometheus_api.storage_client.filesystem.ConnectionConfig.from_env",
        from_env,
    )
    monkeypatch.setattr("prometheus_api.storage_client.filesystem.StorageClient", FakeStorageClient)

    fs = DeepLynxFileSystem()
    from_env.assert_called_once()
    assert created["config"] is cfg
    assert created["entered"] is True
    fs.close()
    assert created["exited"] is True


def test_put_adds_metadata_with_version_timestamp(tmp_path):
    """put() should upload and stamp required filesystem metadata keys."""
    local_file = tmp_path / "mesh.e"
    local_file.write_bytes(b"mesh-data")

    files = Mock()
    files.upload.return_value = FileMetadata(id=101, name="mesh.e")
    items = Mock()
    items.get.return_value = make_item(101, {"existing": "value"})
    items.iter_all.return_value = []
    search = Mock()
    search.advanced_query.return_value = make_page([])
    search.query.return_value = make_page([])
    search.recent.return_value = []

    client = SimpleNamespace(files=files, items=items, search=search)
    fs = DeepLynxFileSystem(client=client)

    fs.put(str(local_file), "deeplynx://session-1/data/mesh.e")

    files.upload.assert_called_once_with(local_file)
    items.get.assert_called_once_with(101)
    update_call = items.update.call_args
    assert update_call is not None

    assert update_call.args[0] == 101
    properties = update_call.args[1].properties
    assert properties["existing"] == "value"
    assert properties["_deeplynx_fs_managed"] is True
    assert properties["_deeplynx_fs_path"] == "session-1/data/mesh.e"
    assert isinstance(properties["_deeplynx_fs_version_ns"], int)
    assert properties["_deeplynx_fs_version_ns"] > 0


def test_get_selects_latest_valid_version_and_ignores_invalid(tmp_path):
    """get() should choose newest valid version and ignore malformed versions."""
    invalid = make_item(
        1,
        {
            "_deeplynx_fs_managed": True,
            "_deeplynx_fs_path": "session/data/file.txt",
            "_deeplynx_fs_version_ns": "not-an-int",
        },
    )
    older = make_item(
        2,
        {
            "_deeplynx_fs_managed": True,
            "_deeplynx_fs_path": "session/data/file.txt",
            "_deeplynx_fs_version_ns": 10,
        },
    )
    newer = make_item(
        3,
        {
            "_deeplynx_fs_managed": True,
            "_deeplynx_fs_path": "session/data/file.txt",
            "_deeplynx_fs_version_ns": 20,
        },
    )

    files = Mock()
    items = Mock()
    items.iter_all.return_value = []
    search = Mock()
    search.advanced_query.return_value = make_page([invalid, older, newer])
    search.query.return_value = make_page([])
    search.recent.return_value = []
    client = SimpleNamespace(files=files, items=items, search=search, config=make_config())

    fs = DeepLynxFileSystem(client=client)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    fs.get("deeplynx://session/data/file.txt", str(output_dir))

    files.download.assert_called_once()
    assert files.download.call_args.args[0] == 3
    assert files.download.call_args.args[1] == output_dir / "file.txt"

    # Fallback resolution should have gone through advanced_query with the
    # configured client project, not been silently skipped.
    search.advanced_query.assert_called()
    assert search.advanced_query.call_args.kwargs["project_ids"] == [2]


def test_get_supports_deeplynx_item_uri(tmp_path):
    """Item-addressed deeplynx:// URIs should download the backing file record."""
    files = Mock()
    items = Mock()
    search = Mock()
    config = SimpleNamespace(organization_id=1, project_id=2)
    client = SimpleNamespace(files=files, items=items, search=search, config=config)
    fs = DeepLynxFileSystem(client=client)
    output = tmp_path / "artifact.svg"

    fs.get("deeplynx://organizations/1/projects/2/items/42", str(output))

    files.download.assert_called_once_with(42, output)
    search.advanced_query.assert_not_called()


def test_get_rejects_deeplynx_item_uri_for_other_project(tmp_path):
    """Item URI org/project must match the configured DeepLynx client."""
    files = Mock()
    items = Mock()
    search = Mock()
    config = SimpleNamespace(organization_id=1, project_id=2)
    client = SimpleNamespace(files=files, items=items, search=search, config=config)
    fs = DeepLynxFileSystem(client=client)

    with pytest.raises(ValueError, match="organization/project"):
        fs.get("deeplynx://organizations/1/projects/999/items/42", str(tmp_path / "out"))

    files.download.assert_not_called()


def test_rm_file_deletes_all_versions_for_exact_path():
    """rm(file) should delete every version mapped to the exact logical key."""
    v1 = make_item(
        5,
        {
            "_deeplynx_fs_managed": True,
            "_deeplynx_fs_path": "session/data/file.txt",
            "_deeplynx_fs_version_ns": 11,
        },
    )
    v2 = make_item(
        6,
        {
            "_deeplynx_fs_managed": True,
            "_deeplynx_fs_path": "session/data/file.txt",
            "_deeplynx_fs_version_ns": 12,
        },
    )

    files = Mock()
    items = Mock()
    items.iter_all.return_value = []
    search = Mock()
    search.advanced_query.return_value = make_page([v1, v2])
    search.query.return_value = make_page([])
    search.recent.return_value = []
    client = SimpleNamespace(files=files, items=items, search=search, config=make_config())
    fs = DeepLynxFileSystem(client=client)

    fs.rm("deeplynx://session/data/file.txt")

    deleted = sorted(call.args[0] for call in files.delete.call_args_list)
    assert deleted == [5, 6]


def test_rm_recursive_deletes_all_versions_under_prefix():
    """rm(prefix, recursive=True) should remove all descendant versions."""
    items_for_prefix = [
        make_item(
            7,
            {
                "_deeplynx_fs_managed": True,
                "_deeplynx_fs_path": "session/run/file-a.txt",
                "_deeplynx_fs_version_ns": 10,
            },
        ),
        make_item(
            8,
            {
                "_deeplynx_fs_managed": True,
                "_deeplynx_fs_path": "session/run/file-a.txt",
                "_deeplynx_fs_version_ns": 11,
            },
        ),
        make_item(
            9,
            {
                "_deeplynx_fs_managed": True,
                "_deeplynx_fs_path": "session/run/file-b.txt",
                "_deeplynx_fs_version_ns": 12,
            },
        ),
    ]

    files = Mock()
    items = Mock()
    items.iter_all.return_value = []
    search = Mock()
    search.advanced_query.return_value = make_page(items_for_prefix)
    search.query.return_value = make_page([])
    search.recent.return_value = []
    client = SimpleNamespace(files=files, items=items, search=search, config=make_config())
    fs = DeepLynxFileSystem(client=client)

    fs.rm("deeplynx://session/run", recursive=True)

    deleted = sorted(call.args[0] for call in files.delete.call_args_list)
    assert deleted == [7, 8, 9]


def test_get_warns_on_recent_and_full_scan_fallback(tmp_path):
    """When search endpoints fail, fallback warnings should be emitted."""
    target = make_item(
        77,
        {
            "_deeplynx_fs_managed": True,
            "_deeplynx_fs_path": "session/out/result.e",
            "_deeplynx_fs_version_ns": 1000,
        },
    )

    files = Mock()
    items = Mock()
    items.iter_all.return_value = [target]
    search = Mock()
    search.advanced_query.side_effect = RuntimeError("advanced unavailable")
    search.query.side_effect = RuntimeError("query unavailable")
    search.recent.return_value = []
    client = SimpleNamespace(files=files, items=items, search=search, config=make_config())

    fs = DeepLynxFileSystem(client=client)
    output_dir = tmp_path / "download"
    output_dir.mkdir()

    with pytest.warns(RuntimeWarning) as captured:
        fs.get("deeplynx://session/out/result.e", str(output_dir))

    messages = [str(w.message) for w in captured]
    assert any("fallback to search.recent" in msg for msg in messages)
    assert any("fallback to full scan" in msg for msg in messages)
    files.download.assert_called_once_with(77, output_dir / "result.e")


def test_glob_includes_virtual_directories_and_files():
    """glob() should return synthetic directories plus managed files."""
    records = [
        make_item(
            10,
            {
                "_deeplynx_fs_managed": True,
                "_deeplynx_fs_path": "session/data/data.csv",
                "_deeplynx_fs_version_ns": 100,
            },
        ),
        make_item(
            11,
            {
                "_deeplynx_fs_managed": True,
                "_deeplynx_fs_path": "session/data/mesh.e",
                "_deeplynx_fs_version_ns": 101,
            },
        ),
        make_item(
            12,
            {
                "_deeplynx_fs_managed": True,
                "_deeplynx_fs_path": "session/moose/input.i",
                "_deeplynx_fs_version_ns": 102,
            },
        ),
    ]

    files = Mock()
    items = Mock()
    items.iter_all.return_value = records
    search = Mock()
    search.advanced_query.return_value = make_page([])
    search.query.return_value = make_page([])
    search.recent.return_value = []
    client = SimpleNamespace(files=files, items=items, search=search, config=make_config())
    fs = DeepLynxFileSystem(client=client)

    listed = sorted(fs.glob("deeplynx://session/**", detail=False))
    assert listed == sorted(
        [
            "session",
            "session/data",
            "session/data/data.csv",
            "session/data/mesh.e",
            "session/moose",
            "session/moose/input.i",
        ]
    )


def test_entry_point_registers_deeplynx_protocol():
    """Installed package should expose deeplynx protocol via fsspec entry points."""
    code = "import fsspec,sys;sys.exit(0 if 'deeplynx' in fsspec.available_protocols() else 1)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
