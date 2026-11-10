# 002 — Storage items, tags, search, and pagination

status: implemented
sources: docs/storage-client/GUIDE.md, prometheus_api/storage_client/models/item.py, prometheus_api/storage_client/models/pagination.py, prometheus_api/storage_client/models/tag.py, prometheus_api/storage_client/models/metadata.py, prometheus_api/storage_client/resources/items.py, prometheus_api/storage_client/resources/tags.py, prometheus_api/storage_client/resources/search.py, prometheus_api/storage_client/async_resources/items.py, prometheus_api/storage_client/async_resources/tags.py, prometheus_api/storage_client/async_resources/search.py, tests/unit/test_models.py, tests/unit/test_tags.py, tests/unit/test_sync_async_parity.py, tests/unit/test_integration.py
depends-on: 001

## Purpose
Expose DeepLynx records as typed `Item` objects with predictable CRUD, tagging, search, and pagination behavior for both sync and async callers.

## Requirements
- REQ-002-01: Item create MUST POST to `/organizations/{org}/projects/{project}/records` with `dataSourceId` and a snake_case payload containing `name`, `description`, `properties`, `original_id`, and optional `class_id`.
- REQ-002-02: Item create and bulk create MUST default a missing or empty `description` to the item's `name` (DeepLynx rejects an empty description with `400 The Description field is required`), and a missing `original_id` to a client-generated value.
- REQ-002-03: Item create with tag names MUST resolve/add those tags and refetch the created item.
- REQ-002-04: Item update MUST use `PUT /records/{item_id}` and include only fields explicitly provided on `ItemUpdate`.
- REQ-002-05: Item list MUST return `Page[Item]` and compute `has_next`/`has_previous` for both list-shaped and wrapped DeepLynx responses.
- REQ-002-06: `iter_all(...)` MUST repeatedly call `list(...)` until `page_info.has_next` is false.
- REQ-002-07: Bulk create MUST POST all item payloads to `/records/bulk` and parse both list-shaped and wrapped responses.
- REQ-002-08: Tag operations MUST use project-scoped `/projects/{project_id}/tags` endpoints, normalize whitespace, reject empty names, skip duplicate names, and require resolved IDs to be positive integers.
- REQ-002-09: `ItemsResource.add_tags(...)` and async equivalent MUST call `/records/{item_id}/tags` once per tag using singular `tagId` query parameters.
- REQ-002-10: `ItemsResource.remove_tags(...)` and async equivalent MUST remove resolved tag IDs using singular `tagId` query parameters. ⚠ untested
- REQ-002-11: Simple search MUST call `/organizations/{org}/query/records` with `userQuery` and the active project ID; advanced and tag search MUST return `Page[Item]`.
- REQ-002-12: Item/search parsing MUST accept DeepLynx camelCase fields and JSON-string `properties` or `tags`, producing typed `Item` and `Tag` values.
- REQ-002-13: Sync and async item create/update payloads and search query parsing MUST remain aligned.
- REQ-002-14: Sync and async advanced query MUST accept a list of structured filters and project IDs, optionally accept text search, validate page numbers and page sizes, POST matching payloads to `/organizations/{org}/query/records/advanced/paginated`, and parse server pagination into `Page[Item]`.

## Behavior
- BEH-002-01: GIVEN a tag list with duplicate and blank names WHEN IDs are resolved THEN each non-empty normalized name is resolved once.
- BEH-002-02: GIVEN search results with JSON-string properties and tags WHEN parsed THEN properties become a dict and tags become `Tag` models.
- BEH-002-03: GIVEN a full page from a list-shaped response WHEN total count is absent THEN `has_next` is conservatively true.
- BEH-002-04: GIVEN equivalent sync and async advanced queries WHEN they execute THEN they send the same filters and pagination parameters and return equivalent typed pages.

## Interfaces
- `Tag(id: int | None = None, name: str)`
- `TagModel(id: int | None = None, name: str)`
- `MetadataField(name: str, value: Any, type: str | None = None)`
- `ItemCreate(name: str, description: str | None = None, properties: dict = {}, class_id: int | None = None, original_id: str | None = None, tags: list[str] | None = None)`
- `BulkItemCreate(items: list[ItemCreate])`
- `ItemUpdate(name: str | None = None, description: str | None = None, properties: dict | None = None, class_id: int | None = None, original_id: str | None = None)`
- `Item(id: int, name: str, properties: dict, created_at: datetime, updated_at: datetime, tags: list[Tag] = [], ...)`
- `PageInfo(page_number: int, page_size: int, total_count: int, has_next: bool, has_previous: bool).total_pages -> int`
- `Page[T](items: list[T], page_info: PageInfo)`
- `TagsResource.list() -> list[TagModel]`, `create(name: str) -> TagModel`, `get_or_create(name: str) -> TagModel`, `resolve_ids(names: list[str]) -> list[int]`
- `AsyncTagsResource.list/create/get_or_create/resolve_ids`
- `ItemsResource.create/get/update/delete/list/iter_all/bulk_create/add_tags/remove_tags`
- `AsyncItemsResource.create/get/update/delete/list/iter_all/bulk_create/add_tags/remove_tags`
- `SearchResource.query(query: str, page: int = 1, page_size: int = 100) -> Page[Item]`
- `SearchResource.advanced_query(filters: list[dict], project_ids: list[int], text_search: str | None = None, page: int = 1, page_size: int = 25) -> Page[Item]`
- `SearchResource.by_tags(tags: list[str], match_all: bool = False, page: int = 1, page_size: int = 100) -> Page[Item]`
- `SearchResource.recent(limit: int = 100) -> list[Item]`
- `AsyncSearchResource.query/advanced_query/by_tags/recent` with an `advanced_query(...)` signature matching `SearchResource`
- `paginate_iterator(fetch_page: Callable[[int, int], list[T]], page_size: int = 100, start_page: int = 1) -> Iterator[T]`

## Constraints
- Endpoint behavior shared by sync and async resource pairs MUST be kept in parity when payload shape, parsing, aliases, or tag behavior changes.
- Public models SHOULD retain generic storage terminology (`Item`, `Relationship`, `Tag`) rather than leaking DeepLynx record naming into downstream code.
- Tag ID validation intentionally fails fast because record tag endpoints require numeric project tag IDs.

## Out of scope / Non-goals
- This package does not define DeepLynx query syntax beyond forwarding simple, advanced, and tag search payloads.
- Search result ranking and filtering correctness remain DeepLynx responsibilities.

## Open questions
- `remove_tags(...)`, `by_tags(...)`, and `recent(...)` have less unit coverage than create/update/query paths.
- Page totals are inferred for some list-shaped responses; callers needing exact totals must rely on backend response support.
