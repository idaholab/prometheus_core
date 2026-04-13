---
title: API
description: Description of page
icon: lucide/book-open
---

# Prometheus API

A Python toolkit that provides two main components:

1. **StorageClient** -- full-featured client for storage operations (sync and async) backed by DeepLynx
2. **PrometheusAgent** -- base class for building A2A-enabled agents with minimal boilerplate

## Installation

```bash
# Basic (StorageClient only)
pip install git+https://github.inl.gov/genesis/prometheus_api.git

# With agent support
pip install "git+https://github.inl.gov/genesis/prometheus_api.git#egg=prometheus-api[agent]"

# Editable / development
git clone https://github.inl.gov/genesis/prometheus_api.git
cd prometheus_api
pip install -e ".[dev]"
```

### Dependencies

=== "Core"

    - `httpx>=0.24.0`
    - `pydantic>=2.0.0`
    - `python-dateutil>=2.8.0`
    - `python-dotenv>=1.0.0`

=== "Agent extra"

    - `starlette>=0.27.0`
    - `uvicorn[standard]>=0.27.0`
    - `a2a-sdk[http-server]>=0.3.0`

=== "Dev extra"

    - `pytest`, `pytest-asyncio`, `pytest-cov`
    - `black`, `mypy`, `ruff`

## StorageClient

### Configuration

Create a `.env` file (see `.env.example` in the repo):

```bash
# Authentication -- choose one method
# Method 1: API key pair (recommended)
DEEPLYNX_KEY=your-api-key
DEEPLYNX_SECRET=your-api-secret

# Method 2: JWT token
# DEEPLYNX_JWT_TOKEN=your-jwt-token

# Required
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456

# Optional
DEEPLYNX_DATA_SOURCE_ID=789
DEEPLYNX_BASE_URL=https://deeplynx.inl.gov/api/v1
DEEPLYNX_TIMEOUT=30.0
DEEPLYNX_MAX_RETRIES=3
DEEPLYNX_VERIFY_SSL=true
```

Load it:

```python
from prometheus_api.storage_client import ConnectionConfig

config = ConnectionConfig.from_env()  # reads .env automatically
```

Or configure manually:

```python
config = ConnectionConfig(
    organization_id=123,
    project_id=456,
    api_key="your-api-key",
    api_secret="your-api-secret",
)
```

### Synchronous usage

```python
from prometheus_api.storage_client import StorageClient, ItemCreate, ItemUpdate
from pathlib import Path

config = ConnectionConfig.from_env()

with StorageClient(config) as client:
    # Items
    item = client.items.create(ItemCreate(
        name="Experiment A",
        properties={"status": "active", "priority": 5}
    ))
    item = client.items.get(item_id=item.id)
    client.items.update(item.id, ItemUpdate(name="Experiment A (revised)"))
    client.items.delete(item.id)

    # Pagination
    page = client.items.list(page=1, page_size=100)
    for item in client.items.iter_all(page_size=50):
        print(item.name)

    # Bulk operations
    items = client.items.bulk_create([
        ItemCreate(name=f"Item {i}") for i in range(100)
    ])

    # Tags
    client.items.add_tags(item_id=1, tags=["reviewed"])
    client.items.remove_tags(item_id=1, tags=["draft"])

    # Files
    meta = client.files.upload(Path("data.csv"), description="Results")
    client.files.upload_chunked(Path("large.zip"), chunk_size=10*1024*1024)
    client.files.download(file_id=meta.id, output_path=Path("out.csv"))

    # Relationships
    from prometheus_api.storage_client import RelationshipCreate
    client.relationships.create(RelationshipCreate(
        from_item_id=1, to_item_id=2,
        relationship_type="depends_on"
    ))
    rels = client.relationships.get_item_relationships(
        item_id=1, direction="outgoing"
    )

    # Search
    results = client.search.query("experiment data")
    results = client.search.by_tags(["reviewed"])
    results = client.search.advanced_query({
        "properties.status": "active"
    })

    # Timeseries
    client.timeseries.upload(Path("sensor.csv"), data_source_id=456)
    client.timeseries.query(
        data_source_id=456,
        sql_query="SELECT * FROM sensor_data WHERE timestamp > '2024-01-01'"
    )
```

### Asynchronous usage

```python
import asyncio
from prometheus_api.storage_client import AsyncStorageClient, ConnectionConfig, ItemCreate

config = ConnectionConfig.from_env()

async def main():
    async with AsyncStorageClient(config) as client:
        item = await client.items.create(ItemCreate(name="Test"))

        async for item in client.items.iter_all(page_size=50):
            print(item.name)

        # Concurrent operations
        results = await asyncio.gather(
            client.search.query("test"),
            client.items.list(),
        )

asyncio.run(main())
```

### Data models

**Items**

```python
from prometheus_api.storage_client import Item, ItemCreate, ItemUpdate, Tag

ItemCreate(name="...", description="...", properties={}, tags=["..."])
ItemUpdate(name="...", properties={})  # all fields optional
Item(id=1, name="...", properties={}, tags=[Tag(...)], created_at=..., updated_at=...)
```

**Relationships**

```python
from prometheus_api.storage_client import Relationship, RelationshipCreate

RelationshipCreate(
    from_item_id=1, to_item_id=2,
    relationship_type="depends_on",   # also: "related_to", "has_data_file"
    properties={}
)
```

**Files**

```python
from prometheus_api.storage_client import FileMetadata

FileMetadata(id=1, name="data.csv", file_type="csv", size=1024, ...)
```

**Pagination**

```python
from prometheus_api.storage_client import Page, PageInfo

page = client.items.list(page=1, page_size=100)
page.items        # list of Item
page.page_info    # PageInfo with total_count, has_next, total_pages
```

### Error handling

```python
from prometheus_api.storage_client import (
    StorageClientError,   # base
    AuthenticationError,  # 401
    ItemNotFoundError,    # 404 (has .item_id)
    ValidationError,      # 4xx (has .details)
    APIError,             # other (has .status_code, .response_data)
)

try:
    client.items.get(item_id=999)
except ItemNotFoundError as e:
    print(f"Item {e.item_id} not found")
except AuthenticationError:
    print("Invalid credentials")
```

## PrometheusAgent

Base class that handles A2A protocol boilerplate. You override one method -- `process_analysis` -- and call `run()`.

### Minimal example

```python
from prometheus_api.agent import PrometheusAgent

class MyAgent(PrometheusAgent):
    async def process_analysis(self, params, context, event_queue):
        data = params.get("input_data")
        return {"status": "success", "result": data}

if __name__ == "__main__":
    agent = MyAgent(agent_name="My Agent")
    agent.run()
```

Each agent needs an `agent_card.json` alongside the script:

```json
{
  "name": "My Agent",
  "description": "What this agent does",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "process_analysis",
      "name": "Process Analysis",
      "description": "Analyzes input data",
      "tags": ["analysis"]
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"]
}
```

### Configuration

```bash
# Server
AGENT_PORT=8000
AGENT_HOST=localhost

# Authentication
AGENT_SECRET=your-secret          # enables Bearer token auth
AGENT_SECRET_REQUIRED=true

# LiteLLM agent gateway (optional, used for agent registration/routing)
LITELLM_URL=http://litellm:4000
LITELLM_MASTER_KEY=your-litellm-master-key

# Enterprise proxy / CA certs
HTTP_PROXY=...
SSL_CERT_FILE=/path/to/cert.pem
```

### Progress updates

For long-running tasks, send status updates to the client:

```python
from prometheus_api.agent import (
    PrometheusAgent, EventQueue, RequestContext,
    TaskState, TaskStatus, TaskStatusUpdateEvent,
)

class LongRunningAgent(PrometheusAgent):
    async def process_analysis(self, params, context, event_queue):
        # Notify: working
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=context.task_id,
                contextId=context.context_id,
                final=False,
                status=TaskStatus(state=TaskState.working),
            )
        )

        result = await self.do_heavy_work(params)
        return {"status": "success", "result": result}
```

### Using StorageClient inside an agent

```python
from prometheus_api.agent import PrometheusAgent
from prometheus_api.storage_client import StorageClient, ConnectionConfig, ItemCreate

class StorageAgent(PrometheusAgent):
    def __init__(self):
        super().__init__("Storage Agent")
        self.storage_config = ConnectionConfig.from_env()

    async def process_analysis(self, params, context, event_queue):
        with StorageClient(self.storage_config) as client:
            item = client.items.create(ItemCreate(
                name=params.get("name", "Unknown"),
                properties=params
            ))
        return {"status": "success", "item_id": item.id}
```

### Built-in endpoints

Every agent automatically exposes:

| Path | Description |
|------|-------------|
| `/health` | Health check (exempt from auth) |
| `/.well-known/agent.json` | Agent card (exempt from auth) |
| `/message` | A2A message endpoint (JSON-RPC 2.0) |

### Agent lifecycle

When `agent.run()` is called:

1. Loads `agent_card.json` from disk
2. Creates an executor wrapping `process_analysis()`
3. Sets up a Starlette HTTP server with the A2A SDK
4. Adds health endpoint and Bearer token middleware (if `AGENT_SECRET` is set)
5. Registers with LiteLLM (if `LITELLM_URL` is set)
6. Starts uvicorn

## Testing

```bash
cd prometheus_api

# All tests
pytest tests/

# Unit tests only (no external dependencies)
pytest -m unit tests/

# With coverage
pytest --cov=prometheus_api tests/
```

Test markers: `unit`, `integration` (requires `.env`), `slow`.

## Package structure

```
prometheus_api/
  prometheus_api/
    storage_client/
      client.py            # Synchronous client
      async_client.py      # Asynchronous client
      connection.py        # ConnectionConfig
      auth.py              # Token refresh handlers
      exceptions.py        # Custom exceptions
      models/              # Item, File, Relationship, Pagination, Timeseries
      resources/           # Sync resource handlers (items, files, etc.)
      async_resources/     # Async resource handlers
    agent/
      base.py              # PrometheusAgent, PrometheusAgentExecutor
      middleware.py         # BearerTokenMiddleware
  examples/                # Working code examples
  tests/                   # pytest suite
```
