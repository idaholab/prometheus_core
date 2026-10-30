---
title: Agent Template
description: Description of page
icon: lucide/book-open
---

# Prometheus Agent Template

An interactive scaffolding tool that generates a ready-to-run A2A agent from a template. Run the setup script, answer a few prompts, and get a complete agent with Dockerfile, configuration, and authentication.

## Quick start

```bash
cd prometheus_core/agent-template

# Run the scaffolding script
python setup_agent.py
```

The script prompts for:

| Prompt | Example | Default |
|--------|---------|---------|
| Agent name | Plant Analysis | (required) |
| Description | Analyzes plant thermal output | -- |
| Slug | plant-analysis | derived from name |
| Class name | PlantAnalysis | derived from name |
| Skill ID | analyze_plant | derived from name |
| Skill name | Analyze Plant | derived from name |
| Skill description | Runs plant thermal analysis | -- |
| Trim comments? | y/n | n |

After confirmation, it creates a new directory with all files ready to go.

### Run the generated agent

=== "pip"

    ```bash
    cd <output-directory>
    cp .env.example .env          # edit with your settings
    pip install -r requirements.txt
    python agent.py
    ```

=== "uv"

    ```bash
    cd ../<output-directory> && uv run agent.py
    ```

=== "Docker

    ```bash
    docker build -t my-agent .
    docker run -p 8000:8000 --env-file .env my-agent
    ```

## Generated files

The template produces these files:

| File | Purpose |
|------|---------|
| `agent.py` | Agent implementation -- subclass of `PrometheusAgent` with `process_analysis()` to customize |
| `agent_card.json` | A2A agent metadata (name, description, skills, capabilities) |
| `workflows/` | Optional agent-owned workflow templates published through the served agent card |
| `.env.example` | Environment variable template |
| `Dockerfile` | Container config with health check and proxy support |
| `requirements.txt` | Python dependencies (`a2a-sdk`, `pydantic`, `httpx`, `uvicorn`, `prometheus-api[agent]`) |
| `pyproject.toml` | Package metadata |
| `README.md` | Agent-specific documentation |
| `.python-version` | Pinned to 3.12 |

## Template placeholders

The setup script replaces these tokens across all files:

| Placeholder | Replaced with |
|-------------|---------------|
| `TEMPLATE_NAME` | Agent name |
| `TEMPLATE_DESCRIPTION` | Agent description |
| `TEMPLATE_SLUG` | Kebab-case identifier |
| `TEMPLATE_CLASS` | PascalCase class name |
| `TEMPLATE_SKILL_ID` | Snake-case skill ID |
| `TEMPLATE_SKILL_NAME` | Skill display name |
| `TEMPLATE_SKILL_DESCRIPTION` | Skill description |

## Customizing the agent

### Override `process_analysis`

The only method you need to implement:

```python
from prometheus_api.agent import PrometheusAgent

class MyAgent(PrometheusAgent):
    async def process_analysis(self, params, context, event_queue):
        input_data = params.get("input_data")
        if not input_data:
            raise ValueError("input_data is required")

        # Your logic here
        result = do_analysis(input_data)

        return {"status": "success", "result": result}
```

### Send progress updates

For long-running tasks:

```python
from prometheus_api.agent import (
    TaskState, TaskStatus, TaskStatusUpdateEvent,
)

async def process_analysis(self, params, context, event_queue):
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            taskId=context.task_id,
            contextId=context.context_id,
            final=False,
            status=TaskStatus(state=TaskState.working),
        )
    )
    # ... continue processing
```

### Add skills

Edit `agent_card.json` to register additional skills:

```json
{
  "skills": [
    {
      "id": "primary_analysis",
      "name": "Primary Analysis",
      "description": "Main analysis skill",
      "tags": ["analysis"]
    },
    {
      "id": "secondary_check",
      "name": "Secondary Check",
      "description": "Validation step",
      "tags": ["validation"]
    }
  ]
}
```

### Add workflow templates

Use `workflows/` when this agent should publish reusable workflow templates to the platform workflow library.
`PrometheusAgent` loads `*.yaml`, `*.yml`, and `*.json` workflow files from that directory and inserts them into
the served agent card. The client-agent discovers those definitions, compiles them against available skill schemas,
and exposes them in the shared workflow catalog.

The generated template ships `workflows/example_workflow.yaml.example` so a new agent does not publish a sample
workflow by accident. Rename it to `.yaml` only after reviewing the workflow ID, inputs, step bindings, and output
mapping. See [Workflow Templates](workflow-templates.md) for the complete schema and authoring rules.

### Use the StorageClient

Agents can interact with the storage backend:

```python
from prometheus_api.storage_client import StorageClient, ConnectionConfig, ItemCreate

class MyAgent(PrometheusAgent):
    def __init__(self):
        super().__init__("My Agent")
        self.storage_config = ConnectionConfig.from_env()

    async def process_analysis(self, params, context, event_queue):
        with StorageClient(self.storage_config) as client:
            item = client.items.create(ItemCreate(
                name="Analysis Result",
                properties=params
            ))
        return {"item_id": item.id}
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_PORT` | No | 8000 | Port to listen on |
| `AGENT_HOST` | No | localhost | Hostname for agent card URL |
| `AGENT_SECRET` | Prod | -- | Shared secret for Bearer token auth |
| `AGENT_SECRET_REQUIRED` | No | true | Enforce authentication. Do not disable this in normal development or deployment. |
| `REGISTRY_URL` | No | -- | Agent registry base URL used for registration and A2A routing (on the platform, the backend: `http://backend:8000`) |
| `LITELLM_MASTER_KEY` | No | -- | Registry token the SDK sends when registering (name kept for SDK compatibility); on the platform, set it to `AGENT_SECRET` |
| `DEEPLYNX_KEY` | If using storage | -- | API key for DeepLynx |
| `DEEPLYNX_SECRET` | If using storage | -- | API secret for DeepLynx |
| `DEEPLYNX_ORG_ID` | If using storage | -- | Organization ID |
| `DEEPLYNX_PROJECT_ID` | If using storage | -- | Project ID |

See `.env.example` for the full list including proxy settings.

## Docker deployment

The generated Dockerfile:

- Base image: `python:3.11-slim`
- Supports `HTTP_PROXY` / `HTTPS_PROXY` build args
- Health check on `/healthz` endpoint every 30 seconds

### Docker Compose (multi-agent)

```yaml
services:
  agent-one:
    build: ./agent-one
    ports:
      - "8300:8000"
    env_file: ./agent-one/.env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]
      interval: 30s
      retries: 3

  agent-two:
    build: ./agent-two
    ports:
      - "8301:8000"
    env_file: ./agent-two/.env
```

## Agent endpoints

Every generated agent exposes:

| Path | Auth | Description |
|------|------|-------------|
| `GET /healthz` | No | Health check |
| `GET /.well-known/agent.json` | No | Agent card (A2A discovery) |
| `POST /message` | Yes | A2A JSON-RPC 2.0 message endpoint |

## A2A protocol

Agents communicate using JSON-RPC 2.0 with the `message/send` method:

If you test this request against a Dockerized target agent on localhost, run that
agent in external network mode; see the [agent template run instructions](https://github.com/idaholab/prometheus_core/blob/devel/agent-template/README.md#run-it).

**Request:**

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "req-1",
  "params": {
    "message": {
      "messageId": "msg-1",
      "role": "user",
      "parts": [{"text": "{\"input_data\": \"value\"}"}]
    }
  }
}
```

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "history": [
      {
        "role": "agent",
        "parts": [{"text": "{\"status\": \"success\"}"}]
      }
    ]
  }
}
```

## Development commands

From the `agent-template/` directory:

```bash
make lint       # Ruff linter
make format     # Ruff formatter check
make typecheck  # mypy on setup_agent.py
make fix        # Auto-fix lint + format
make check      # All checks
make test       # Run pytest
```
