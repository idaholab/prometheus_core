# Migration guide

This document explains what changed when `multi_agent_testbed` and `prometheus_platform` were merged into the combined Prometheus platform, and why.

## Summary of changes

The merge replaced the old FastAPI backend in `prometheus_platform` with the multi-agent orchestration system from `multi_agent_testbed`. The Chainlit frontend now communicates directly with the client-agent via the A2A JSON-RPC protocol, eliminating the backend as a middleman.

### What was removed

| Component | Location | Reason |
|-----------|----------|--------|
| FastAPI backend | `prometheus_platform/backend/` | Replaced by client-agent orchestrator |
| `/api/chat` endpoint | `backend/routers/chat.py` | Replaced by A2A `message/send` to client-agent |
| `/api/demo/workflow/run` SSE stream | `backend/routers/demo_workflow.py` | Replaced by A2A status updates and ConversationResponse lifecycle |
| `/api/demo/ifc`, `/api/demo/exodus` | `backend/routers/demo.py` | Replaced by artifact registry in PrometheusAgent |
| Hardcoded Bearer token | `message_handler.py:104` | Replaced by configurable `AGENT_SECRET` env var |
| `platform-url` config key | `frontend/config.yml` | Replaced by `agent-url` pointing to client-agent |
| `requests.post()` to backend | `message_handler.py` | Replaced by `A2AClient.send()` using httpx |
| Backend orchestrator module | `backend/orchestrator/` | Logic moved to client-agent's LangGraph workflow |
| Backend models | `backend/models/` | Replaced by `ConversationRequest` / `ConversationResponse` in client-agent |

The `backend/` directory has been deleted.

### What was merged from multi_agent_testbed

The contents of `multi_agent_testbed/` were moved into `prometheus_platform/`, creating a single unified project:

| Component | New location | Purpose |
|-----------|-------------|---------|
| Client-agent orchestrator | `agents/client-agent/` | LangGraph-based query routing, planning, and multi-agent dispatch |
| Agent registry | `registry/` | Lightweight FastAPI service for agent discovery and capability search |
| PrometheusAgent SDK | `prometheus_api/` | Base class for building A2A agents with auth, health checks, artifact handling |
| Specialist agents | `agents/*/` | Corrosion, radiation, thermal, data, synthesis, OSTI, form-filler, requirements agents |
| Artifact registry | `prometheus_api/agent/artifacts.py` | Conversation-scoped artifact tracking in Redis |
| Docker Compose stack | `docker-compose.yml` | Full-stack deployment with all services |

### What was added to the frontend

| Component | File | Purpose |
|-----------|------|---------|
| A2A client | `frontend/utils/a2a_client.py` | JSON-RPC 2.0 client with status polling during blocking calls |
| Conversation state client | `frontend/utils/conversation_state_client.py` | Redis client for browsing recent conversation state from the UI |
| Conversation tracking | `frontend/components/message_handler.py` | `conversation_id` and artifact catalog persisted in Chainlit session |
| Follow-up questions | `message_handler.py:_handle_needs_info()` | Renders DynamicForm for structured input collection |
| Plan approval | `message_handler.py:_handle_plan_ready()` | Shows execution plans with PlanViewer and approve/reject actions |
| Artifact rendering | `message_handler.py:render_artifacts()` | Routes artifact types to IFC, Exodus, PDF, Mermaid, or data viewers |
| PlanViewer component | `frontend/public/elements/PlanViewer.jsx` | Rich plan visualization with step status tracking |
| `agent-url` config | `frontend/config.yml` | Points frontend at the client-agent A2A endpoint |
| `redis-url` config | `frontend/config.yml` | Redis connection for conversation history and status polling |

### What was preserved unchanged

- **Custom React elements**: `ExodusViewer.jsx`, `IFCViewer.jsx`, `MermaidViewer.jsx`, `DynamicForm.jsx`, `FollowUpSuggestions.jsx` -- no protocol dependency, receive props from Python
- **File upload handling**: Exodus, IFC, and PDF uploads are still processed locally in the frontend before any agent call
- **Chainlit authentication**: Password-based auth via `config.yml` local-users, independent of agent auth
- **Settings panel**: Debug toggles, agent name display, auto-approve setting
- **VTK/IFC build tooling**: `public/js/` bundles for 3D viewers

## Why these changes were made

### Eliminating the backend middleman

The old FastAPI backend was a pass-through: it received chat messages from the frontend, forwarded them to a basic LLM, and returned responses. It added latency and maintenance burden without meaningful logic. The client-agent in `multi_agent_testbed` already handled query classification, agent discovery, planning, and execution -- duplicating this in the backend served no purpose.

### Multi-agent orchestration

The old backend had a single LLM endpoint. The new architecture routes queries to specialist agents based on capability metadata, supports multi-step execution plans with user approval, and chains agent outputs across workflow steps. This required the client-agent's LangGraph workflow, LiteLLM-backed agent discovery/routing, and the A2A protocol for inter-agent communication.

### Artifact management

The old backend used hardcoded demo endpoints (`/api/demo/ifc`, `/api/demo/exodus`) to serve static artifacts. The new system has a conversation-scoped artifact registry where any agent can produce artifacts (JSON, files, references) that are tracked across conversation turns and rendered by appropriate frontend viewers.

## Configuration changes

### Old configuration (config.yml)

```yaml
platform-url: "http://localhost:8001"   # FastAPI backend
model: "gpt-oss-120B"                   # Direct model selection
openai_api_key: "..."                   # Direct API key
```

### New configuration (config.yml)

```yaml
agent-url: "http://localhost:8001"      # Client-agent A2A endpoint
agent-secret: ""                        # Bearer token (use AGENT_SECRET env var)
redis-url: "redis://localhost:6379"     # Redis for conversation state/status
debug: true
auto-approve-steps: false
```

Model selection and API keys are now configured on the client-agent and specialist agents, not the frontend.

### Environment variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `AGENT_SECRET` | Frontend + all agents | Shared Bearer token for A2A auth |
| `ANTHROPIC_API_KEY` | Client-agent + specialists | LLM API access |
| `REDIS_URL` | Client-agent + frontend | Conversation state, status polling, and history browser |
| `REDIS_PASSWORD` | Redis container | Redis auth |
| `LITELLM_URL` | All agents | LiteLLM base URL for A2A routing and discovery |
| `LITELLM_MASTER_KEY` | Client-agent + specialists | LiteLLM auth for agent discovery/registration |
| `LITELLM_DB_PASSWORD` | LiteLLM Postgres | Persistent storage for LiteLLM agent registrations |
| `LITELLM_LOCAL_PORT` | Docker Compose host mapping | Host port that exposes LiteLLM locally (default: `9977`) |
| `MODEL_NAME` | All agents | LLM model selection (default: `claude-sonnet-4-20250514`) |
| `CHAINLIT_AUTH_SECRET` | Frontend | Session encryption secret for Chainlit |

## Protocol change: HTTP REST to A2A JSON-RPC

### Before (old backend)

```python
# Frontend → Backend
requests.post(
    "http://backend:8001/api/chat",
    json={"message": "Analyze SS316...", "user_id": "user_123"},
    headers={"Authorization": "Bearer <hardcoded-token>"},
)
# Response: {"type": "workflow", "response": "...", "workflow_id": "..."}
```

### After (A2A client-agent)

```python
# Frontend → Client-Agent
client = A2AClient(agent_url="http://client-agent:8001", agent_secret=os.getenv("AGENT_SECRET"))
response = await client.send(
    query="Analyze SS316...",
    conversation_id=conv_id,
    artifacts=artifact_catalog,
)
# Response: ConversationResponse(status="completed", report="...", artifacts=[...])
```

The key differences:

1. **Protocol**: Plain HTTP POST with flat JSON body becomes JSON-RPC 2.0 with nested `message/send` envelope
2. **State**: No conversation tracking becomes `conversation_id` + Redis-backed state
3. **Response model**: `{type, response}` becomes `ConversationResponse` with lifecycle states (`needs_info`, `plan_ready`, `completed`, `answer`)
4. **Auth**: Hardcoded token becomes configurable `AGENT_SECRET` env var
5. **Artifacts**: Ephemeral demo URLs become conversation-scoped registry with typed rendering

## Known limitations

- **Status polling instead of streaming**: The client-agent uses blocking mode (`blocking: true`). The A2A client polls `/status/{conversation_id}` every 3 seconds for progress updates, but there is no real-time streaming from specialist agents.
- **Conversation state has no TTL**: Redis conversation keys persist indefinitely. A 24-48 hour TTL should be added to prevent unbounded memory growth.
## Docker Compose changes

The deployment moved from a frontend-only Docker setup to a full multi-agent stack defined in `docker-compose.yml` at the project root:

| Service | Port | Role |
|---------|------|------|
| LiteLLM Agent Gateway | 9977 | Agent discovery and A2A routing |
| Client Agent | 8001 | Orchestration |
| Corrosion Agent | 8002 | Specialist |
| Radiation Agent | 8003 | Specialist |
| Thermal Agent | 8004 | Specialist |
| Data Agent | 8005 | Specialist |
| Form Filler | 8006 | Specialist |
| OSTI Research | 8007 | Specialist |
| Artifact Debug | 8008 | Testing |
| Synthesis Agent | 8009 | Specialist |
| Redis | 6379 | State/status |
| LiteLLM DB | 5432 | Persistent LiteLLM metadata store |
| Chainlit Frontend | 8500 | UI |

All containers share the `agent-network` bridge. Specialist agents register with LiteLLM on startup, and the client-agent discovers them dynamically through LiteLLM's `/v1/agents` directory.
