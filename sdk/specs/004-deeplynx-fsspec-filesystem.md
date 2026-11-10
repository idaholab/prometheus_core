# 004 — DeepLynx fsspec filesystem

status: implemented
sources: docs/storage-client/GUIDE.md, pyproject.toml, prometheus_api/storage_client/filesystem.py, tests/unit/test_filesystem.py, tests/unit/test_integration.py
depends-on: 001, 002, 003

## Purpose
Expose DeepLynx-backed file records through familiar `fsspec` object-store operations so tools can use stable `deeplynx://` paths.

## Requirements
- REQ-004-01: The package MUST register `deeplynx` as an `fsspec.specs` entry point.
- REQ-004-02: `DeepLynxFileSystem` initialization MUST prefer an explicit `client`, else create and own `StorageClient(config)`, else load `ConnectionConfig.from_env()`.
- REQ-004-03: `close()` MUST close only internally owned clients and MUST be idempotent.
- REQ-004-04: Path handling MUST strip `deeplynx://`, normalize backslashes to POSIX separators, remove leading slashes, and treat empty or `.` paths as root.
- REQ-004-05: `put()` MUST reject missing local paths, require `recursive=True` for directories, and preserve directory-relative structure for recursive uploads.
- REQ-004-06: Uploaded filesystem-managed records MUST be stamped with `_deeplynx_fs_managed`, `_deeplynx_fs_path`, and `_deeplynx_fs_version_ns`.
- REQ-004-07: Repeated `put()` to the same logical path MUST preserve older records; reads MUST select the newest valid version and ignore missing or malformed version metadata.
- REQ-004-08: `get()` MUST support item-addressed `deeplynx://organizations/{org}/projects/{project}/items/{item}` URIs, validate org/project against the configured client when available, and reject recursive item-URI downloads.
- REQ-004-09: `rm(file)` MUST delete all versions for an exact logical path; `rm(prefix, recursive=True)` MUST delete all versions under that prefix; root deletion MUST require `recursive=True`.
- REQ-004-10: `info`, `exists`, `isfile`, `isdir`, `ls`, and `glob` MUST expose files plus synthetic virtual directories derived from managed file paths.
- REQ-004-11: Lookup MUST try advanced metadata search, then text search plus metadata filtering, then `search.recent` with a runtime warning, then full `items.iter_all` scan with a runtime warning.
- REQ-004-12: Full-scan results MUST be cached until a mutating operation invalidates the cache. ⚠ untested

## Behavior
- BEH-004-01: GIVEN multiple valid versions for one key WHEN `get()` is called THEN the file with the greatest version timestamp, breaking ties by item ID, is downloaded.
- BEH-004-02: GIVEN a copied DeepLynx item URI for another project WHEN `get()` is called THEN `ValueError` is raised before download.
- BEH-004-03: GIVEN search endpoints fail WHEN a matching item exists only in a full scan THEN both fallback warnings are emitted and the file is still resolved.

## Interfaces
- `DeepLynxFileSystem(client: StorageClient | None = None, config: ConnectionConfig | None = None, *, recent_limit: int = 500, search_page_size: int = 100, search_max_pages: int = 5, **kwargs)`
- `DeepLynxFileSystem.close() -> None`
- `DeepLynxFileSystem.put(lpath, rpath, recursive: bool = False, callback=..., maxdepth=None, **kwargs) -> None`
- `DeepLynxFileSystem.get(rpath, lpath, recursive: bool = False, callback=..., maxdepth=None, **kwargs) -> None`
- `DeepLynxFileSystem.info(path, **kwargs) -> dict`
- `DeepLynxFileSystem.exists(path, **kwargs) -> bool`
- `DeepLynxFileSystem.isfile(path) -> bool`
- `DeepLynxFileSystem.isdir(path) -> bool`
- `DeepLynxFileSystem.ls(path, detail: bool = True, **kwargs) -> list`
- `DeepLynxFileSystem.glob(path, maxdepth=None, **kwargs) -> list | dict`
- `DeepLynxFileSystem.rm(path, recursive: bool = False, maxdepth=None) -> None`

## Constraints
- The filesystem MUST NOT create secondary index records; logical paths and versions live in file record metadata.
- Non-search fallbacks are compatibility paths and intentionally warn because they can be expensive on large projects.
- Managed record detection accepts common truthy encodings for compatibility, but version metadata must be a non-negative integer or digit string.

## Out of scope / Non-goals
- The filesystem is not a transactional object store and does not guarantee atomic multi-file directory uploads or deletes.
- It does not expose historical version selection by timestamp or version ID; only the latest valid version is readable by path.

## Open questions
- Full-scan cache invalidation is implemented for mutations, but direct tests only exercise lookup behavior, not cache reuse.
- Prefix lookup relies on client-side filtering because DeepLynx advanced filter support differs by deployment.
