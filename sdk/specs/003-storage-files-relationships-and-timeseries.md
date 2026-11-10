# 003 — Storage files, relationships, and timeseries

status: implemented
sources: docs/storage-client/GUIDE.md, prometheus_api/storage_client/models/file.py, prometheus_api/storage_client/models/relationship.py, prometheus_api/storage_client/models/timeseries.py, prometheus_api/storage_client/resources/files.py, prometheus_api/storage_client/resources/relationships.py, prometheus_api/storage_client/resources/timeseries.py, prometheus_api/storage_client/utils/streaming.py, prometheus_api/storage_client/async_resources/files.py, prometheus_api/storage_client/async_resources/relationships.py, prometheus_api/storage_client/async_resources/timeseries.py, tests/test_models.py, tests/test_relationships.py, tests/test_timeseries.py, tests/test_integration.py
depends-on: 001, 002

## Purpose
Support non-record storage workflows: binary files, large chunked uploads, relationships between items, and queries over tabular (timeseries) file records.

## Requirements
- REQ-003-01: File upload MUST reject missing local paths, default the remote name to `Path.name`, include optional description, and return `FileMetadata`.
- REQ-003-02: File metadata lookup MUST retrieve the backing record through `/records/{file_id}` and parse DeepLynx file fields into `FileMetadata`.
- REQ-003-03: File download MUST request `/files/{file_id}`, create parent directories for the target path, and write response bytes to disk.
- REQ-003-04: File delete MUST call `/files/{file_id}` and return `None` on success.
- REQ-003-05: Chunked upload MUST start a session, send zero-based chunks, complete with `total_chunks`, and best-effort cancel the session if an intermediate step fails. ⚠ untested
- REQ-003-06: Chunked upload MUST use a generated UUID when the start response omits an upload ID. ⚠ untested
- REQ-003-07: Relationship create/bulk create MUST map generic model fields to DeepLynx `origin_id`, `destination_id`, `name`, `properties`, and include `dataSourceId`.
- REQ-003-08: Relationship get/delete MUST address `/edges/{relationship_id}`.
- REQ-003-09: `get_item_relationships(item_id, direction=None)` MUST combine outgoing and incoming relationships; explicit `outgoing`/`incoming` MUST map to `isOrigin=true/false`.
- REQ-003-10: Relationship parsing MUST accept wrapped DeepLynx responses and MUST raise `ValueError` if required origin/destination IDs are absent. ⚠ untested
- REQ-003-11: `get_item_graph(item_id, depth=1)` MUST return a dict response, wrapping non-dict backend responses under `{"result": ...}`. ⚠ untested
- REQ-003-12: Timeseries query MUST `POST /organizations/{org}/projects/{project}/records/{record_id}/olap/query` with `viewName` as a query parameter and a JSON body holding only the options the caller provided (`query`, `limit`, `rowStride`, `startRow`, `stopRow`, `columns`), and MUST return a `TimeseriesResult` of `columns` and `data` with cells uncoerced (a missing value can arrive as `{}`). A missing or null `columns` or `data`, as for a window past the end of the data, MUST be an empty result and not an error. There is no timeseries upload: tabular files are uploaded through the file API.
- REQ-003-13: Sync and async file, chunked upload, relationship, and timeseries resource pairs SHOULD remain behaviorally aligned. ⚠ untested
- REQ-003-14: `Relationship` MUST accept `properties` as the JSON-encoded string (or `null`) that DeepLynx edge endpoints return, decoding it to a dict; a string that is not valid JSON or does not decode to an object MUST become an empty dict.

## Behavior
- BEH-003-01: GIVEN a file path that does not exist WHEN upload is requested THEN `ValueError` is raised before any API request.
- BEH-003-02: GIVEN `direction=None` WHEN item relationships are requested THEN outgoing and incoming relationship lists are concatenated.
- BEH-003-03: GIVEN a chunk upload failure WHEN cancellation also fails THEN the original upload failure is re-raised.

## Interfaces
- `FileMetadata(id: int, name: str, description: str | None = None, file_type: str | None = None, size: int | None = None, uri: str | None = None, created_at: datetime | None = None, updated_at: datetime | None = None)`
- `FileUpload(file_path: Path, name: str | None = None, description: str | None = None)`
- `ChunkedUploadSession(upload_id: str, file_name: str, total_chunks: int, chunks_uploaded: int = 0)`
- `FilesResource.upload(file_path: Path, name: str | None = None, description: str | None = None) -> FileMetadata`
- `FilesResource.upload_chunked(file_path: Path, chunk_size: int = 5242880, name: str | None = None, description: str | None = None) -> FileMetadata`
- `FilesResource.get(file_id: int) -> FileMetadata`, `download(file_id: int, output_path: Path) -> None`, `delete(file_id: int) -> None`
- `AsyncFilesResource.upload/upload_chunked/get/download/delete`
- `ChunkedUploader(client: StorageClient, chunk_size: int = 5242880).upload(file_path: Path, name: str | None = None, description: str | None = None) -> FileMetadata`
- `AsyncChunkedUploader(client: AsyncStorageClient, chunk_size: int = 5242880).upload(...) -> FileMetadata`
- `RelationshipCreate(from_item_id: int, to_item_id: int, relationship_type: str, properties: dict = {})`
- `Relationship(id: int = 0, from_item_id: int, to_item_id: int, relationship_type: str = "", properties: dict = {}, ...)`
- `BulkRelationshipCreate(relationships: list[RelationshipCreate])`
- `RelationshipsResource.create/get/delete/bulk_create/get_item_relationships/get_item_graph`
- `AsyncRelationshipsResource.create/get/delete/bulk_create/get_item_relationships/get_item_graph`
- `TimeseriesResource.query(record_id: int, view_name: str = "data", sql_query: str | None = None, *, limit: int | None = None, row_stride: int | None = None, start_row: int | None = None, stop_row: int | None = None, columns: Sequence[str] | None = None) -> TimeseriesResult`
- `TimeseriesResult(columns: list[str] = [], data: list[list[Any]] = [])`
- `AsyncTimeseriesResource.query` with the same signature

## Constraints
- File APIs expose file IDs as DeepLynx record IDs; downstream code must not assume a separate file-record ID namespace.
- Chunked upload does not define resumability; cancellation is best-effort cleanup only.
- Timeseries SQL validation and execution are backend responsibilities. The server accepts one statement that mentions the view name, rejects a list of keywords (`COPY`, `UPDATE`, `ATTACH` and others) as substrings, and opens a fresh query engine per request, so large files can take many seconds.

## Out of scope / Non-goals
- This package does not implement local file locking, checksum verification, or automatic MIME detection.
- Relationship graph traversal semantics beyond forwarding `depth` are not defined here.

## Open questions
- Chunked upload, relationship parser error paths and graph wrapping need focused unit tests.
- The sync/async parity suite currently covers item and search behavior more directly than file/relationship/timeseries behavior.
