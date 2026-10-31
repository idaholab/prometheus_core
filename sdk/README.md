# Prometheus API

A Python toolkit for building data-driven applications with storage operations and A2A-enabled agents.

## Components

| Component | Description | Documentation |
|-----------|-------------|---------------|
| **StorageClient** | Full-featured client for storage operations with sync/async APIs | [Guide](docs/storage-client/GUIDE.md) \| [Quick Start](docs/storage-client/QUICK_START.md) |
| **PrometheusAgent** | Base class for building A2A-enabled agents with minimal boilerplate | [Guide](docs/agent/GUIDE.md) \| [Quick Start](docs/agent/QUICK_START.md) \| [Multi-User](docs/agent/MULTI_USER.md) |
| **LLMClient** | Provider-agnostic LiteLLM chat, embedding, and tool-calling client with sync/async APIs | [Environment Setup](docs/ENV_SETUP.md#llmclient-configuration) |

## Installation

See [INSTALL.md](INSTALL.md) for full options. Quick paths:

- **For development:** `git clone … && cd prometheus_core/sdk && uv sync` (then `make check`, `make test`)

## Quick Start - StorageClient

```python
from prometheus_api.storage_client import StorageClient, ConnectionConfig, ItemCreate

# Configure from environment variables
config = ConnectionConfig.from_env()

with StorageClient(config) as client:
    # Create an item
    item = client.items.create(ItemCreate(
        name="My Item",
        properties={"key": "value"},
        tags=["example"]
    ))

    # Upload a file
    file_meta = client.files.upload(Path("data.csv"))

    # Search
    results = client.search.by_tags(["example"])
```

**[Full StorageClient Guide](docs/storage-client/GUIDE.md)** | **[Quick Reference](docs/storage-client/QUICK_START.md)**

## Quick Start - PrometheusAgent

```python
from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext

class MyAgent(PrometheusAgent):
    async def _execute(self, params, context: RequestContext, event_queue: EventQueue):
        return {
            "conversation_id": context.context_id,
            "status": "completed",
            "message": "Request handled.",
        }

if __name__ == "__main__":
    agent = MyAgent(agent_name="My Agent")
    agent.run()
```

**[Full PrometheusAgent Guide](docs/agent/GUIDE.md)** | **[Quick Reference](docs/agent/QUICK_START.md)**

## Quick Start - LLMClient

```python
from prometheus_api.llm_client import LLMClient

llm = LLMClient()
response = llm("Summarize this DeepLynx record.")
print(response.text)

vector_response = llm.embedding("bearing temperature rising")
print(vector_response.embeddings[0])
```

```python
from prometheus_api.agent import PrometheusAgent

class AnalysisAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        async with self.llm_client(context) as llm:
            response = await llm.medium(params["query"])
        return {"status": "completed", "answer": response.text}
```

## Environment Variables

### StorageClient

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPLYNX_KEY` | API key | Yes* |
| `DEEPLYNX_SECRET` | API secret | Yes* |
| `DEEPLYNX_ORG_ID` | Organization ID | Yes |
| `DEEPLYNX_PROJECT_ID` | Project ID | Yes |
| `DEEPLYNX_BASE_URL` | Custom API URL | No |

*Or use `DEEPLYNX_JWT_TOKEN` instead

### PrometheusAgent

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_PORT` | Port uvicorn binds to | `8000` |
| `EXTERNAL_AGENT_URL` | Full URL advertised to the registry (e.g. `http://my-host:9002`). When absent, auto-derived from the container hostname and `AGENT_PORT`. | auto |
| `AGENT_WORKFLOWS` | Directory of JSON/YAML workflow templates inserted into the raw agent card. Relative paths resolve next to `agent_card.json`. | `workflows` |
| `AGENT_SECRET` | Shared secret for auth | - |
| `REGISTRY_URL` | LiteLLM registry/proxy URL used for agent registration | `http://litellm:4000` |
| `REGISTRY_MAX_RETRIES` | Registration retries after the first attempt, used for both explicit `REGISTRY_URL` and the built-in fallback URL. | `10` |
| `REGISTRY_CHECK_INTERVAL_SECONDS` | After startup, how often the agent checks the registry still lists it, re-registering if not (a registry restarted or cleared under a running agent). `0` disables. | `60` |

### LLMClient

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_CONFIG_PROFILE` | Installed profile: `registry`, `inl_hpc`, `inl_litellm`, `amsc`, `anthropic`, `openai`, or `anl_asksage` | `registry` |
| `LLM_CONFIG_FILE` | Custom LiteLLM YAML path; overrides `LLM_CONFIG_PROFILE` | - |
| `REGISTRY_URL` | LiteLLM proxy URL read by the installed `registry` profile | - |
| `LLM_DEBUG_LOG_MESSAGES` | Include redacted prompt/embedding content in debug logs | `false` |
| `ENABLE_MLFLOW_TRACING` | Enable optional MLflow tracing for LLM chat calls | `false` |

When `ENABLE_MLFLOW_TRACING=true`, install `mlflow` in the runtime environment
and configure `MLFLOW_TRACKING_URI` and optionally `MLFLOW_EXPERIMENT_NAME`.
`MLFLOW_API_KEY` is forwarded as `X-Api-Key` on MLflow REST calls when present.

**[Full Environment Setup Guide](docs/ENV_SETUP.md)**

## Documentation

| Document | Description |
|----------|-------------|
| [**Writing an Agent (Tutorial)**](https://github.com/idaholab/prometheus_core/tree/devel/agent-template) | Step-by-step guide and scaffolder for building, containerizing, and deploying a new specialist agent (lives in the `agent-template/` directory of this monorepo) |
| [StorageClient Guide](docs/storage-client/GUIDE.md) | Complete StorageClient API reference |
| [StorageClient Quick Start](docs/storage-client/QUICK_START.md) | Condensed reference and examples |
| [PrometheusAgent Guide](docs/agent/GUIDE.md) | Complete PrometheusAgent documentation |
| [PrometheusAgent Quick Start](docs/agent/QUICK_START.md) | Minimal agent setup guide |
| [LLMClient Migration Guide](docs/agent/LLM_CLIENT_MIGRATION.md) | Move agents from vendor-specific LLM code to `LLMClient` |
| [Environment Setup](docs/ENV_SETUP.md) | Environment variables for both components |
| [Testing Guide](docs/TESTING.md) | Running and writing tests |
| [Installation Guide](INSTALL.md) | Detailed installation options |
| [Development Guide](DEVELOPMENT.md) | Architecture, commands, and conventions |

## Features

### StorageClient
- CRUD operations for items
- File upload/download (including chunked uploads)
- Relationship management
- Search and query capabilities
- Timeseries data support
- Bulk operations
- Automatic pagination
- Sync and async APIs
- Type safety with Pydantic

### PrometheusAgent
- Automatic agent card loading
- Built-in Bearer token authentication
- Background registry registration during app startup, re-registered if the registry later forgets the agent
- HTTP server setup with A2A protocol
- Optional `message/stream` support (`agent_card.capabilities.streaming=true`)
- Final response emission from the returned `_execute(...)` dict
- Status updates, native artifacts, and `INPUT_REQUIRED` helpers
- Per-agent context-state persistence keyed by `contextId`
- 95% reduction in boilerplate code

### LLMClient
- Sync and async chat calls with generic aliases (`default`, `small`, `medium`, `large`, `vision`)
- Embeddings through the `embedding` alias
- Tool calling on any chat alias: typed `ToolCall` / `ToolDefinition`, replayable tool history, and forced single-tool calls
- Installed LiteLLM profiles for registry, INL HPC, AMSc, Anthropic, and OpenAI inference
- Optional MLflow tracing for sync and async chat calls
- Prompt-safe debug logging with opt-in redacted content logging

## Examples

See the `examples/` directory for working code:
- `basic_usage.py` - StorageClient CRUD operations
- `async_usage.py` - Async/await patterns
- `file_operations.py` - File upload/download
- `bulk_operations.py` - Bulk operations
- `agent_patterns.py` - PrometheusAgent status, artifacts, input requests, and stateful resume
- `llm_client_usage.py` - Provider-agnostic LLMClient chat and embedding calls
- `llm_tool_calling_usage.py` - LLM tool calling: definitions, parsing, and replaying tool results
- `llm_agent_usage.py` - PrometheusAgent using AsyncLLMClient from A2A context
- `env_config_usage.py` - Loading `ConnectionConfig` from `.env`
- `list_datasources.py` - Print available DeepLynx data source IDs for your project
- `verify_connection.py` - Manual DeepLynx connection smoke test

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) and [INSTALL.md](INSTALL.md#development) for setup. The common loop is:

```bash
make check    # ruff + mypy
make test     # pytest (unit only)
make test-integration  # DeepLynx tests, requires .env
make hooks    # install pre-commit/pre-push hooks
make fix      # auto-fix lint and format
```

## License

MIT License

## Support

For issues and questions, please contact your system administrator or open an issue in the repository.
