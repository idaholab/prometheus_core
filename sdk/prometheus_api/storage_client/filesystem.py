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

"""fsspec filesystem implementation for DeepLynx-backed file artifacts.

This module exposes a :class:`DeepLynxFileSystem` implementation that maps
``deeplynx://`` URIs to DeepLynx file records managed through the
``prometheus_api.storage_client`` high-level resources.
"""

import logging
import os
import re
import posixpath
import time
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
import json as json_lib

from fsspec import AbstractFileSystem
from fsspec.callbacks import DEFAULT_CALLBACK
from fsspec.spec import has_magic
from fsspec.utils import glob_translate

from .client import StorageClient
from .connection import ConnectionConfig
from .models.item import Item, ItemUpdate
from .uri import parse_item_uri

logger = logging.getLogger(__name__)


class DeepLynxFileSystem(AbstractFileSystem):
    """fsspec-compatible filesystem facade backed by DeepLynx file records.

    The filesystem emulates S3-like object path semantics over DeepLynx:
    each logical object key (for example ``session-1/data/mesh.e``) is stored
    in record metadata, while the binary file payload is stored through the
    DeepLynx file API.

    Design goals
    ------------
    1. Make ``put`` and ``get`` efficient and predictable for downstream
       workflows that pass around stable URI paths.
    2. Keep all indexing inside record metadata; no secondary index records or
       external manifest tables are created.
    3. Prefer search resource endpoints for lookup, and degrade gracefully with
       explicit runtime warnings when broader scans are required.
    4. Preserve version history for repeated writes to the same logical path.

    Metadata contract
    -----------------
    Every managed record is marked with:

    - ``_deeplynx_fs_managed``: Boolean marker indicating this record belongs
      to the filesystem abstraction.
    - ``_deeplynx_fs_path``: Normalized POSIX object key used for exact and
      prefix lookup.
    - ``_deeplynx_fs_version_ns``: Integer timestamp from ``time.time_ns()``,
      used as the primary ordering key for version resolution.

    Versioning behavior
    -------------------
    ``put`` to an existing logical path creates a new version and keeps prior
    records. ``get`` resolves to the latest valid version for that path.
    Records with missing or invalid version metadata are treated as invalid for
    read resolution and ignored.

    Lookup strategy
    ---------------
    To avoid unnecessary full scans, candidate lookup uses a layered approach:

    1. ``search.advanced_query`` with metadata-oriented filters.
    2. ``search.query`` with exact in-memory metadata filtering.
    3. ``search.recent`` fallback with warning.
    4. ``items.iter_all`` full scan fallback with warning.

    This ordering keeps normal paths fast on search-enabled deployments while
    still functioning on deployments with limited search capabilities.

    Initialization behavior
    -----------------------
    Constructor inputs are resolved with explicit precedence:

    1. If ``client`` is provided, it is used directly and lifecycle ownership
       remains with the caller.
    2. Else if ``config`` is provided, a new internal ``StorageClient`` is
       built and entered.
    3. Else ``ConnectionConfig.from_env()`` is used to build an internal
       client.

    Example
    -------
    ```python
    import fsspec
    from prometheus_api.storage_client import ConnectionConfig

    fs = fsspec.filesystem("deeplynx", config=ConnectionConfig.from_env())
    fs.put("input.i", "deeplynx://session-abc/moose/input.i")
    fs.get("deeplynx://session-abc/moose/input.i", "./run/")
    ```
    """

    protocol = "deeplynx"
    sep = "/"

    META_MANAGED = "_deeplynx_fs_managed"
    META_PATH = "_deeplynx_fs_path"
    META_VERSION_NS = "_deeplynx_fs_version_ns"

    def __init__(
        self,
        client: Optional[StorageClient] = None,
        config: Optional[ConnectionConfig] = None,
        *,
        recent_limit: int = 500,
        search_page_size: int = 100,
        search_max_pages: int = 5,
        **kwargs,
    ):
        """Create a DeepLynx filesystem instance.

        Args:
            client: Existing storage client to reuse. If provided, this class
                does not close it.
            config: Connection configuration used only when ``client`` is not
                supplied.
            recent_limit: Result count for ``search.recent`` fallback.
            search_page_size: Page size for search pagination.
            search_max_pages: Maximum number of pages fetched per search call.
            **kwargs: Additional options forwarded to
                :class:`fsspec.AbstractFileSystem`.
        """
        super().__init__(**kwargs)
        self._owns_client = False
        self._closed = False
        self._full_scan_cache: Optional[List[Item]] = None
        self._recent_limit = max(1, int(recent_limit))
        self._search_page_size = max(1, int(search_page_size))
        self._search_max_pages = max(1, int(search_max_pages))

        if client is not None:
            self._client = client
        else:
            self._owns_client = True
            client_config = config or ConnectionConfig.from_env()
            self._client = StorageClient(client_config)
            # Enter context so auth/session initialization is identical to
            # explicit "with StorageClient(...)" usage.
            self._client.__enter__()

    @classmethod
    def _strip_protocol(cls, path: Any) -> Any:
        """Strip ``deeplynx://`` and normalize to a POSIX key string."""
        if isinstance(path, (tuple, list, set)):
            return type(path)(cls._strip_protocol(p) for p in path)
        if path is None:
            return ""

        value = os.fsdecode(path).replace("\\", "/")
        protocol_prefix = f"{cls.protocol}://"
        if value.startswith(protocol_prefix):
            value = value[len(protocol_prefix) :]

        value = value.lstrip("/")
        if not value or value == ".":
            return ""

        normalized = posixpath.normpath(value)
        if normalized in (".", "/"):
            return ""
        return normalized.lstrip("/")

    def close(self):
        """Close internally-owned client session."""
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            try:
                self._client.__exit__(None, None, None)
            except Exception:
                pass

    def __del__(self):
        """Best-effort cleanup for internally created client sessions."""
        self.close()

    def put(
        self,
        lpath,
        rpath,
        recursive: bool = False,
        callback=DEFAULT_CALLBACK,
        maxdepth=None,
        **kwargs,
    ):
        """Upload a local file or directory into DeepLynx-backed storage.

        For files, the destination key is either the exact remote path or
        ``<remote-prefix>/<filename>`` when destination is treated as a
        directory path.

        For directories, recursive mode is required and each local file is
        uploaded independently while preserving relative structure.
        """
        local_path = Path(os.fspath(lpath))
        if not local_path.exists():
            raise FileNotFoundError(f"Local path does not exist: {local_path}")

        if local_path.is_dir():
            if not recursive:
                raise IsADirectoryError(f"Local path is a directory: {local_path}")
            self._put_directory(local_path, rpath)
            return

        remote_key = self._resolve_target_file_key(local_path, rpath)
        callback.set_size(local_path.stat().st_size)
        self._upload_with_metadata(local_path, remote_key)
        callback.relative_update(local_path.stat().st_size)

    def get(
        self,
        rpath,
        lpath,
        recursive: bool = False,
        callback=DEFAULT_CALLBACK,
        maxdepth=None,
        **kwargs,
    ):
        """Download a remote file (or tree in recursive mode) to local disk.

        Non-recursive mode resolves a single logical key to the latest valid
        version and downloads that file.
        """
        remote_key = self._normalize_key(rpath)
        item_id = self._parse_item_uri_key(remote_key)
        if item_id is not None:
            if recursive:
                raise NotADirectoryError(f"DeepLynx item URI is a file, not a directory: {rpath}")
            destination = self._resolve_local_destination(lpath, remote_key)
            callback.set_size(None)
            self._client.files.download(item_id, destination)
            callback.relative_update(1)
            return

        if recursive:
            self._get_recursive(remote_key, lpath)
            return

        selected = self._resolve_latest_item(remote_key)
        if selected is None:
            raise FileNotFoundError(f"No DeepLynx file found for path: {remote_key}")

        destination = self._resolve_local_destination(lpath, remote_key)
        callback.set_size(None)
        self._client.files.download(selected.id, destination)
        callback.relative_update(1)

    def info(self, path, **kwargs):
        """Return file/directory metadata compatible with fsspec expectations."""
        key = self._normalize_key(path)
        item_id = self._parse_item_uri_key(key)
        if item_id is not None:
            return {"name": key, "type": "file", "size": None}

        latest = self._resolve_latest_item(key)
        if latest is not None:
            return {"name": key, "type": "file", "size": None}

        if key == "":
            return {"name": "", "type": "directory", "size": 0}

        if self._path_has_children(key):
            return {"name": key, "type": "directory", "size": 0}

        raise FileNotFoundError(path)

    def exists(self, path, **kwargs):
        """Return ``True`` when a file or directory-like key exists."""
        try:
            self.info(path, **kwargs)
            return True
        except FileNotFoundError:
            return False

    def isfile(self, path):
        """Return ``True`` if the key resolves to a managed file."""
        key = self._normalize_key(path)
        if self._parse_item_uri_key(key) is not None:
            return True
        return self._resolve_latest_item(key) is not None

    def isdir(self, path):
        """Return ``True`` if key is root or a virtual directory prefix."""
        key = self._normalize_key(path)
        if key == "":
            return True
        return self._path_has_children(key)

    def ls(self, path, detail=True, **kwargs):
        """List immediate children for a virtual directory or file key."""
        key = self._normalize_key(path)
        latest_map = self._list_latest_by_path(prefix=key)

        # "ls(file)" should return the file itself if it exists
        file_item = latest_map.get(key) if key else None
        if key and file_item is not None:
            info = {"name": key, "type": "file", "size": None}
            return [info] if detail else [key]

        children: Dict[str, dict] = {}
        for file_path in latest_map:
            child = self._immediate_child(key, file_path)
            if child is None:
                continue
            if "/" in child:
                child_name = self._join_keys(key, child.split("/", 1)[0])
                children[child_name] = {"name": child_name, "type": "directory", "size": 0}
            else:
                child_name = self._join_keys(key, child)
                children[child_name] = {"name": child_name, "type": "file", "size": None}

        if not children:
            if key == "":
                return [] if detail else []
            raise FileNotFoundError(path)

        names = sorted(children)
        if detail:
            return [children[name] for name in names]
        return names

    def glob(self, path, maxdepth=None, **kwargs):
        """Glob against virtual file and directory entries."""
        detail = kwargs.pop("detail", False)
        pattern = self._normalize_key(path)
        ends_with_sep = os.fspath(path).endswith(("/", "\\"))
        append_slash_to_dirname = ends_with_sep or pattern.endswith("/**")

        entries = self._build_virtual_entries(prefix=self._glob_prefix(pattern))
        if not has_magic(pattern):
            if pattern in entries:
                if detail:
                    return {pattern: entries[pattern]}
                return [pattern]
            return {} if detail else []

        compiled = re.compile(glob_translate(pattern + ("/" if ends_with_sep else "")))
        # Match directory entries with optional trailing slash behavior to
        # align with fsspec's expectations for "pattern/**" results.
        matched = {
            name: info
            for name, info in sorted(entries.items())
            if compiled.match(
                name + "/" if append_slash_to_dirname and info["type"] == "directory" else name
            )
        }
        if detail:
            return matched
        return list(matched)

    def rm(self, path, recursive=False, maxdepth=None):
        """Delete file versions or directory prefixes from managed records."""
        if isinstance(path, (list, tuple, set)):
            for entry in path:
                self.rm(entry, recursive=recursive, maxdepth=maxdepth)
            return

        key = self._normalize_key(path)
        if key == "":
            if not recursive:
                raise ValueError("Refusing to remove root without recursive=True")
            targets = self._find_items_for_prefix(prefix="", require_version=False)
            self._delete_items(targets)
            return

        exact = self._find_items_for_exact_path(key, require_version=False)
        if exact:
            # File delete semantics: remove all versions for this exact key.
            self._delete_items(exact)
            return

        if not recursive:
            if self._path_has_children(key):
                raise IsADirectoryError(f"Path is a directory; use recursive=True: {path}")
            raise FileNotFoundError(path)

        prefixed = self._find_items_for_prefix(prefix=key, require_version=False)
        if not prefixed:
            raise FileNotFoundError(path)
        # Recursive directory delete semantics: remove all versions under key.
        self._delete_items(prefixed)

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _normalize_key(self, path: Any) -> str:
        """Normalize user path/URI input into a canonical object key."""
        return str(self._strip_protocol(path))

    def _parse_item_uri_key(self, key: str) -> Optional[int]:
        """Return the item ID of an ``organizations/{org}/projects/{project}/items/{item}`` key.

        ``send_deeplynx_artifact`` emits item-addressed URIs for durable
        artifacts, while this filesystem also supports logical object keys used
        by ``put``/``get``. Item URIs are validated against the current client
        configuration so a configured project cannot accidentally read another
        project's item through a copied URI.
        """
        ref = parse_item_uri(key)
        if ref is None:
            return None
        config = getattr(self._client, "config", None)
        if config is not None:
            if ref.organization_id != int(config.organization_id) or ref.project_id != int(
                config.project_id
            ):
                raise ValueError(
                    "DeepLynx item URI does not match the configured organization/project"
                )
        return ref.item_id

    def _join_keys(self, *parts: str) -> str:
        """Join non-empty path fragments into a normalized POSIX key."""
        values = [p for p in parts if p]
        if not values:
            return ""
        return posixpath.normpath("/".join(values))

    def _path_endswith_sep(self, path: Any) -> bool:
        """Return ``True`` for path-like inputs ending with a separator."""
        value = os.fsdecode(path)
        return value.endswith("/") or value.endswith("\\")

    def _resolve_target_file_key(self, local_file: Path, rpath) -> str:
        """Resolve destination key for a single-file upload."""
        target = self._normalize_key(rpath)
        if target == "" or self._path_endswith_sep(rpath):
            return self._join_keys(target, local_file.name)
        return target

    def _put_directory(self, local_dir: Path, rpath):
        """Upload all files from a local directory tree."""
        target = self._normalize_key(rpath)
        include_source_dir = target == "" or self._path_endswith_sep(rpath)
        prefix = self._join_keys(target, local_dir.name) if include_source_dir else target

        for file_path in sorted(local_dir.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(local_dir).as_posix()
            remote_key = self._join_keys(prefix, relative)
            self._upload_with_metadata(file_path, remote_key)

    def _upload_with_metadata(self, local_file: Path, remote_key: str):
        """Upload bytes and stamp record metadata used by this filesystem."""
        file_meta = self._client.files.upload(local_file)
        existing = self._client.items.get(file_meta.id)
        properties = dict(existing.properties or {})
        properties.update(
            {
                self.META_MANAGED: True,
                self.META_PATH: remote_key,
                # time_ns is timezone-independent and monotonic enough for
                # deterministic ordering in this context.
                self.META_VERSION_NS: time.time_ns(),
            }
        )
        self._client.items.update(
            file_meta.id,
            ItemUpdate(
                name=existing.name,
                description=existing.description,
                properties=properties,
                class_id=existing.class_id,
                original_id=existing.original_id,
            ),
        )
        self._full_scan_cache = None

    def _resolve_local_destination(self, lpath, remote_key: str) -> Path:
        """Resolve local output path for download operations."""
        destination = Path(os.fspath(lpath))
        is_dir_target = self._path_endswith_sep(lpath) or destination.is_dir()
        if is_dir_target:
            destination = destination / Path(remote_key).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    def _get_recursive(self, remote_key: str, lpath):
        """Download a remote subtree, preserving relative paths."""
        latest = self._list_latest_by_path(prefix=remote_key)
        if remote_key and remote_key in latest:
            selected = self._resolve_latest_item(remote_key)
            if selected is None:
                raise FileNotFoundError(remote_key)
            destination = self._resolve_local_destination(lpath, remote_key)
            self._client.files.download(selected.id, destination)
            return

        if remote_key:
            keys = sorted([k for k in latest if k.startswith(f"{remote_key}/")])
        else:
            keys = sorted(latest)
        if not keys:
            raise FileNotFoundError(remote_key)

        base = Path(os.fspath(lpath))
        base.mkdir(parents=True, exist_ok=True)
        for key in keys:
            relative = key[len(remote_key) + 1 :] if remote_key else key
            output_path = base / relative
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._client.files.download(latest[key].id, output_path)

    def _build_virtual_entries(self, prefix: str = "") -> Dict[str, dict]:
        """Materialize file and synthetic directory entries for glob/list."""
        latest = self._list_latest_by_path(prefix=prefix)
        entries: Dict[str, dict] = {"": {"name": "", "type": "directory", "size": 0}}

        for path in latest:
            entries[path] = {"name": path, "type": "file", "size": None}
            pieces = path.split("/")
            for idx in range(1, len(pieces)):
                directory = "/".join(pieces[:idx])
                entries.setdefault(directory, {"name": directory, "type": "directory", "size": 0})
        return entries

    def _glob_prefix(self, pattern: str) -> str:
        """Extract static prefix before first glob metacharacter."""
        if not pattern:
            return ""
        if not has_magic(pattern):
            return pattern
        for idx, char in enumerate(pattern):
            if char in "*?[":
                prefix = pattern[:idx]
                if "/" in prefix:
                    return prefix.rsplit("/", 1)[0]
                return ""
        return ""

    def _immediate_child(self, directory_key: str, file_key: str) -> Optional[str]:
        """Return relative child segment for ``ls`` calculations."""
        if directory_key:
            prefix = f"{directory_key}/"
            if not file_key.startswith(prefix):
                return None
            remainder = file_key[len(prefix) :]
        else:
            remainder = file_key
        if not remainder:
            return None
        return remainder

    def _delete_items(self, items: Sequence[Item]):
        """Delete record-backed files by record id with duplicate suppression."""
        seen = set()
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            self._client.files.delete(item.id)
        self._full_scan_cache = None

    def _path_has_children(self, key: str) -> bool:
        """Check whether a virtual directory has any descendant files."""
        latest = self._list_latest_by_path(prefix=key)
        if key == "":
            return bool(latest)
        prefix = f"{key}/"
        return any(path.startswith(prefix) for path in latest)

    def _list_latest_by_path(self, prefix: str = "") -> Dict[str, Item]:
        """Return latest valid-version item for each key under a prefix."""
        items = self._find_items_for_prefix(prefix)
        latest: Dict[str, tuple[int, int, Item]] = {}
        for item in items:
            path = self._item_path(item)
            version = self._item_version(item)
            if path is None or version is None:
                continue
            if prefix and path != prefix and not path.startswith(f"{prefix}/"):
                continue
            score = (version, item.id, item)
            current = latest.get(path)
            if current is None or score[:2] > current[:2]:
                latest[path] = score
        return {path: score[2] for path, score in latest.items()}

    def _resolve_latest_item(self, path: str) -> Optional[Item]:
        """Resolve newest valid item for an exact object key."""
        candidates = self._find_items_for_exact_path(path, require_version=True)
        if not candidates:
            return None
        best: Optional[tuple[int, int, Item]] = None
        for item in candidates:
            version = self._item_version(item)
            if version is None:
                continue
            score = (version, item.id, item)
            if best is None or score[:2] > best[:2]:
                best = score
        if best is None:
            return None
        return best[2]

    def _find_items_for_exact_path(self, path: str, require_version: bool) -> List[Item]:
        """Find candidate items for an exact key using layered search fallback."""
        items = self._search_exact_with_advanced(path)
        filtered = self._filter_exact_path(items, path, require_version=require_version)
        if filtered:
            return filtered

        query_terms = [path]
        name = path.rsplit("/", 1)[-1]
        if name and name != path:
            query_terms.append(name)

        queried: List[Item] = []
        for term in query_terms:
            queried.extend(self._search_query_items(term))
        filtered = self._filter_exact_path(queried, path, require_version=require_version)
        if filtered:
            return filtered

        self._warn_recent_fallback(path, "exact path")
        recent = self._search_recent_items()
        filtered = self._filter_exact_path(recent, path, require_version=require_version)
        if filtered:
            return filtered

        self._warn_full_scan_fallback(path, "exact path")
        scanned = self._scan_all_items()
        return self._filter_exact_path(scanned, path, require_version=require_version)

    def _find_items_for_prefix(self, prefix: str, require_version: bool = True) -> List[Item]:
        """Find candidate items for a key prefix using layered search fallback."""
        advanced = self._search_prefix_with_advanced(prefix)
        filtered = self._filter_prefix(advanced, prefix, require_version=require_version)
        if filtered:
            return filtered

        query_terms: List[str] = [prefix] if prefix else [self.META_MANAGED]
        if prefix and "/" in prefix:
            query_terms.append(prefix.rsplit("/", 1)[-1])

        queried: List[Item] = []
        for term in query_terms:
            queried.extend(self._search_query_items(term))
        filtered = self._filter_prefix(queried, prefix, require_version=require_version)
        if filtered:
            return filtered

        self._warn_recent_fallback(prefix, "prefix")
        recent = self._search_recent_items()
        filtered = self._filter_prefix(recent, prefix, require_version=require_version)
        if filtered:
            return filtered

        self._warn_full_scan_fallback(prefix, "prefix")
        scanned = self._scan_all_items()
        return self._filter_prefix(scanned, prefix, require_version=require_version)

    def _search_exact_with_advanced(self, path: str) -> List[Item]:
        """Attempt exact-path lookup via advanced-query jsonb containment filter."""
        filters: List[Dict[str, Any]] = [
            {
                "filter": "properties",
                "operator": "KEY_VALUE",
                "json": json_lib.dumps({self.META_MANAGED: True, self.META_PATH: path}),
            }
        ]
        return self._search_advanced_items(filters)

    def _search_prefix_with_advanced(self, prefix: str) -> List[Item]:
        """Attempt broad managed-record lookup; prefix filtering happens client-side."""
        _ = prefix
        filters: List[Dict[str, Any]] = [
            {
                "filter": "properties",
                "operator": "KEY_VALUE",
                "json": json_lib.dumps({self.META_MANAGED: True}),
            }
        ]
        return self._search_advanced_items(filters)

    def _search_advanced_items(self, filters: List[Dict[str, Any]]) -> List[Item]:
        """Run paginated advanced search and return flattened item list."""
        items: List[Item] = []
        project_ids = [self._client.config.project_id]
        for page in range(1, self._search_max_pages + 1):
            try:
                result = self._client.search.advanced_query(
                    filters=filters,
                    project_ids=project_ids,
                    page=page,
                    page_size=self._search_page_size,
                )
            except Exception as exc:
                logger.debug("search fallback failed on page %d: %r", page, exc)
                return []
            items.extend(result.items)
            if not result.page_info.has_next:
                break
        return items

    def _search_query_items(self, text: str) -> List[Item]:
        """Run paginated text search and return flattened item list."""
        if not text:
            return []
        items: List[Item] = []
        for page in range(1, self._search_max_pages + 1):
            try:
                result = self._client.search.query(
                    text,
                    page=page,
                    page_size=self._search_page_size,
                )
            except Exception as exc:
                logger.debug("search fallback failed on page %d: %r", page, exc)
                return []
            items.extend(result.items)
            if not result.page_info.has_next:
                break
        return items

    def _search_recent_items(self) -> List[Item]:
        """Retrieve recent items as fallback when query endpoints fail."""
        try:
            return list(self._client.search.recent(limit=self._recent_limit))
        except Exception:
            # A failure here (a route error, a malformed body) otherwise looks like
            # "file not found" to the caller.
            logger.warning("search.recent failed during a deeplynx:// lookup", exc_info=True)
            return []

    def _scan_all_items(self) -> List[Item]:
        """Perform full-record scan as last-resort fallback.

        Results are cached until a mutating operation invalidates cache.
        """
        if self._full_scan_cache is not None:
            return list(self._full_scan_cache)
        items = list(self._client.items.iter_all(page_size=self._search_page_size))
        self._full_scan_cache = list(items)
        return items

    def _warn_recent_fallback(self, value: str, mode: str):
        """Warn that recent-items fallback was required for lookup."""
        warnings.warn(
            f"DeepLynxFileSystem fallback to search.recent for {mode} lookup: '{value}'",
            RuntimeWarning,
            stacklevel=3,
        )

    def _warn_full_scan_fallback(self, value: str, mode: str):
        """Warn that full-scan fallback was required for lookup."""
        warnings.warn(
            f"DeepLynxFileSystem fallback to full scan for {mode} lookup: '{value}'",
            RuntimeWarning,
            stacklevel=3,
        )

    def _filter_exact_path(
        self, items: Iterable[Item], path: str, require_version: bool
    ) -> List[Item]:
        """Filter items to exact managed path with optional version validity."""
        seen = set()
        filtered: List[Item] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            if self._item_path(item) != path:
                continue
            if require_version and self._item_version(item) is None:
                continue
            filtered.append(item)
        return filtered

    def _filter_prefix(
        self,
        items: Iterable[Item],
        prefix: str,
        require_version: bool = True,
    ) -> List[Item]:
        """Filter items to managed path prefix with optional version validity."""
        seen = set()
        filtered: List[Item] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            path = self._item_path(item)
            if path is None:
                continue
            if require_version and self._item_version(item) is None:
                continue
            if prefix and path != prefix and not path.startswith(f"{prefix}/"):
                continue
            filtered.append(item)
        return filtered

    def _item_path(self, item: Item) -> Optional[str]:
        """Extract normalized managed key from item properties."""
        props = item.properties or {}
        if not self._is_truthy(props.get(self.META_MANAGED)):
            return None
        path_value = props.get(self.META_PATH)
        if not isinstance(path_value, str):
            return None
        normalized = self._normalize_key(path_value)
        return normalized if normalized else None

    def _item_version(self, item: Item) -> Optional[int]:
        """Extract and validate version timestamp metadata."""
        props = item.properties or {}
        value = props.get(self.META_VERSION_NS)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            value = value.strip()
            if value.isdigit():
                return int(value)
        return None

    def _is_truthy(self, value) -> bool:
        """Interpret common truthy formats for metadata compatibility."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        if isinstance(value, int):
            return value != 0
        return False
