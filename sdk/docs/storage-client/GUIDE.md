# Storage Client Library - Complete Guide

A full-featured Python client library that provides a clean, generic interface for storage operations. The library abstracts backend implementation details and offers both synchronous and asynchronous APIs.

## Features

- **Generic Terminology**: Uses intuitive terms like `Item`, `Relationship`, `Metadata` instead of backend-specific terminology
- **Dual API Support**: Both synchronous and asynchronous clients using httpx
- **Type Safety**: Fully typed with Pydantic models for validation and IDE support
- **Full Feature Set**:
  - CRUD operations for items
  - File upload/download (including chunked uploads for large files)
  - `fsspec` filesystem protocol (`deeplynx://`) for S3-style path workflows
  - Relationship management
  - Search and query capabilities
  - Timeseries data support
  - Bulk operations
  - Automatic pagination
  - Tag management

## Configuration

### Using Environment Variables (Recommended)

The easiest way to configure the client is using environment variables:

1. **Create a `.env` file** (copy from `.env.example`):
```bash
cp .env.example .env
```

2. **Edit `.env` with your credentials**:

Your `.env` file must contain:
- `DEEPLYNX_KEY` - Your API key
- `DEEPLYNX_SECRET` - Your API secret
- `DEEPLYNX_ORG_ID` - Your organization ID
- `DEEPLYNX_PROJECT_ID` - Your project ID

3. **Load configuration from environment**:
```python
from prometheus_api.storage_client import ConnectionConfig, StorageClient

# Automatically loads from .env file
config = ConnectionConfig.from_env()

with StorageClient(config) as client:
    # Use the client
    items = client.items.list()
```

**Benefits:**
- Keeps credentials out of code
- `.env` file is gitignored automatically
- Easy to switch between environments

**Supported Environment Variables:**
- `DEEPLYNX_KEY` - API key (required with DEEPLYNX_SECRET)
- `DEEPLYNX_SECRET` - API secret (required with DEEPLYNX_KEY)
- `DEEPLYNX_JWT_TOKEN` - JWT token (alternative to key/secret)
- `DEEPLYNX_ORG_ID` - Organization ID (required)
- `DEEPLYNX_PROJECT_ID` - Project ID (required)
- `DEEPLYNX_BASE_URL` - Custom base URL (optional)

### Manual Configuration

The `ConnectionConfig` class supports multiple configuration options:

```python
from prometheus_api.storage_client import ConnectionConfig

# Using API key authentication
config = ConnectionConfig(
    organization_id=123,
    project_id=456,
    api_key="your-api-key",
    api_secret="your-api-secret",
    base_url="https://api.example.com",  # Optional, has default
    timeout=30.0,  # Request timeout in seconds
    max_retries=3,  # Number of retry attempts
    verify_ssl=True  # SSL certificate verification
)

# Using JWT token authentication
config = ConnectionConfig(
    organization_id=123,
    project_id=456,
    jwt_token="your-jwt-token"
)
```

## API Reference

### Items Operations

```python
# Create a single item
item = client.items.create(ItemCreate(name="Test", properties={"key": "value"}))

# Get an item by ID
item = client.items.get(item_id=123)

# Update an item
updated = client.items.update(item_id=123, update=ItemUpdate(name="New Name"))

# Delete an item
client.items.delete(item_id=123)

# List items with pagination
page = client.items.list(page=1, page_size=100)

# Iterate over all items (automatic pagination)
for item in client.items.iter_all():
    print(item.name)

# Bulk create items
items = client.items.bulk_create([
    ItemCreate(name="Item 1"),
    ItemCreate(name="Item 2")
])

# Manage tags
item = client.items.add_tags(item_id=123, tags=["important", "reviewed"])
item = client.items.remove_tags(item_id=123, tags=["old-tag"])
```

### File Operations

```python
from pathlib import Path

# Upload a file
file_meta = client.files.upload(
    Path("data.csv"),
    description="Experiment data"
)

# Upload a large file in chunks
file_meta = client.files.upload_chunked(
    Path("large_file.zip"),
    chunk_size=10 * 1024 * 1024  # 10MB chunks
)

# Get file metadata
file_meta = client.files.get(file_id=123)

# Download a file
client.files.download(file_id=123, output_path=Path("downloaded.csv"))

# Delete a file
client.files.delete(file_id=123)
```

### DeepLynx Filesystem Operations (`fsspec`)

The library provides a filesystem implementation that maps `deeplynx://` URIs
to DeepLynx file records while preserving logical object paths in metadata.

#### Why use this

- Integrates with tooling built on top of `fsspec`.
- Supports path-based `put/get/glob/ls/rm` semantics similar to object stores.
- Avoids separate index records by storing path/version metadata on each file record.

#### Protocol registration

The protocol is exposed through Python entry points (`fsspec.specs`), so this works
for downstream packages that depend on `prometheus_api`:

```python
import fsspec

fs = fsspec.filesystem("deeplynx")
```

#### Initialization modes

`DeepLynxFileSystem(client=None, config=None, ...)` resolves in this order:

1. Use provided `client` directly.
2. Else create internal `StorageClient(config)` when `config` is provided.
3. Else load `ConnectionConfig.from_env()` and create an internal client.

```python
import fsspec
from prometheus_api.storage_client import ConnectionConfig, StorageClient

# Reuse an existing client
config = ConnectionConfig.from_env()
with StorageClient(config) as client:
    fs = fsspec.filesystem("deeplynx", client=client)
    fs.put("mesh.e", "deeplynx://session-abc/data/mesh.e")
    fs.get("deeplynx://session-abc/data/mesh.e", "./run/")

# Or let filesystem create/manage its own client
fs = fsspec.filesystem("deeplynx", config=ConnectionConfig.from_env())
```

#### Metadata contract

Files managed through the filesystem are tagged with:

- `_deeplynx_fs_managed`: marker indicating record belongs to this filesystem layer
- `_deeplynx_fs_path`: normalized POSIX object key (`session-abc/data/mesh.e`)
- `_deeplynx_fs_version_ns`: integer version timestamp from `time.time_ns()`

#### Versioning + path behavior

- Repeated `put()` to the same path creates additional versions (older versions retained).
- `get(path)` resolves the newest valid version for the exact path.
- Records missing/invalid `_deeplynx_fs_version_ns` are ignored for read resolution.
- `rm(file_path)` deletes all versions for that exact logical path.
- `rm(prefix, recursive=True)` deletes all versions under that prefix.

#### Lookup strategy

Path lookup is search-first and degrades gracefully:

1. `search.advanced_query(...)`
2. `search.query(...)` + exact metadata filtering
3. `search.recent(...)` (emits runtime warning)
4. `items.iter_all(...)` full scan fallback (emits runtime warning)

This keeps normal workflows efficient while still supporting DeepLynx deployments
where some search endpoints are unavailable.

#### Common filesystem operations

```python
# Upload files
fs.put("input.i", "deeplynx://session-abc/moose/input.i")
fs.put("./run-dir", "deeplynx://session-abc/", recursive=True)

# Download files
fs.get("deeplynx://session-abc/moose/input.i", "./local/")
fs.get("deeplynx://session-abc/run-dir", "./downloaded-run", recursive=True)

# List and glob
entries = fs.ls("deeplynx://session-abc", detail=False)
all_paths = fs.glob("deeplynx://session-abc/**", detail=False)

# Existence checks
fs.isfile("deeplynx://session-abc/moose/input.i")
fs.isdir("deeplynx://session-abc/moose")

# Delete paths
fs.rm("deeplynx://session-abc/moose/input.i")  # all versions of this key
fs.rm("deeplynx://session-abc/run-dir", recursive=True)  # recursive prefix delete
```

### Relationship Operations

```python
# Create a relationship
rel = client.relationships.create(RelationshipCreate(
    from_item_id=1,
    to_item_id=2,
    relationship_type="depends_on",
    properties={"strength": "high"}
))

# Get a relationship
rel = client.relationships.get(relationship_id=123)

# Delete a relationship
client.relationships.delete(relationship_id=123)

# Bulk create relationships
rels = client.relationships.bulk_create([
    RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="links"),
    RelationshipCreate(from_item_id=2, to_item_id=3, relationship_type="links")
])

# Get all relationships for an item
all_rels = client.relationships.get_item_relationships(item_id=123)
outgoing = client.relationships.get_item_relationships(item_id=123, direction="outgoing")

# Get relationship graph
graph = client.relationships.get_item_graph(item_id=123, depth=2)
```

### Search Operations

```python
# Simple text search
results = client.search.query("experiment data", page_size=50)

# Advanced search with filters
results = client.search.advanced_query(
    filters=[
        {
            "filter": "properties",
            "operator": "KEY_VALUE",
            "json": '{"status": "active", "priority": 5}',
        }
    ],
    project_ids=[client.config.project_id],
)

# Search by tags
results = client.search.by_tags(["important", "urgent"])
results = client.search.by_tags(["tag1", "tag2"], match_all=True)

# Get recent items
recent = client.search.recent(limit=50)
```

### Timeseries Operations

Tabular files (csv or parquet) are uploaded like any other file with `client.files.upload(...)`.
Query one by the ID of its record. The server exposes the file as a temporary SQL view named
`view_name`, and your query must mention that name:

```python
stored = client.files.upload(Path("sensor_data.csv"))

result = client.timeseries.query(
    record_id=stored.id,
    view_name="data",
    sql_query="SELECT * FROM data WHERE Timestamp > '2024-01-01'",
    limit=1000,
)
print(result.columns)   # ["Timestamp", ...]
print(result.data[:3])  # rows as lists, in column order
```

- Without `sql_query` you get the view's rows limited by `limit` (the server's default is 20).
- A missing value can arrive as `{}`, and one column can mix numbers and `{}`; cells are not
  converted.
- Quote column names that contain dots (`"a.b"`) inside `sql_query`. The `columns=` option
  rejects them.
- The server rejects statements containing words such as `UPDATE`, `COPY` or `ATTACH` anywhere,
  including inside a column name.
- Each call can take many seconds on a large file; raise `ConnectionConfig.timeout` if needed.

## Error Handling

The library provides custom exceptions for different error scenarios:

```python
from prometheus_api.storage_client.exceptions import (
    StorageClientError,      # Base exception
    AuthenticationError,     # Authentication failures
    ItemNotFoundError,       # Item not found (404)
    ValidationError,         # Validation errors (4xx)
    APIError                 # Other API errors (5xx)
)

try:
    item = client.items.get(item_id=999)
except ItemNotFoundError as e:
    print(f"Item {e.item_id} not found")
except AuthenticationError:
    print("Authentication failed")
except APIError as e:
    print(f"API error {e.status_code}: {e.message}")
```

## Advanced Usage

### Pagination

```python
# Manual pagination
page = client.items.list(page=1, page_size=50)
print(f"Page {page.page_info.page_number} of {page.page_info.total_pages}")
print(f"Total items: {page.page_info.total_count}")

if page.page_info.has_next:
    next_page = client.items.list(page=2, page_size=50)

# Automatic pagination
for item in client.items.iter_all(page_size=100):
    # Process each item across all pages
    process(item)
```

### Filtering

```python
# Filter items in list operation
results = client.items.list(
    page=1,
    page_size=100,
    filters={
        "properties.status": "active",
        "created_at": {"$gt": "2024-01-01"}
    }
)
```

### Bulk Operations

```python
# Create multiple items efficiently
items = client.items.bulk_create([
    ItemCreate(name=f"Item {i}", properties={"index": i})
    for i in range(100)
])

# Create multiple relationships
relationships = client.relationships.bulk_create([
    RelationshipCreate(
        from_item_id=items[i].id,
        to_item_id=items[i+1].id,
        relationship_type="next"
    )
    for i in range(len(items) - 1)
])
```

### Asynchronous Usage

```python
import asyncio
from prometheus_api.storage_client import AsyncStorageClient, ConnectionConfig, ItemCreate

async def main():
    config = ConnectionConfig(
        organization_id=123,
        project_id=456,
        api_key="your-api-key",
        api_secret="your-api-secret"
    )

    async with AsyncStorageClient(config) as client:
        # Create items
        item = await client.items.create(ItemCreate(
            name="Async Item",
            properties={"key": "value"}
        ))

        # List items with pagination
        page = await client.items.list(page=1, page_size=50)
        for item in page.items:
            print(f"Item: {item.name}")

        # Iterate over all items automatically
        async for item in client.items.iter_all(page_size=100):
            print(f"Processing: {item.name}")

asyncio.run(main())
```

## Architecture

The library is organized into several key components:

- **Client Layer** (`client.py`, `async_client.py`): Main entry points with context manager support
- **Resource Layer** (`resources/`, `async_resources/`): Organized API operations by domain
- **Models Layer** (`models/`): Pydantic data models for type safety and validation
- **Auth Layer** (`auth.py`): Automatic JWT token management and refresh
- **Utilities** (`utils/`): Helper functions for pagination, streaming, etc.

All backend-specific terminology and identifiers are hidden from the public API, providing a clean, generic interface.

## Development

### Running Tests

```bash
uv sync
make test
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Type checking
uv run mypy prometheus_api/
```

## Next Steps

- See the [Quick Start Guide](QUICK_START.md) for a condensed reference
- Check [ENV_SETUP.md](../ENV_SETUP.md) for environment configuration
- Run the examples in `examples/`
