# Critical Design Review: Prometheus Combined Project

**Date:** 2026-03-13
**Reviewer:** critical-reviewer agent
**Scope:** Merging multi_agent_testbed into prometheus_platform, dropping the FastAPI backend, replacing the homemade registry with litellm.

---

## 1. Registry: litellm as service registry

### What the homemade registry actually does

The current registry (`registry/app.py`) is a ~220-line FastAPI service providing:

- **Agent registration** (`POST /agents/register`): Stores agent ID, name, URL, capabilities list, full agent card (with skills and input schemas), and timestamps in an in-memory dict.
- **Agent discovery** (`GET /agents`, `GET /agents/{id}/card`): Returns registered agent metadata including full agent cards with skill definitions and input schemas.
- **Capability-based lookup** (`GET /agents/by-capability/{cap}`, `GET /capabilities`, `GET /capabilities/search`): Flattens all skills across all agents into a searchable catalog with tags, descriptions, input schemas, derivation rules, and expected durations.
- **Heartbeat** (`POST /agents/{id}/heartbeat`): Updates last-seen timestamp for liveness tracking.
- **Deregistration** (`DELETE /agents/{id}`): Removes agents from the registry.

The client-agent's `tool_discovery.py` queries this registry to dynamically build LangChain `StructuredTool` instances from agent card skill definitions, including dynamic Pydantic model generation from `inputSchema`.

### What litellm's proxy actually provides

litellm is a **model routing proxy**. It provides:

- Unified API to call 100+ LLM providers (OpenAI, Anthropic, etc.)
- Load balancing across model deployments
- Rate limiting, spend tracking, API key management
- A `/model/info` endpoint for listing registered models

It does **not** provide:

- Agent registration or discovery
- Skill/capability cataloging
- Agent card hosting or input schema management
- Health monitoring for arbitrary services
- Capability-based routing (it routes by model name, not by skill semantics)

### Verdict: litellm is a poor fit for agent registration/discovery

litellm solves a fundamentally different problem. You can register LLM endpoints in litellm, but you cannot register "an agent that performs corrosion analysis with these input parameters and these skills." The capability search (`/capabilities/search`), skill flattening, and input schema propagation that the client-agent depends on have no analog in litellm.

### Recommendation

**Use litellm for what it's good at: LLM model routing.** Replace the current pattern where every agent independently creates its own `ChatAnthropic` instance with `MODEL_NAME` env var. Instead, point all agents at a single litellm proxy that handles model selection, fallback, rate limiting, and key management.

**Keep a lightweight registry for agent discovery.** The current registry is only ~220 lines and solves its problem adequately. Don't try to force litellm into the service discovery role. If the in-memory storage bothers you, swap it for a Redis-backed dict (you already have Redis in the stack). If you want something off-the-shelf, consider Consul or etcd, but honestly, the current registry is simple enough that it's not the problem.

---

## 2. Client-agent complexity

### The numbers

- `agent.py`: **3,678 lines / 149 KB** in a single file
- 50+ top-level functions and classes
- Responsibilities include: conversation state management, dynamic routing, follow-up question generation, plan compilation, plan approval, multi-step execution, memory retrieval/extraction, artifact resolution, context map propagation, parameter derivation from capability metadata, workflow library integration, status polling via Redis, and the A2A executor wrapper

### Is the complexity justified?

Partially. The client-agent is doing genuinely complex orchestration: it takes a natural language query, classifies it, discovers which agents can handle it, figures out what parameters are missing, asks the user, builds an execution plan, gets approval, runs the plan across multiple agents, synthesizes results, and stores factoids for future recall. That's a lot of responsibility.

But 3,678 lines in one file is not "complex orchestration," it's "everything in one place." The file mixes:

1. **Data models** (ConversationRequest, ConversationResponse, AgentState) — should be a separate `models.py`
2. **Pure utility functions** (JSON extraction, parameter path manipulation, schema flattening) — should be `utils.py`
3. **Memory/factoid logic** (retrieve_memories, extract_memories) — already has `memory_manager.py`, should be used more
4. **Planning logic** (compile_query_plan, plan_analysis) — partially extracted to `planner.py` but still has ~400 lines of planning in agent.py
5. **Parameter resolution** (~500 lines of `resolve_params_via_capability_metadata`, `extract_required_param_paths`, `apply_artifact_param_resolution`) — should be its own module
6. **Workflow execution** — partially in `workflow_library.py` but duplicated in agent.py
7. **The actual LangGraph workflow** — buried somewhere in the middle

### Is LangGraph the right choice?

Looking at the CLAUDE.md routing diagram:

```
understand_query → route_by_decision
    ├─ "fallback"        → fallback_response → END
    ├─ "direct_invoke"   → invoke_agent_generic → END
    ├─ "collect_params"  → ask_followup_dynamic → END
    └─ "plan_and_approve"→ plan → show_plan → [approval] → execute → END
```

This is a state machine with 4 branches and at most 4 steps in the longest path. LangGraph adds value when you need cycles (agent loops), conditional branching on intermediate LLM outputs, or tool-use retries. Here, the graph is essentially linear with a single classification branch at the top.

A simple `match` statement calling async functions would do the same thing more readably, with fewer dependencies, and without the overhead of LangGraph's state management and checkpointing (which you're not using — state is stored in Redis manually anyway).

**However**: LangGraph is not causing active harm. If the team is familiar with it and the orchestration is likely to get more complex (cycles, retries, parallel agent execution), keeping it is defensible. The real problem is the 3,678-line file, not the framework.

### What could be safely cut

1. **Workflow library integration** (if not actively used): The `ENABLE_WORKFLOW_LIBRARY` flag and all associated catalog/form/start endpoints add ~300 lines.
2. **The status polling Redis subsystem**: `store_status_update` / `get_status` / `_get_status_redis_client` — this is a mini pub-sub reimplemented on top of Redis strings. Use Redis Pub/Sub or SSE directly.
3. **Duplicated parameter resolution logic**: `resolve_params_via_capability_metadata` is ~200 lines of parameter threading that partially overlaps with `normalize_params_for_capability` and `build_plan_param_metadata`.

### Recommendation

**Split agent.py into 5-6 focused modules** before the merge. Do not merge a 149KB file into the combined project. The refactoring categories are clear and the functions are already loosely coupled.

---

## 3. A2A protocol overhead

### What A2A JSON-RPC adds

The A2A protocol wraps every agent call in a JSON-RPC envelope:

```json
{
  "jsonrpc": "2.0",
  "id": "<uuid>",
  "method": "message/send",
  "params": {
    "message": { "messageId": "<uuid>", "role": "user", "parts": [{"type": "text", "text": "..."}] },
    "configuration": { "blocking": true },
    "context": { "skillId": "...", "conversationId": "..." }
  }
}
```

Response extraction (`call_a2a_agent` in `tool_discovery.py`) is 120+ lines of defensive parsing: checking `status.message.parts`, then `artifacts.parts`, then `history` messages, looking for JSON in text parts, handling artifact references. This is because the A2A response format is highly variable depending on how the agent chose to emit its results.

### Is the overhead justified?

**For local Docker services: no.** When all agents are containers on the same Docker network, JSON-RPC adds:

- Message ID generation and tracking (unused — you don't correlate request/response IDs)
- The "parts" wrapping/unwrapping (every message is a single text part containing JSON, which is then double-parsed)
- 120 lines of fragile response extraction heuristics
- A 15-minute timeout because blocking mode waits synchronously

A simple REST endpoint (`POST /analyze`, returns JSON) would eliminate the entire parsing layer.

### When to keep A2A

Keep it if:
- You plan to expose agents to external systems or other teams that need a standard protocol
- You want to interop with Google's A2A ecosystem
- You need streaming, push notifications, or multi-turn agent conversations over A2A

### Recommendation

**Keep A2A as the external protocol but add a fast internal path.** The `PrometheusAgent` base class already exposes a `/api/chat` endpoint that accepts plain JSON and returns plain JSON. Use that for agent-to-agent calls within the Docker network. Reserve full A2A JSON-RPC for external-facing communication. This is a one-line change in `call_a2a_agent`: POST to `/api/chat` instead of `/` with a simpler payload.

---

## 4. Redis memory system

### What the factoid system actually does

`memory_manager.py` stores "factoids" — structured dictionaries with content, material_id, analysis_type, and embedding vectors. It provides:

1. **Storage**: Each factoid is a JSON blob stored at `factoid:{uuid}` in Redis.
2. **Secondary indexes**: Redis sets for `material:{id}:factoids` and `analysis_type:{type}:factoids` enable fast lookup by material or analysis type.
3. **Semantic search**: Hand-rolled cosine similarity over embedding vectors stored inside the JSON blobs. Loads ALL candidate factoids into memory, deserializes them, extracts embeddings, and computes similarity in Python.
4. **Conversation state**: Stores conversation state dicts at `conversation:{id}` with no TTL (permanent storage).

### Is Redis the right choice?

**For the secondary indexes and conversation state: yes.** Redis sets are fast, the data model is simple, and you already need Redis in the stack.

**For semantic search: absolutely not.** The current implementation:

- Loads every factoid for a material (or ALL factoids if no material filter) from Redis into Python
- Deserializes each one from JSON
- Extracts the embedding vector from the JSON blob
- Computes cosine similarity in a Python loop using `math.sqrt` and `zip`

This is O(n) in the number of factoids with Python-speed vector math. It will fall over at ~1,000 factoids. Redis itself has vector search via RediSearch (`FT.SEARCH` with `KNN`), which would solve this without adding another database. Alternatively, pgvector or ChromaDB would work, but they add deployment complexity you don't currently need.

### Recommendation

**Phase 1 (now):** Keep Redis, but use the RediSearch module for vector similarity search. Redis Stack (or `redis/redis-stack` Docker image) includes the vector search module. This means: create a RediSearch index on your factoid hash fields, store embeddings as Redis vector fields, and use `FT.SEARCH` with `KNN` instead of the Python loop. You keep one database, eliminate the O(n) scan, and get proper ANN indexing.

**Phase 2 (if needed):** If factoid volume grows to 100K+ or you need advanced RAG features (metadata filtering + vector search + full-text search), migrate to pgvector or a dedicated vector DB.

**Also:** Add a TTL to conversation state. Permanent storage with no cleanup will leak memory over time. 24-48 hours is reasonable for conversation state.

---

## 5. Chainlit frontend

### What Chainlit provides

Chainlit is a Python framework for building conversational AI UIs. For this project it provides:

- **Chat interface** with streaming support (built-in)
- **Step visualization** (nested tool execution display via `cl.Step`)
- **File upload handling** (Exodus, IFC, PDF) with custom element rendering
- **Authentication** (password auth, OAuth hooks ready)
- **Custom elements** (3D viewers via ExodusViewer, IFCViewer, MermaidViewer)
- **Settings panel** and action buttons (approval gates)
- **Suggestions** on chat start

### Tradeoffs vs. React SPA

**Chainlit advantages:**
- Rapid prototyping — the frontend is ~300 lines of Python, not 10,000 lines of React/TypeScript
- Built-in streaming, step nesting, and file handling
- Custom elements via React components (you already have 3D viewers working)
- No separate build pipeline, no node_modules, no webpack

**Chainlit disadvantages:**
- Limited layout customization (you're in a chat paradigm, can't easily add dashboards, sidebars, or data tables)
- No fine-grained state management (React Query, Redux, etc.)
- Deployment is a Python process, not a static bundle behind a CDN
- Community is small — debugging obscure issues means reading Chainlit source code

### Tradeoffs vs. Open WebUI

Open WebUI is designed for local LLM management (Ollama, etc.). It has a richer UI but is opinionated about its backend (it wants to manage models, conversations, and RAG itself). Integrating your A2A multi-agent system would mean fighting Open WebUI's architecture rather than leveraging it.

### Verdict: keep Chainlit

For a nuclear analysis research platform with custom 3D viewers and multi-step agent workflows, Chainlit is the right call. The chat paradigm fits (users ask questions, agents respond with analysis). The custom element system lets you embed Exodus/IFC viewers without building a full SPA. The step visualization maps directly to your multi-agent execution plan.

**Switch to React only if** you need a dashboard-style UI with multiple panels, persistent data tables, or complex state management beyond conversation flow.

---

## 6. Direct Chainlit → client-agent communication

### What the FastAPI backend currently provides

Looking at `message_handler.py`, the Chainlit frontend currently:

1. Sends all chat messages to `{platform_url}/api/chat` (the FastAPI backend)
2. Streams workflow events from `{platform_url}/api/demo/workflow/run`
3. Fetches artifacts from `{platform_url}/demo/exodus`, `{platform_url}/demo/ifc`, etc.

The backend acts as a gateway, proxying requests to the client-agent and adding workflow orchestration, artifact fetching, and demo endpoints.

### Security implications of removing the backend

**The current security posture is already poor.** Line 104 of `message_handler.py` has a hardcoded Bearer token:

```python
headers={"Authorization": "Bearer d8Q0ICXp1AUcGH0mLbkG-lgsUX6f_5RY7pu3KRrHUAE"}
```

The "backend" is not adding meaningful security. It's passing through requests with a static token. Removing it doesn't make things worse.

**What IS lost:**

1. **No rate limiting**: The client-agent has no request throttling. A runaway frontend or misbehaving client can hammer the agent.
2. **No request validation gateway**: The backend could validate/sanitize inputs before they reach the LLM. Without it, raw user input goes directly to the agent.
3. **No auth token management**: The current static token pattern needs to be replaced with proper auth regardless of architecture.

### Scalability implications

With the backend removed, Chainlit talks directly to the client-agent container. This is fine for single-user or small-team use. For multi-user deployment:

- The client-agent is a single uvicorn process — it can handle concurrent requests but not high throughput
- There's no horizontal scaling path without adding a load balancer
- Long-running analyses (15-minute timeout) tie up connections

### Recommendation

**Removing the FastAPI backend is correct.** It's a pass-through that adds latency and maintenance burden without meaningful security. But you need to add:

1. **Rate limiting** on the client-agent (use Starlette's `slowapi` or a simple middleware)
2. **Proper authentication** — replace the hardcoded token with JWT or API key validation that can be rotated. The `BearerTokenMiddleware` in `prometheus_api` already supports this; wire it up properly.
3. **Input sanitization** — the client-agent should validate request size and shape before passing to the LLM

---

## 7. Overall architecture recommendations

### Top 5 changes

1. **Split agent.py immediately.** 3,678 lines in one file is the single biggest maintenance risk. Extract models, utilities, parameter resolution, memory operations, and workflow logic into separate modules. Do this before the merge, not after.

2. **Use litellm as model proxy, not service registry.** Deploy litellm as a sidecar or shared service that all agents use for LLM calls. Keep the existing registry (or a simplified version) for agent discovery. This gives you model fallback, rate limiting, and spend tracking for free.

3. **Add a fast internal communication path.** Use the existing `/api/chat` endpoint for agent-to-agent calls within Docker instead of full A2A JSON-RPC. Keep A2A for the external boundary. This eliminates the brittle 120-line response parser.

4. **Upgrade Redis to Redis Stack for vector search.** Replace the hand-rolled cosine similarity with RediSearch's native vector KNN. This is a Docker image swap and ~20 lines of index creation code.

5. **Add authentication and rate limiting to the client-agent.** The hardcoded Bearer token must go. Add JWT validation and request throttling before exposing the agent directly to the frontend.

### What NOT to change

- **The A2A protocol itself**: It's a reasonable standard. The issue is using it internally where plain HTTP would suffice, not the protocol's existence.
- **The specialist agent architecture**: Separate containers for corrosion, radiation, thermal, data, and synthesis agents is clean separation of concerns. Each agent is focused and independently deployable.
- **The PrometheusAgent base class** (`prometheus_api/agent/base.py`): This is well-designed. It handles agent card loading, registry registration, auth middleware, health endpoints, and the A2A execution lifecycle in a clean, extensible way. It's the best piece of architecture in the codebase.
- **The Chainlit frontend with custom 3D viewers**: This is the right tool for the job. The Exodus/IFC/Mermaid integration via custom elements is a genuine differentiator.
- **Redis for conversation state and factoid secondary indexes**: Simple, fast, already in the stack. Don't add another database unless you have a concrete scaling problem.
