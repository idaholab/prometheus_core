# Adding agents

This guide covers how to create a new specialist agent, register it with LiteLLM, and wire it into Docker Compose.

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
- LiteLLM agent registration on startup
- A2A JSON-RPC message parsing
- Task lifecycle (working/completed/failed status)
- Automatic JSON artifact emission for the return value

### 2. Create agent_card.json

The agent card defines the agent's identity, skills, and capabilities:

```json
{
  "name": "My Analysis Agent",
  "description": "Performs custom analysis for nuclear materials",
  "url": "http://localhost:8000",
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

### 3. Create environment and dependencies

**.env.example:**
```bash
AGENT_PORT=8000
AGENT_HOST=localhost
AGENT_SECRET=your-shared-secret
AGENT_SECRET_REQUIRED=true
LITELLM_URL=http://localhost:4000
LITELLM_MASTER_KEY=your-litellm-master-key
ANTHROPIC_API_KEY=your-api-key
MODEL_NAME=claude-sonnet-4-20250514
REDIS_URL=redis://localhost:6379
```

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

The agent starts a uvicorn server and registers with LiteLLM (if `LITELLM_URL` is set).
Keep `AGENT_SECRET_REQUIRED=true` for local runs as well.

Custom CA certificates should be placed in the repo-local [`certs`](/Users/schwd/Programs/prometheus/prometheus_platform/certs) directory as `*.pem` files only. The Docker build context for certificates is intentionally limited to that directory.

### 5. Add to Docker Compose

Add a service block to `docker-compose.yml`:

```yaml
my-analysis-agent:
  build:
    context: ./agents/my-analysis-agent
    additional_contexts:
      prometheus_api: ./prometheus_api
      certs: ./certs
  container_name: my-analysis-agent
  ports:
    - "8010:8000"
  networks:
    - agent-network
  environment:
    - AGENT_HOST=my-analysis-agent
    - AGENT_PORT=8000
    - LITELLM_URL=http://litellm:4000
    - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}
    - REDIS_URL=${REDIS_URL}
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    - MODEL_NAME=${MODEL_NAME:-claude-sonnet-4-20250514}
    - AGENT_SECRET=${AGENT_SECRET}
    - AGENT_SECRET_REQUIRED=true
  depends_on:
    litellm:
      condition: service_healthy
  volumes:
    - ./shared:/app/shared
  restart: unless-stopped
```

Once the container starts, it registers with LiteLLM. The client-agent discovers it automatically through LiteLLM's agent directory and loads the full agent card from the specialist's well-known endpoint when needed.

## Workflow YAML files

For multi-step workflows that chain agents in a defined sequence, use the workflow library:

```yaml
# workflows/my_workflow.yml
name: Material Assessment
description: Full material assessment workflow
version: "1.0"

steps:
  - id: data_retrieval
    agent_skill: retrieve_material_data
    description: Get material properties
    params:
      material_id: "${input.material_id}"

  - id: corrosion_check
    agent_skill: analyze_corrosion
    description: Run corrosion analysis
    depends_on: [data_retrieval]
    params:
      material_id: "${input.material_id}"
      material_data: "${steps.data_retrieval.result}"
      temperature: "${input.temperature}"

  - id: synthesis
    agent_skill: synthesize_results
    description: Combine findings
    depends_on: [corrosion_check]
    params:
      analyses: "${steps.corrosion_check.result}"
```

Workflow files are loaded by the client-agent's workflow library module. Parameters use `${input.*}` for user-provided values and `${steps.<id>.result}` for outputs from previous steps.

## Agent endpoints

Every PrometheusAgent exposes:

| Path | Auth | Description |
|------|------|-------------|
| `GET /health` | No | Health check |
| `GET /.well-known/agent.json` | No | Agent card (A2A discovery) |
| `POST /` | Yes | A2A JSON-RPC 2.0 message endpoint |

## Sending artifacts from agents

See [artifacts.md](artifacts.md) for details on returning structured artifacts from `process_analysis()`.
