# Architecture

## System overview

Prometheus is a multi-agent platform for nuclear engineering analysis. A Chainlit chat frontend communicates with a central client-agent orchestrator, which dynamically routes queries to specialist agents using the A2A (Agent-to-Agent) JSON-RPC 2.0 protocol. Redis provides conversation state and status persistence.

## Architecture diagram

```mermaid
graph TD
  subgraph Frontend
    CL[Chainlit UI<br/>Python + custom JSX elements]
  end

  subgraph Orchestration
    CA[Client Agent<br/>LangGraph + Claude]
    LLM[LiteLLM Agent Gateway<br/>A2A routing + agent directory]
    RED[(Redis<br/>conversation state + status)]
  end

  subgraph Specialists
    CORR[Corrosion Agent]
    RAD[Radiation Agent]
    THERM[Thermal Agent]
    DATA[Data Agent]
    SYNTH[Synthesis Agent]
    OSTI[OSTI Research Agent]
    FF[Form Filler Agent]
    REQ[Requirements Agent]
  end

  CL -->|A2A JSON-RPC<br/>Bearer token| CA
  CA -->|GET /v1/agents + A2A via /a2a/{agent}| LLM
  CA -->|store/retrieve conversation state<br/>status updates| RED
  LLM -->|A2A JSON-RPC| CORR
  LLM -->|A2A JSON-RPC| RAD
  LLM -->|A2A JSON-RPC| THERM
  LLM -->|A2A JSON-RPC| DATA
  LLM -->|A2A JSON-RPC| SYNTH
  LLM -->|A2A JSON-RPC| OSTI
  LLM -->|A2A JSON-RPC| FF
  LLM -->|A2A JSON-RPC| REQ

  CORR -.->|register| LLM
  RAD -.->|register| LLM
  THERM -.->|register| LLM
  DATA -.->|register| LLM
  SYNTH -.->|register| LLM
  OSTI -.->|register| LLM
  FF -.->|register| LLM
  REQ -.->|register| LLM
```

## Component responsibilities

### Chainlit frontend

The frontend is a Python Chainlit application that provides:

- Chat interface with status polling during long-running agent calls
- File upload handling (Exodus, IFC, PDF) with local processing
- Custom React elements for visualization (ExodusViewer, IFCViewer, MermaidViewer, PlanViewer)
- Authentication (password-based, OAuth-ready)
- Settings panel with agent toggles and debug tools
- Follow-up suggestion cards and DynamicForm for structured input
- Conversation history browser backed by Redis state

The frontend communicates with the client-agent via A2A JSON-RPC. During blocking A2A calls, the A2A client polls the agent's `/status/{conversation_id}` endpoint every 3 seconds and displays progress updates in a `cl.Step` element.

### Client-agent (orchestrator)

The client-agent is a LangGraph-based orchestrator that:

1. **Classifies queries** using LLM-based routing with capability metadata
2. **Discovers agents** from LiteLLM's agent directory and specialist agent cards
3. **Collects parameters** by asking follow-up questions when information is missing
4. **Builds execution plans** for multi-step analyses
5. **Manages approval gates** before executing plans
6. **Dispatches work** to specialist agents via A2A
7. **Synthesizes results** from multiple agents into coherent responses

**Routing flow:**

```
understand_query → route_by_decision
    ├─ "fallback"        → fallback_response → END
    ├─ "direct_invoke"   → invoke_agent_generic → END
    ├─ "collect_params"  → ask_followup_dynamic → END
    └─ "plan_and_approve"→ plan → show_plan → [approval] → execute → END
```

### LiteLLM agent gateway

LiteLLM now serves as the shared A2A gateway and agent directory. In the current stack it provides:

- Runtime agent registration persisted in PostgreSQL
- Agent listing via `/v1/agents`
- A2A request routing via `/a2a/{agent_name}`
- A single in-cluster endpoint that the client-agent uses for specialist dispatch

The client-agent still prefers each specialist's direct well-known agent-card endpoint when it needs full per-skill metadata, because LiteLLM's agent listing can be a lossy summary.

### Redis

Serves two purposes:

1. **Conversation state**: Multi-turn conversation state persistence (keyed by `conversation:{id}`)
2. **Status history**: Short-lived progress updates rendered in the frontend during long-running execution

### Specialist agents

Each specialist agent is a standalone container built on the `PrometheusAgent` base class from `prometheus_api`. Agents:

- Load metadata from `agent_card.json`
- Register with LiteLLM on startup
- Accept A2A JSON-RPC requests with Bearer token auth
- Execute domain-specific analysis
- Return results as artifacts

Current specialists: corrosion, radiation, thermal, data retrieval, synthesis, OSTI literature search, form filler, requirements.

## Data flow for a typical request

```mermaid
sequenceDiagram
    participant U as User
    participant CL as Chainlit
    participant CA as Client Agent
    participant LLM as LiteLLM
    participant SA as Specialist Agent
    participant R as Redis

    U->>CL: "Analyze SS316 corrosion at 300C"
    CL->>CA: A2A message/send (query, conversation_id)
    CA->>R: Retrieve prior conversation state
    CA->>LLM: GET /v1/agents (find corrosion agent)
    CA->>CA: LLM classifies → "direct_invoke"
    CA->>LLM: POST /a2a/corrosion-agent/message/send
    LLM->>SA: A2A message/send (params)
    SA-->>CA: Result + artifacts
    CA->>R: Store updated conversation state
    CA-->>CL: ConversationResponse (status, artifacts)
    CL-->>U: Render response + artifact viewers
```

## A2A protocol

All inter-agent communication uses JSON-RPC 2.0 over HTTP POST:

```json
{
  "jsonrpc": "2.0",
  "id": "request-uuid",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-uuid",
      "role": "user",
      "parts": [{"type": "text", "text": "{\"query\": \"...\", \"conversation_id\": \"...\"}"}]
    },
    "configuration": {"blocking": true},
    "context": {"skillId": "analyze_corrosion", "conversationId": "conv-uuid"}
  }
}
```

Authentication uses Bearer tokens via the `Authorization` header, validated by `BearerTokenMiddleware` in the PrometheusAgent base class.

**Current limitation:** The client-agent uses blocking mode (`blocking: true`), meaning it waits for the full specialist agent response before returning. There is no real-time streaming from specialist agents to the frontend.

## LiteLLM integration

LiteLLM is part of the active deployment. It serves two roles:

1. Agent registration/discovery for A2A routing
2. Optional shared model proxy for LLM calls

```yaml
# litellm config.yaml
model_list:
  - model_name: "claude-sonnet"
    litellm_params:
      model: "anthropic/claude-sonnet-4-20250514"
      api_key: "${ANTHROPIC_API_KEY}"
```

Agents call litellm's OpenAI-compatible endpoint instead of Anthropic directly. This centralizes model configuration and enables provider switching without agent changes.

## Deployment

All services are containerized via Docker Compose:

| Service | Container | Port | Role |
|---------|-----------|------|------|
| LiteLLM | litellm-proxy | 9977 | Agent discovery and A2A routing |
| LiteLLM DB | litellm-db | 5432 | Persistent LiteLLM metadata |
| Client Agent | client-agent | 8001 | Orchestration |
| Corrosion Agent | corrosion-agent | 8002 | Specialist |
| Radiation Agent | radiation-agent | 8003 | Specialist |
| Thermal Agent | thermal-agent | 8004 | Specialist |
| Data Agent | data-agent | 8005 | Specialist |
| Form Filler | form-filler-agent | 8006 | Specialist |
| OSTI Research | osti-research-agent | 8007 | Specialist |
| Artifact Debug | artifact-debug-agent | 8008 | Testing |
| Synthesis Agent | synthesis-agent | 8009 | Specialist |
| Redis | agent-redis | 6379 | State/status |
| Chainlit Frontend | chainlit-frontend | 8500 | UI |

All containers share the `agent-network` bridge network. Environment variables for secrets and host mappings (`ANTHROPIC_API_KEY`, `AGENT_SECRET`, `REDIS_PASSWORD`, `LITELLM_MASTER_KEY`, `LITELLM_DB_PASSWORD`, `LITELLM_LOCAL_PORT`) are passed via `.env` file.
