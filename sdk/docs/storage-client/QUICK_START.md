# Storage Client - Quick Start Guide

## Installation

```bash
pip install "git+https://github.com/idaholab/prometheus_core.git#subdirectory=sdk"
```

Or install in development mode:
```bash
git clone https://github.com/idaholab/prometheus_core.git
cd prometheus_core/sdk
uv sync
```

## Setup Credentials

**Using .env file (Recommended):**

```bash
# 1. Copy the example file
cp .env.example .env

# 2. Edit .env and add your actual credentials
#    (see .env.example for the required variable names)
```

## Basic Usage (30 seconds)

```python
from prometheus_api.storage_client import StorageClient, ConnectionConfig, ItemCreate

# 1. Configure connection (from .env file)
config = ConnectionConfig.from_env()

# Or configure manually:
# config = ConnectionConfig(
#     organization_id=123,
#     project_id=456,
#     api_key="your-api-key",
#     api_secret="your-api-secret"
# )

# 2. Create a client and use it
with StorageClient(config) as client:
    # Create an item
    item = client.items.create(ItemCreate(
        name="My First Item",
        properties={"key": "value"},
        tags=["example"]
    ))

    print(f"Created item {item.id}: {item.name}")
```

## Common Operations Cheat Sheet

### Items

```python
# Create
item = client.items.create(ItemCreate(name="Item", properties={"k": "v"}))

# Get
item = client.items.get(item_id=123)

# Update
updated = client.items.update(123, ItemUpdate(name="New Name"))

# Delete
client.items.delete(123)

# List with pagination
page = client.items.list(page=1, page_size=50)

# Iterate all (auto-pagination)
for item in client.items.iter_all():
    print(item.name)

# Bulk create
items = client.items.bulk_create([ItemCreate(name=f"Item {i}") for i in range(10)])

# Tags
client.items.add_tags(123, ["tag1", "tag2"])
client.items.remove_tags(123, ["old-tag"])
```

### Files

```python
from pathlib import Path

# Upload
file_meta = client.files.upload(Path("data.csv"), description="My data")

# Download
client.files.download(file_id=123, output_path=Path("output.csv"))

# Large file (chunked)
file_meta = client.files.upload_chunked(Path("large.zip"), chunk_size=10*1024*1024)

# Delete
client.files.delete(123)
```

### Relationships

```python
from prometheus_api.storage_client import RelationshipCreate

# Create relationship
rel = client.relationships.create(RelationshipCreate(
    from_item_id=1,
    to_item_id=2,
    relationship_type="related_to"
))

# Get item's relationships
rels = client.relationships.get_item_relationships(item_id=1)

# Get relationship graph
graph = client.relationships.get_item_graph(item_id=1, depth=2)

# Bulk create
rels = client.relationships.bulk_create([
    RelationshipCreate(from_item_id=1, to_item_id=2, relationship_type="links"),
    RelationshipCreate(from_item_id=2, to_item_id=3, relationship_type="links")
])
```

### Search

```python
# Simple text search
results = client.search.query("experiment data")

# Search by tags (any match)
results = client.search.by_tags(["important", "urgent"])

# Search by tags (all match)
results = client.search.by_tags(["tag1", "tag2"], match_all=True)

# Advanced search
results = client.search.advanced_query(
    filters=[
        {
            "filter": "properties",
            "operator": "KEY_VALUE",
            "json": '{"status": "active"}',
        }
    ],
    project_ids=[client.config.project_id],
)

# Recent items
recent = client.search.recent(limit=50)
```

## DeepLynx Filesystem (fsspec)

The storage client includes a native `fsspec` filesystem protocol: `deeplynx://`.
It is registered via Python entry points, so downstream projects can call
`fsspec.filesystem("deeplynx", ...)` without importing internal registration code.

### Quick Example

```python
import fsspec
from prometheus_api.storage_client import ConnectionConfig, StorageClient

# Option 1: Provide an existing client
config = ConnectionConfig.from_env()
with StorageClient(config) as client:
    fs = fsspec.filesystem("deeplynx", client=client)
    fs.put("mesh.e", "deeplynx://session-abc/data/mesh.e")
    fs.get("deeplynx://session-abc/data/mesh.e", "./run/")

# Option 2: Let filesystem create an internal client from config
fs = fsspec.filesystem("deeplynx", config=ConnectionConfig.from_env())
fs.put("input.i", "deeplynx://session-abc/moose/input.i")
```

### Constructor Behavior

`DeepLynxFileSystem(client=None, config=None, ...)` resolves inputs in this order:

1. Use `client` if provided.
2. Else build internal `StorageClient(config)` if `config` is provided.
3. Else default to `ConnectionConfig.from_env()`.

### Path + Versioning Semantics

- `put()` stores path metadata on each uploaded record (no separate index table).
- Repeated `put()` to the same path keeps prior versions.
- `get()` resolves the latest valid version for that exact path.
- `rm("deeplynx://path/to/file")` deletes all versions of that logical path.
- `rm("deeplynx://path/to/prefix", recursive=True)` deletes all versions under that prefix.

### Recursive Workflows

```python
# Upload a local directory tree
fs.put("./moose-run", "deeplynx://session-abc/", recursive=True)

# Fetch a whole prefix locally
fs.get("deeplynx://session-abc/moose-run", "./downloaded-run", recursive=True)
```

## Async Usage

```python
from prometheus_api.storage_client import AsyncStorageClient
import asyncio

async def main():
    config = ConnectionConfig(...)

    async with AsyncStorageClient(config) as client:
        # Same API, just add 'await'
        item = await client.items.create(ItemCreate(name="Async"))
        items = await client.items.list(page=1, page_size=100)

        # Async iteration
        async for item in client.items.iter_all():
            print(item.name)

asyncio.run(main())
```

## Authentication Options

### Environment Variables (Recommended)
```python
# Load from .env file
config = ConnectionConfig.from_env()

# Or load from specific file
config = ConnectionConfig.from_env(env_file=Path("config/prod.env"))

# Or override specific values
config = ConnectionConfig.from_env(
    organization_id=999,  # Override env var
    timeout=60.0
)
```

### API Key (manual)
```python
config = ConnectionConfig(
    organization_id=123,
    project_id=456,
    api_key="your-key",
    api_secret="your-secret"
)
```

### JWT Token (manual)
```python
config = ConnectionConfig(
    organization_id=123,
    project_id=456,
    jwt_token="your-token"
)
```

## Error Handling

```python
from prometheus_api.storage_client.exceptions import (
    ItemNotFoundError,
    AuthenticationError,
    ValidationError,
    APIError
)

try:
    item = client.items.get(999)
except ItemNotFoundError as e:
    print(f"Item {e.item_id} not found")
except AuthenticationError:
    print("Auth failed - check credentials")
except ValidationError as e:
    print(f"Validation error: {e.message}")
except APIError as e:
    print(f"API error {e.status_code}: {e.message}")
```

## Configuration Options

```python
config = ConnectionConfig(
    organization_id=123,
    project_id=456,
    api_key="key",
    api_secret="secret",

    # Optional settings
    base_url="https://custom.api.com/v1",  # Default: DeepLynx INL
    timeout=60.0,                           # Request timeout (seconds)
    max_retries=5,                          # Retry attempts
    verify_ssl=True                         # SSL verification
)
```

## Common Patterns

### Create item with file
```python
item = client.items.create(ItemCreate(name="Analysis"))
file_meta = client.files.upload(Path("data.csv"))
client.relationships.create(RelationshipCreate(
    from_item_id=item.id,
    to_item_id=file_meta.id,
    relationship_type="has_data"
))
```

### Bulk operations with progress
```python
items_to_create = [ItemCreate(name=f"Item {i}") for i in range(100)]
items = client.items.bulk_create(items_to_create)
print(f"Created {len(items)} items")
```

### Search and filter
```python
# Find all active experiments
results = client.search.advanced_query(
    filters=[
        {
            "filter": "properties",
            "operator": "KEY_VALUE",
            "json": '{"type": "experiment", "status": "active"}',
        }
    ],
    project_ids=[client.config.project_id],
)

for item in results.items:
    print(f"{item.name}: {item.properties}")
```

## Key Concepts

1. **Items** = Data records with properties and tags
2. **Relationships** = Connections between items
3. **Files** = Uploaded files linked to items
4. **Properties** = Custom key-value metadata on items
5. **Tags** = Labels for organizing and searching items

## Quick Tips

- Use context managers (`with` / `async with`) for automatic cleanup
- Use `iter_all()` for automatic pagination
- Use bulk operations for creating many items at once
- All fields are type-checked with Pydantic
- IDs are integers, not strings
- Properties can be any JSON-serializable dict
- Tags are strings

## Next Steps

1. Read the full [Guide](GUIDE.md) for detailed documentation
2. Check [ENV_SETUP.md](../ENV_SETUP.md) for environment configuration
3. Run the examples in `examples/`
4. Start building your application!
