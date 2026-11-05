# Environment Variable Setup Guide

This guide covers environment configuration for the StorageClient, PrometheusAgent, and
LLMClient components.

## Quick Setup

1. **Copy the template:**
```bash
cp .env.example .env
```

2. **Edit `.env` with your values:**
```bash
vim .env
# or
nano .env
```

3. **Use in your code:**
```python
# StorageClient
from prometheus_api.storage_client import ConnectionConfig, StorageClient
config = ConnectionConfig.from_env()

# PrometheusAgent
from prometheus_api.agent import PrometheusAgent
# Reads env vars automatically via run()

# LLMClient
from prometheus_api.llm_client import LLMClient
# Reads LLM_* and REGISTRY_URL automatically
llm = LLMClient()
```

---

## Agent Configuration

Environment variables for `PrometheusAgent`:

For base-agent behavior changes and migration examples, see
[`docs/agent/AGENT_MIGRATIONS.md`](agent/AGENT_MIGRATIONS.md).

### Agent Server

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `AGENT_PORT` | Port uvicorn binds to (internal) | `8000` | No |
| `EXTERNAL_AGENT_URL` | Full URL advertised to the registry. Set this when the agent is port-mapped or on a different host from the registry. When absent, the URL is derived automatically from the container hostname and `AGENT_PORT`. | auto | No |

**How the two variables relate:**

`AGENT_PORT` is always the port uvicorn listens on inside the container. `EXTERNAL_AGENT_URL` is what the registry (LiteLLM) uses to reach the agent. In the common case — where the agent and registry share a Docker network — you only need `AGENT_PORT`: Docker sets the container hostname to the service name, so the URL is derived automatically as `http://<service-name>:<AGENT_PORT>`.

Set `EXTERNAL_AGENT_URL` only when the agent is accessed through a port mapping or is on a separate host:

```yaml
# docker-compose.yml — port-mapped / external agent
ports:
  - "9002:8000"   # 9002 is the external port; 8000 is what AGENT_PORT is set to
environment:
  AGENT_PORT: 8000                          # internal bind port (matches container side of the mapping)
  EXTERNAL_AGENT_URL: http://my-host:9002   # external port (matches host side of the mapping)
```

### Agent Authentication

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `AGENT_SECRET` | Shared secret for Bearer token auth | - | Yes (production) |
| `AGENT_SECRET_REQUIRED` | Enforce authentication | `true` | No |

When `AGENT_SECRET_REQUIRED=true`, `AGENT_SECRET` must be set or agent app startup fails fast.
Set `AGENT_SECRET_REQUIRED=false` only for local unauthenticated development.

### Agent Registry

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `REGISTRY_URL` | LiteLLM registry/proxy URL for auto-registration | `http://litellm:4000` | No |
| `REGISTRY_MAX_RETRIES` | Registration retries after the first attempt, used for both explicit `REGISTRY_URL` and the built-in fallback URL. | `10` | No |
| `REGISTRY_CHECK_INTERVAL_SECONDS` | After startup, how often the agent checks the registry still lists it, re-registering if not (the registry was cleared, or startup registration gave up). `0` disables; a negative or non-finite value uses the default; the minimum is `0.1`. Skipped for an agent that overrides `register_with_registry_async`. | `5` | No |

Registry registration is started as a background async task during the agent app lifespan so
the HTTP server can start while the LiteLLM registry is still becoming ready. After it, the same
task checks every `REGISTRY_CHECK_INTERVAL_SECONDS` that the registry still lists the agent and
registers it again if not, including when the startup retries ran out.

### Example Agent .env

```bash
# Agent Server
AGENT_PORT=8000
# EXTERNAL_AGENT_URL=http://my-host:9002  # only needed for port-mapped / cross-host deployments

# Authentication
AGENT_SECRET=your-shared-secret-here
AGENT_SECRET_REQUIRED=true

# Registry (optional)
REGISTRY_URL=http://litellm:4000
# REGISTRY_MAX_RETRIES=10
# REGISTRY_CHECK_INTERVAL_SECONDS=5
```

### Agent Usage

```python
from prometheus_api.agent import PrometheusAgent

class MyAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        return {
            "conversation_id": context.context_id,
            "status": "completed",
            "message": "Request handled.",
        }

if __name__ == "__main__":
    agent = MyAgent(agent_name="My Agent")
    agent.run()  # Reads AGENT_* env vars automatically
```

---

## LLMClient Configuration

`LLMClient` and `AsyncLLMClient` load `LLMConfig.from_env()` automatically unless you pass
an explicit config.

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `LLM_CONFIG_PROFILE` | Installed configuration profile: `registry`, `inl_hpc`, `inl_litellm`, `amsc`, `anthropic`, `openai`, or `anl_asksage`. | `registry` | No |
| `LLM_CONFIG_FILE` | Custom LiteLLM YAML path. This overrides `LLM_CONFIG_PROFILE`. | - | No |
| `REGISTRY_URL` | LiteLLM registry/proxy URL referenced by the installed `registry` profile. | - | For `registry` |
| `LLM_DEBUG_LOG_MESSAGES` | Include normalized messages and embedding inputs in debug logs after secret redaction. Prompt content is hidden when `false`. | `false` | No |
| `ENABLE_MLFLOW_TRACING` | Enable optional MLflow tracing for sync and async LLM chat calls. | `false` | No |

### Example LLMClient .env

```bash
REGISTRY_URL=http://litellm:4000
LLM_CONFIG_PROFILE=registry
LLM_DEBUG_LOG_MESSAGES=false
ENABLE_MLFLOW_TRACING=false
```

Every configuration is a YAML file. Selection order is `LLM_CONFIG_FILE`, then
`LLM_CONFIG_PROFILE`, then the installed `registry` profile. The `registry`
profile contains `proxy_url: os.environ/REGISTRY_URL`; the provider profiles
contain the `default`, `small`, `medium`, `large`, `vision`, and `embedding`
flavors and read credentials from environment variables. Agent code chooses a
flavor; it never chooses the provider model mapped to that flavor.

### Optional MLflow Tracing

Set `ENABLE_MLFLOW_TRACING=true` to trace `LLMClient.chat` and
`AsyncLLMClient.chat` calls. MLflow is imported only when tracing is enabled.
Install `mlflow` in the runtime environment before enabling this setting.
Configure the tracking server with standard MLflow variables:

```bash
ENABLE_MLFLOW_TRACING=true
MLFLOW_TRACKING_URI=https://mlflow.example.org
MLFLOW_EXPERIMENT_NAME=prometheus-llm
MLFLOW_API_KEY=your-mlflow-api-key
```

When `MLFLOW_API_KEY` is present, the client injects it into MLflow REST calls as
`X-Api-Key`. If it is absent, the client logs a warning and continues.

Each chat trace includes protected `app_name`, `base_url`, and `model` tags.
Agents should use `self.llm_client(context)` so `app_name` inherits the agent
name. Additional tags can be set when constructing `LLMConfig`, creating the
client, or calling `chat(..., trace_tags={...})`; protected tags always win.

To customize a profile without modifying the installed package, copy the
tracked example:

```bash
cp llm_config.example.yaml llm_config.yaml
export LLM_CONFIG_FILE=./llm_config.yaml
```

`llm_config.yaml` is gitignored so developers can edit provider models for their own
machine without committing local configuration.

### Tool Calling

Tool calling needs **no configuration and adds no environment variables**. It is a
per-call capability of any chat alias rather than a flavor, so there is no `tools`
alias to configure and the six-flavor contract is unchanged. Pick a flavor for the
cost and capability you want, then pass tools to that call:

```python
from prometheus_api.llm_client import (
    LLMClient,
    ToolDefinition,
    assistant_message,
    tool_result_message,
)

lookup = ToolDefinition.from_pydantic("lookup_material", LookupArgs, description="Look up a material")

with LLMClient() as llm:
    response = llm.medium("What is the density of iron?", tools=[lookup], tool_choice="auto")

    for call in response.tool_calls:
        print(call.name, call.arguments)
```

A turn that only requests tools has no message content, so `response.text` is `""`.
Use `response.tool_calls` as the signal; `response.finish_reason` is for observability only.
To continue the conversation, replay the turn and answer each call:

```python
    history = [
        {"role": "user", "content": "What is the density of iron?"},
        assistant_message(response),
        *(tool_result_message(call, run_tool(call)) for call in response.tool_calls),
    ]
    final = llm.medium(history, tools=[lookup])
```

When MLflow tracing is enabled, spans record supplied tool **names** (not full JSON
schemas) as inputs, and tool calls as outputs with their arguments passed through
`redact_secrets(...)`. Tool-call arguments are model-authored, so debug logs withhold
them unless `LLM_DEBUG_LOG_MESSAGES=true`, and redact them even then.

Streaming is not supported. Passing `stream=True` raises `LLMClientError` before any
backend is contacted.

### Custom LiteLLM YAML

The repository includes a fully commented local development template at
`llm_config.example.yaml`. The minimal shape is:

```yaml
model_list:
  - model_name: default
    litellm_params:
      model: openai/gpt-5-mini
      api_key: os.environ/LLM_API_KEY
      # Optional: override the direct provider endpoint
      # api_base: http://localhost:8000/v1

  - model_name: small
    litellm_params:
      model: openai/gpt-5-mini
      api_key: os.environ/LLM_API_KEY
      # api_base: http://localhost:8000/v1

  - model_name: large
    litellm_params:
      model: anthropic/claude-sonnet-4-5-20250929
      api_key: os.environ/LLM_API_KEY
      # api_base: https://api.anthropic.com

  - model_name: embedding
    litellm_params:
      model: openai/text-embedding-3-large
      api_key: os.environ/LLM_API_KEY
      # api_base: http://localhost:8000/v1
```

`api_base` is optional and applies to direct provider SDK calls made from the
selected configuration. A configuration may instead contain a top-level
`proxy_url`; `os.environ/NAME` references are resolved in both locations.

### LLMClient Usage

```python
from prometheus_api.llm_client import LLMClient

llm = LLMClient()
response = llm("Summarize this result.")
print(response.text)

large_response = llm.large([
    {"role": "system", "content": "You are an engineering analyst."},
    {"role": "user", "content": "Find possible failure modes in this trend."},
])

embedding_response = llm.embedding("bearing temperature rising")
vector = embedding_response.embeddings[0]
```

Agents create clients with `self.llm_client(context)`:

```python
from prometheus_api.agent import PrometheusAgent

class AnalysisAgent(PrometheusAgent):
    async def _execute(self, params, context, event_queue):
        async with self.llm_client(context) as llm:
            response = await llm.medium(params["query"])
        return {"status": "completed", "answer": response.text}
```

Credentials come from the selected profile and environment only; nothing in an A2A request
can supply or override an LLM key.

See `examples/llm_client_usage.py` for sync chat and embedding usage, and
`examples/llm_agent_usage.py` for A2A agent usage with `AsyncLLMClient`.

---

## StorageClient Configuration

Environment variables for `StorageClient`:

### Authentication (choose one method)

**Option 1: API Key/Secret (Recommended)**
```bash
DEEPLYNX_KEY=your-api-key
DEEPLYNX_SECRET=your-api-secret
```

**Option 2: JWT Token**
```bash
DEEPLYNX_JWT_TOKEN=your-jwt-token
```

### Organization & Project

```bash
DEEPLYNX_ORG_ID=123          # Your organization ID (integer)
DEEPLYNX_PROJECT_ID=456      # Your project ID (integer)
```

### Optional Settings

```bash
# Custom API endpoint (defaults to INL DeepLynx)
DEEPLYNX_BASE_URL=https://deeplynx.inl.gov/api/v1

# Connection settings
DEEPLYNX_TIMEOUT=30.0        # Request timeout in seconds
DEEPLYNX_MAX_RETRIES=3       # Number of retry attempts
DEEPLYNX_VERIFY_SSL=true     # SSL certificate verification
```

### Example StorageClient .env

```bash
# Authentication
DEEPLYNX_KEY=your-api-key
DEEPLYNX_SECRET=your-api-secret

# Organization & Project
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456

# Optional
DEEPLYNX_BASE_URL=https://deeplynx.inl.gov/api/v1
DEEPLYNX_TIMEOUT=30.0
```

### StorageClient Usage

```python
from prometheus_api.storage_client import ConnectionConfig, StorageClient

# Load from .env file
config = ConnectionConfig.from_env()

with StorageClient(config) as client:
    items = client.items.list()
```

---

## Combined Configuration

If using both StorageClient and PrometheusAgent, combine variables in one `.env`:

```bash
# ===== Agent Configuration =====
AGENT_PORT=8000
# EXTERNAL_AGENT_URL=http://my-host:9002  # only needed for port-mapped / cross-host deployments
AGENT_SECRET=your-shared-secret-here
AGENT_SECRET_REQUIRED=true
REGISTRY_URL=http://litellm:4000

# ===== LLMClient Configuration =====
# The default profile reads REGISTRY_URL for chat, vision, and embedding calls.
LLM_CONFIG_PROFILE=registry
# LLM_CONFIG_FILE=./llm_config.yaml  # overrides the installed profile
LLM_DEBUG_LOG_MESSAGES=false
ENABLE_MLFLOW_TRACING=false
# MLFLOW_TRACKING_URI=https://mlflow.example.org
# MLFLOW_EXPERIMENT_NAME=prometheus-llm
# MLFLOW_API_KEY=your-mlflow-api-key  # sent as X-Api-Key (e.g. AMSC MLflow)

# ===== StorageClient Configuration =====
DEEPLYNX_KEY=your-api-key
DEEPLYNX_SECRET=your-api-secret
DEEPLYNX_ORG_ID=123
DEEPLYNX_PROJECT_ID=456
DEEPLYNX_BASE_URL=https://deeplynx.inl.gov/api/v1
```

### Combined Usage

```python
from prometheus_api.agent import PrometheusAgent
from prometheus_api.storage_client import StorageClient, ConnectionConfig

class StorageAgent(PrometheusAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # StorageClient reads DEEPLYNX_* vars
        self.storage = StorageClient(ConnectionConfig.from_env())

    async def _execute(self, params, context, event_queue):
        item = self.storage.items.get(params["item_id"])
        return {
            "conversation_id": context.context_id,
            "status": "completed",
            "message": f"Loaded {item.name}.",
            "item": item.name,
        }

if __name__ == "__main__":
    # PrometheusAgent reads AGENT_* vars
    agent = StorageAgent(agent_name="Storage Agent")
    agent.run()
```

---

## Usage Patterns

### Load from Default .env File

```python
from prometheus_api.storage_client import ConnectionConfig

# Loads from .env in current directory
config = ConnectionConfig.from_env()
```

### Load from Specific File

```python
from pathlib import Path

# Load from a specific location
config = ConnectionConfig.from_env(
    env_file=Path("/path/to/production.env")
)
```

### Override Specific Values

```python
# Load from .env but override org/project
config = ConnectionConfig.from_env(
    organization_id=999,  # Override env var
    project_id=888,       # Override env var
    timeout=60.0          # Custom timeout
)
```

### Multiple Environments

**Development (.env.dev):**
```bash
DEEPLYNX_KEY=dev-key
DEEPLYNX_SECRET=dev-secret
DEEPLYNX_ORG_ID=100
DEEPLYNX_PROJECT_ID=200
DEEPLYNX_BASE_URL=https://dev.deeplynx.com/api/v1
```

**Production (.env.prod):**
```bash
DEEPLYNX_KEY=prod-key
DEEPLYNX_SECRET=prod-secret
DEEPLYNX_ORG_ID=500
DEEPLYNX_PROJECT_ID=600
DEEPLYNX_BASE_URL=https://deeplynx.inl.gov/api/v1
```

**Load based on environment:**
```python
import os
from pathlib import Path

env = os.getenv("APP_ENV", "dev")
env_file = Path(f".env.{env}")

config = ConnectionConfig.from_env(env_file=env_file)
```

---

## Security Best Practices

### DO

1. **Use `.env` files for local development**
```bash
# .env is gitignored by default
cp .env.example .env
# Edit with your credentials
```

2. **Use environment variables in production**
```bash
# Set in your deployment system
export DEEPLYNX_KEY=prod-key
export AGENT_SECRET=prod-secret
```

3. **Keep `.env.example` updated**
```bash
# Template without actual credentials
DEEPLYNX_KEY=your-api-key-here
AGENT_SECRET=your-secret-here
```

4. **Use different credentials per environment**

### DON'T

1. **Never commit `.env` files**
   - Already in `.gitignore`
   - Contains real credentials

2. **Don't hardcode credentials in code**
```python
# BAD
config = ConnectionConfig(api_key="actual-key-in-code")

# GOOD
config = ConnectionConfig.from_env()
```

3. **Don't share `.env` files**
   - Each developer should have their own
   - Use a secrets manager for teams

---

## Troubleshooting

### Error: "organization_id must be provided"

Make sure your `.env` file has:
```bash
DEEPLYNX_ORG_ID=123
```

### Error: "Must provide either jwt_token or both api_key and api_secret"

Add authentication credentials to `.env`:
```bash
DEEPLYNX_KEY=your-key
DEEPLYNX_SECRET=your-secret
```

### .env File Not Loading

1. Check file location: `ls -la .env`
2. Check file contents: `cat .env`
3. Try explicit path:
```python
config = ConnectionConfig.from_env(env_file=Path(".env"))
```

### Environment Variables Not Found

Check if they're set:
```bash
printenv | grep DEEPLYNX
printenv | grep AGENT
```

---

## Docker Integration

### Dockerfile
```dockerfile
FROM python:3.12

WORKDIR /app

RUN python -m pip install --upgrade pip uv

COPY . .
RUN uv pip install --system .

# Don't copy .env - use environment variables
CMD ["python", "agent.py"]
```

### docker-compose.yml
```yaml
version: '3.8'

services:
  agent:
    build: .
    environment:
      # Agent
      - AGENT_PORT=8000
      - AGENT_SECRET=${AGENT_SECRET}
      # StorageClient
      - DEEPLYNX_KEY=${DEEPLYNX_KEY}
      - DEEPLYNX_SECRET=${DEEPLYNX_SECRET}
      - DEEPLYNX_ORG_ID=123
      - DEEPLYNX_PROJECT_ID=456
    env_file:
      - .env  # Can also load from file
```

### Run with environment variables
```bash
docker run \
  -e AGENT_SECRET=your-secret \
  -e DEEPLYNX_KEY=your-key \
  -e DEEPLYNX_SECRET=your-secret \
  -e DEEPLYNX_ORG_ID=123 \
  -e DEEPLYNX_PROJECT_ID=456 \
  your-image
```

---

## CI/CD Integration

### GitHub Actions
```yaml
name: Tests

on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        run: python -m pip install uv

      - name: Install dependencies
        run: uv sync

      - name: Run unit tests
        run: make test

      - name: Run integration tests
        env:
          DEEPLYNX_KEY: ${{ secrets.DEEPLYNX_KEY }}
          DEEPLYNX_SECRET: ${{ secrets.DEEPLYNX_SECRET }}
          DEEPLYNX_ORG_ID: 123
          DEEPLYNX_PROJECT_ID: 456
          AGENT_SECRET: ${{ secrets.AGENT_SECRET }}
        run: make test-integration
```

---

## Summary

| Component | Prefix | Key Variables |
|-----------|--------|---------------|
| PrometheusAgent | `AGENT_` | `AGENT_PORT`, `EXTERNAL_AGENT_URL`, `AGENT_SECRET` |
| StorageClient | `DEEPLYNX_` | `DEEPLYNX_KEY`, `DEEPLYNX_SECRET`, `DEEPLYNX_ORG_ID` |

Quick start:
```bash
cp .env.example .env  # Copy template
vim .env              # Add credentials
python your_script.py # Use it!
```
