# Adding agents

This guide covers how to create a new specialist agent, register it with the backend's agent registry, and wire it into Docker Compose.

## Creating a new agent

### 1. Subclass PrometheusAgent

Every agent extends the `PrometheusAgent` base class from `prometheus_api`:

```python
# agent.py
from prometheus_api.agent import PrometheusAgent

class MyAnalysisAgent(PrometheusAgent):
    async def process_analysis(self, params, context, event_queue):
        """Main entry point for agent logic.

        Args:
            params: Dict extracted from the A2A request message
            context: RequestContext with task_id, context_id, etc.
            event_queue: EventQueue for status updates and artifacts

        Returns:
            Dict with analysis results (auto-wrapped as JSON artifact)
        """
        material_id = params.get("material_id")
        temperature = params.get("temperature")

        # Send progress update
        await self.send_status_update(
            context, event_queue,
            state="working",
            message=f"Analyzing {material_id} at {temperature}C...",
            final=False,
        )

        # Your analysis logic
        result = run_analysis(material_id, temperature)

        return {"status": "success", "analysis": result}
```

The base class handles:
- HTTP server setup with Bearer token auth
- Agent card loading and serving at `/.well-known/agent.json`
- Agent registration with the registry at `REGISTRY_URL` on startup
- A2A JSON-RPC message parsing
- Task lifecycle (working/completed/failed status)
- Automatic JSON artifact emission for the return value

### 2. Create agent_card.json

The agent card defines the agent's identity, skills, and capabilities:

```json
{
  "name": "My Analysis Agent",
  "description": "Performs custom analysis for nuclear materials",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "skills": [
    {
      "id": "analyze_custom",
      "name": "Custom Analysis",
      "description": "Runs custom analysis on a given material under specified conditions",
      "tags": ["analysis", "materials"],
      "inputSchema": {
        "type": "object",
        "properties": {
          "material_id": {
            "type": "string",
            "description": "Material identifier (e.g., SS316, Inconel625)"
          },
          "temperature": {
            "type": "number",
            "description": "Temperature in Celsius"
          },
          "duration_hours": {
            "type": "number",
            "description": "Exposure duration in hours"
          }
        },
        "required": ["material_id", "temperature"]
      },
      "expected_duration_seconds": 30,
      "requires_approval": false
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "authentication": {
    "schemes": ["bearer"]
  }
}
```

Key fields for discovery and routing:
- `skills[].id`: Used by the client-agent to invoke specific skills via `skillId` in A2A context
- `skills[].inputSchema`: The client-agent uses this to determine what parameters to collect from the user
- `skills[].tags`: Used by the client-agent when matching capabilities to a request
- `skills[].requires_approval`: If `true`, the client-agent asks the user before invoking

Do **not** put a `url` field in the card. `PrometheusAgent` sets the registered
URL at startup: `EXTERNAL_AGENT_URL` if set, else
`http://{container hostname}:{AGENT_PORT}`. Always set `EXTERNAL_AGENT_URL` to
`http://<service-name>:8000` in the agent's `docker-compose.yml`. The hostname
fallback only works under Docker Compose, where the hostname happens to be the
service name; on Kubernetes the hostname is the pod name, which other pods can't
resolve and which changes on every restart. `make test-static` fails if an agent
doesn't set it.

### LangGraph agents (prototype)

`LangGraphPrometheusAgent` from `prometheus_api.langgraph` is an opt-in subclass of
`PrometheusAgent`. It runs each card skill as a LangGraph graph (`langchain.agents.create_agent`).
The base image already contains `langchain`, `langgraph` and the Postgres checkpointer. Agents
that subclass `PrometheusAgent` need no change. The reference port is
`agents/debug-agents/artifact-debug-agent/agent.py`.

To write a LangGraph agent:

1. Subclass `LangGraphPrometheusAgent` instead of `PrometheusAgent`.
2. Override `skill_tools()` to map each card skill `id` to the tools of its graph.
3. Set `model_alias` to a semantic LLM alias, for example `"small"`. The default is `"default"`.
4. Optionally override `system_prompt(skill_id)` to give each graph its system prompt.
5. Optionally set `approval_tools` to the names of more tools that need user approval.
6. In each tool, add the parameter `runtime: ToolRuntime[PrometheusContext]`.
7. Call `save_artifact(runtime, filename, data, mime_type)` to save output to DeepLynx.
8. Call `load_artifact(runtime, item_id)` to read a DeepLynx item back.

```python
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from prometheus_api.langgraph import LangGraphPrometheusAgent, PrometheusContext, save_artifact


@tool
async def create_report(title: str, runtime: ToolRuntime[PrometheusContext]) -> dict:
    """Save a text report as a DeepLynx artifact."""
    saved = await save_artifact(runtime, "report.txt", title.encode(), "text/plain")
    return {"status": "success", "uri": saved.uri, "version": saved.version}


class ReportAgent(LangGraphPrometheusAgent):
    model_alias = "small"

    def skill_tools(self) -> dict[str, list[BaseTool]]:
        return {"create_report": [create_report]}
```

The agent behaves as follows:

- **Skill check**: The agent does not start when a card skill has no tools, or when a tool list
  has no card skill. `load_agent_card()` raises `ValueError`.
- **Threads**: The A2A task ID is the checkpoint `thread_id`. A later request of the same task
  continues the same graph.
- **Approval**: A tool of a skill with `"requires_approval": true`, or a tool in `approval_tools`,
  pauses before it runs. The task goes to `INPUT_REQUIRED` and asks for the boolean `approved`.
  The tool runs only when `approved` is `true`.
- **Artifacts**: Each `save_artifact` call makes one new DeepLynx item and sends its
  `deeplynx://` reference. A repeated save in the same tool call uses the key
  `thread_id:tool_call_id:filename` and returns the first item. It does not make a second item.
- **Provenance**: `ProvenanceMiddleware` adds `generated` and `input_to` relations to the execution
  record of the task, and closes the record when the graph ends.
- **Model**: `PrometheusChatModel` sends the semantic alias through `AsyncLLMClient`. It is async
  only.
- **Summaries**: Long conversations are summarized with the `small` alias.

Set these variables in the agent's `docker-compose.yml`:

| Variable | Default | Description |
|---|---|---|
| `LANGGRAPH_CHECKPOINT_DB_URL` | empty | psycopg Postgres URL of the checkpoint store. When it is empty, checkpoints stay in memory, a task cannot resume after a restart, and the agent logs one warning. |
| `LANGGRAPH_SUMMARY_TRIGGER_TOKENS` | `24000` | Token count that starts a summary. |
| `LANGGRAPH_SUMMARY_KEEP_MESSAGES` | `20` | Number of recent messages that a summary keeps. |

The checkpoint store is the `langgraph` schema in `admin-db`. Set `LANGGRAPH_DB_PASSWORD` in the
platform `.env`. A backend migration uses it to create the `langgraph` role and schema.

In the agent's `docker-compose.yml`, point `LANGGRAPH_CHECKPOINT_DB_URL` at that schema.

Then add `admin-db` to the agent's `depends_on`:

```yaml
environment:
  LANGGRAPH_CHECKPOINT_DB_URL: ${LANGGRAPH_CHECKPOINT_DB_URL:-postgresql://langgraph:${LANGGRAPH_DB_PASSWORD}@admin-db:5432/admin?options=-csearch_path%3Dlanggraph}
depends_on:
  admin-db:
    condition: service_healthy
```

Use a plain `postgresql://` URL. Do not use `postgresql+asyncpg://`.

### 3. Create environment and dependencies

**.env.example:**
```bash
AGENT_PORT=8000
AGENT_HOST=localhost
AGENT_SECRET=your-shared-secret
AGENT_SECRET_REQUIRED=true
REGISTRY_URL=http://localhost:8600
# The SDK reads its registry token from this name; set it to AGENT_SECRET.
LITELLM_MASTER_KEY=your-shared-secret
LLM_CONFIG_PROFILE=openai
LLM_CONFIG_FILE=
LLM_API_KEY=your-openai-key
REDIS_URL=redis://localhost:6379
```

Use `anthropic`, `openai`, `inl_hpc`, `inl_litellm`, `amsc`, `anl_asksage`,
`genesis`, or `ollama` for `LLM_CONFIG_PROFILE` (it is required; there is no
default, and the SDK's `registry` profile is not supported on this platform
because there is no LLM proxy). Every profile reads its provider key from
`LLM_API_KEY`. If `LLM_CONFIG_FILE` is set, its path must exist
inside the agent container and it overrides the installed profile. Export the
provider keys referenced by the selected configuration.

**requirements.txt:**
```
prometheus-api[agent]
pydantic>=2.0
httpx
uvicorn
```

### 4. Run the agent

```bash
# Local
uv run agent.py

# Docker
docker build -t my-analysis-agent .
docker run -p 8000:8000 --env-file .env my-analysis-agent
```

The agent starts a uvicorn server and registers with the backend's agent registry (if `REGISTRY_URL` is set).
Keep `AGENT_SECRET_REQUIRED=true` for local runs as well.

### 5. Add to Docker Compose

Add a service block to `docker-compose.yml`:

```yaml
my-analysis-agent:
  build:
    context: ./agents/my-analysis-agent
    additional_contexts:
      prometheus_api: ./prometheus_api
  container_name: my-analysis-agent
  ports:
    - "8010:8000"
  networks:
    - agent-network
  environment:
    - AGENT_HOST=my-analysis-agent
    - AGENT_PORT=8000
    - EXTERNAL_AGENT_URL=http://my-analysis-agent:8000
    - REGISTRY_URL=${REGISTRY_URL:-http://backend:8000}
    # The SDK sends this as its registry token; the backend registry checks AGENT_SECRET.
    - LITELLM_MASTER_KEY=${AGENT_SECRET}
    - REDIS_URL=${REDIS_URL}
    - LLM_CONFIG_PROFILE=${LLM_CONFIG_PROFILE:?set LLM_CONFIG_PROFILE in .env}
    - LLM_CONFIG_FILE=${LLM_CONFIG_FILE:-}
    - LLM_API_KEY=${LLM_API_KEY:-}
    - EMBEDDING_API_KEY=${EMBEDDING_API_KEY:-}
    - AGENT_SECRET=${AGENT_SECRET}
    - AGENT_SECRET_REQUIRED=true
  depends_on:
    backend:
      condition: service_healthy
  volumes:
    - ./shared:/app/shared
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]
    interval: 15s
    timeout: 10s
    retries: 5
    start_period: 20s
  restart: unless-stopped
```

The `healthcheck` is required. `make test-static` fails without it in any per-agent `agents/<name>/docker-compose.yml`, and `make up` waits on it to know that the agent is serving. It probes the base class's unauthenticated health endpoint on the container port with Python, since the image has no `curl`. It does not show that registration with the backend succeeded; `make up` then runs `make check`, which does.

Once the container starts, it registers with the backend (`POST /v1/agents`). The client-agent discovers it automatically through the backend's agent registry, calls it through the backend's A2A gateway (`/a2a/{agent_name}`), and loads the full agent card from the specialist's well-known endpoint when needed.
The agent selects semantic model flavors such as `medium` in code; its selected
YAML maps those flavors to provider model IDs.

## Workflow templates

For multi-step workflows that chain agents in a defined sequence, use the workflow library.
See [Workflow Templates](../workflow-templates.md) for the complete schema, platform-owned and agent-owned
publication paths, binding rules, and compiler behavior.
Platform-owned workflows can still live in `agents/client-agent/workflows/*.yaml`:

```yaml
# workflows/my_workflow.yml
id: material_assessment
name: Material Assessment
version: "1.0.0"
description: Full material assessment workflow
matching:
  patterns:
    - "material assessment for {material_id}"
inputs:
  required:
    - material_id
    - context.temperature_c
execution:
  mode: sequential
  on_error: fail_fast

steps:
  - id: data_retrieval
    skill_id: retrieve_material_data
    params:
      material_id:
        from: input.material_id

  - id: corrosion_check
    skill_id: analyze_corrosion
    depends_on: [data_retrieval]
    params:
      material_id:
        from: input.material_id
      material_data:
        from: step.data_retrieval.result
      context:
        temperature_c:
          from: input.context.temperature_c

  - id: synthesis
    skill_id: synthesize_results
    depends_on: [corrosion_check]
    params:
      analyses:
        from: step.corrosion_check.result
```

Workflow files are loaded by the client-agent's workflow library module. Parameters use `from: input.*`
for user-provided values and `from: step.<id>.*` for outputs from previous steps.

Agents can also contribute workflow templates directly from their `agent_card.json` by adding a top-level
`workflows` array. The client-agent reads these cards during discovery, compiles the definitions against
the discovered skill schemas, and merges them into the same workflow catalog:

```json
{
  "name": "Thermal Agent",
  "skills": [
    {
      "id": "analyze_thermal",
      "name": "Analyze Thermal",
      "description": "Run thermal analysis."
    }
  ],
  "workflows": [
    {
      "id": "thermal_agent.quick_check",
      "name": "Quick Thermal Check",
      "version": "1.0.0",
      "description": "Run a quick thermal analysis.",
      "matching": {"patterns": ["quick thermal check"]},
      "execution": {"mode": "sequential", "on_error": "fail_fast"},
      "steps": [
        {"id": "analyze", "skill_id": "analyze_thermal"}
      ],
      "ui": {
        "category": "Thermal",
        "display_name": "Quick Thermal Check",
        "summary": "Quick thermal analysis"
      }
    }
  ]
}
```

Workflow IDs are global. Prefer an agent-scoped prefix such as `thermal_agent.quick_check`.
If a platform-local YAML workflow and an agent-provided workflow use the same `id:version`, the local
workflow wins and the duplicate is reported in the workflow refresh errors.
Before an agent-provided workflow starts, the client-agent calls the contributing agent's direct
`/healthz` endpoint. If the contributing agent has been disconnected or scaled down, the workflow start is
rejected instead of executing a stale catalog entry.

## Agent endpoints

Every PrometheusAgent exposes:

| Path | Auth | Description |
|------|------|-------------|
| `GET /healthz` | No | Health check |
| `GET /.well-known/agent.json` | No | Agent card (A2A discovery) |
| `POST /` | Yes | A2A JSON-RPC 2.0 message endpoint |

## Sending artifacts from agents

See [artifacts.md](artifacts.md) for details on returning structured artifacts from `process_analysis()`.
