# Prometheus Merge: Critical Design Review

**Date:** 2026-03-13
**Scope:** Merging `multi_agent_testbed` backend into `prometheus_platform` with Chainlit frontend

---

## 1. prometheus_platform Backend: LiteLLM-Based Approach

**Verdict: Aspirational, not actual.** The architecture docs recommend LiteLLM as a shared model proxy, but the codebase doesn't use it. The chat endpoint (`backend/routers/chat.py`) hardcodes an OpenAI client pointed at `https://api.i2-core.american-science-cloud.org/v1` with a literal API key in source. This is the worst of both worlds: you pay the complexity tax of planning for LiteLLM without any of its benefits.

**What it does well:**
- The FastAPI backend is clean and minimal. Routers are well-separated (chat, demo, demo_workflow).
- The NDJSON streaming for workflow events (`WorkflowEvent`) is a good pattern for long-running multi-step operations.
- The A2A client in `orchestrator/a2a_client.py` is a reasonable thin wrapper.

**Limitations:**
- **Hardcoded credentials** in `chat.py` and `state/deeplynx.py`. This is a ship-blocker for any environment beyond local dev.
- **3-second hardcoded sleep** in `orchestrator/a2a_client.py` (line ~98). This is debugging detritus that will silently degrade every agent call.
- The backend is essentially a thin proxy right now. It doesn't do orchestration — the `multi_agent_testbed` client-agent does. The two backends overlap in purpose, and the `prometheus_platform` backend will likely become dead code once the merge is done.

**Recommendation:** Drop the `prometheus_platform` backend entirely. The Chainlit frontend already has its own A2A client (`frontend/utils/a2a_client.py`) that talks directly to the client-agent. The FastAPI backend is redundant middleware. If you need demo endpoints or DeepLynx integration, add them as routes on the client-agent or as a small sidecar service — not as a gateway that duplicates orchestration logic.

---

## 2. multi_agent_testbed Client-Agent: LangGraph Orchestration

**Verdict: Well-structured but over-invested in flexibility.** The `understand_query -> route_by_decision` flow is the right core abstraction. The four routing outcomes (fallback, direct_invoke, collect_params, plan_and_approve) cover the necessary cases cleanly. The `AgentState` TypedDict is comprehensive.

**What works:**
- Dynamic tool discovery from the registry is genuinely useful. Creating LangChain `StructuredTool` objects from agent card schemas means adding a new specialist requires zero client-agent changes.
- The planning system (`planner.py`) using LLM-callable tools (`select_capabilities`, `set_plan_steps`, etc.) is clever. It forces the LLM to produce structured output through tool calls rather than hoping for valid JSON in free text.
- Capability caching with Redis + in-memory fallback is pragmatic.

**Over-engineered parts:**
- **Workflow Library** (`workflow_library/`): This is a second orchestration system layered on top of LangGraph. You now have three ways to run a multi-agent task: (1) LangGraph `plan_and_approve` path, (2) YAML workflow templates with DAG execution, (3) the `prometheus_platform` backend's `wf_fmea.py`/`wf_alchemy.py` hardcoded workflows. Pick one. The YAML workflow system has a regex-based pattern matcher, a DAG compiler, a parameter binding system with derivation rules — this is a lot of machinery for what could be an LLM routing decision.
- **`create_input_schema_from_skill()`** dynamically generates Pydantic models from JSON schemas at runtime. This works but is fragile — edge cases in nested objects, reserved field name remapping (`schema` -> `schema_`), and the blanket `model_config = {"extra": "allow"}` means validation is weaker than it appears.
- **Execution priority system** (`early`/`normal`/`late`) in skill ordering is premature. With 7 agents, explicit ordering in the plan is simpler and more debuggable than implicit priority scoring.

**Recommendation:** For the merge, keep the LangGraph orchestration as the single execution engine. Delete the YAML workflow library. If you need canned workflows (like the FMEA sequence), encode them as system prompts or few-shot examples that guide the planner, not as a parallel execution framework. The planner is already good enough to sequence skills correctly — trust it.

---

## 3. A2A Protocol: JSON-RPC 2.0 + Streaming

**Verdict: Solid foundation with significant gaps in error handling and streaming.**

**What's good:**
- JSON-RPC 2.0 is a well-specified wire format. Using `message/send` with blocking configuration is straightforward.
- Bearer token auth via middleware is correct. Exempting `/health` and `/.well-known/agent.json` is the right call.
- The response extraction logic (status.message.parts -> artifacts -> history reverse scan) handles real-world A2A response variability.

**Protocol ambiguities and edge cases:**
- **No streaming implementation.** `capabilities.streaming: false` on every agent. The `PREFER_A2A_STREAMING` flag in the frontend is a dead feature. For long-running agents (OSTI research with 15-minute timeout), the user sees nothing until completion. This is a terrible UX.
- **No cancellation.** If a user navigates away or starts a new query, there's no way to cancel an in-flight 15-minute OSTI research call. The agent keeps burning tokens and compute.
- **Response extraction is a 5-layer fallback cascade.** This means there's no canonical response location — agents can put results in `status.message.parts`, `artifacts`, or `history`, and the client will find it somehow. This works until it doesn't. When an agent returns both artifacts and a status message with different content, which one wins? The answer depends on which extraction path fires first, not on intent.
- **No error taxonomy.** A2A errors are generic. There's no distinction between "agent is down," "agent rejected the input," "agent timed out," and "agent produced an invalid response." The client-agent treats all failures the same way.
- **Hardcoded 900-second timeout.** This is per-call, not per-conversation. A plan with 5 sequential agent calls could take 75 minutes with no intermediate feedback.

**Recommendation:** Define a canonical response location (I'd pick `status.message.parts` for final text, `artifacts` only for binary/structured data). Add SSE streaming for progress updates — even fake progress ("Searching OSTI database...", "Analyzing 47 papers...") dramatically improves perceived responsiveness. Implement a `message/cancel` method. Define error codes: -32001 (agent unavailable), -32002 (input validation failed), -32003 (timeout), -32004 (internal agent error).

---

## 4. Registry: LiteLLM Proxy vs. Homemade Registry

**Verdict: They solve different problems. You need both, but scoped correctly.**

The homemade registry (`registry/app.py`) is an **agent/skill registry** — it tracks which agents exist, what skills they offer, and their input schemas. LiteLLM is a **model proxy** — it abstracts LLM provider APIs, handles fallbacks, rate limiting, and key rotation.

These are orthogonal concerns. The user's preference for LiteLLM is correct **for model access**, but LiteLLM cannot replace the agent registry. There is no LiteLLM feature that says "here are my 7 specialist agents with their JSON schemas."

**Current registry limitations:**
- **In-memory storage.** If the registry container restarts, all registrations are lost. Agents re-register on startup, but there's a window where the client-agent has stale cache entries pointing at agents the registry doesn't know about.
- **No health checking.** Agents register once; the registry never verifies they're still alive. The heartbeat endpoint exists but agents don't call it. A crashed agent stays registered forever (until registry restart).
- **No versioning.** When you deploy a new version of an agent with a changed skill schema, the registry just overwrites. There's no way to do rolling updates where old and new versions coexist.

**Recommendation:** Keep the homemade registry for agent/skill discovery — it's simple and fit for purpose. Add LiteLLM as a separate service that all agents route their LLM calls through. This gives you: unified API key management (agents don't each need `ANTHROPIC_API_KEY`), model fallback chains, spend tracking, and the ability to swap models without redeploying agents. For the registry itself: add a 60-second heartbeat requirement and auto-deregister after 3 missed heartbeats. Store registrations in Redis (you already have it) so they survive restarts.

---

## 5. Memory System: Redis Factoids

**Verdict: Reasonable v1, but the embedding search is a trap.**

**Good design choices:**
- Factoid schema is well-structured: `material_id`, `analysis_type`, `content`, `confidence`, `embedding`.
- Multi-index lookups (by material, by analysis type) via Redis sets are fast and correct.
- Conversation state persistence in Redis enables multi-turn flows.

**Failure modes:**
- **No TTL on factoids.** Conversations have no TTL either. Over time, Redis fills up with stale factoids from months-old analyses. There's no eviction policy. The artifact registry has a 7-day TTL — factoids should too, or at least have a configurable retention window.
- **Cosine similarity search in Python.** The `search_similar_factoids()` method loads all candidate factoid embeddings from Redis, then computes cosine similarity in a Python loop. This is O(n) per query and will degrade as factoid count grows. At 10K factoids it's fine; at 100K it's a problem.
- **Embedding generation is opaque.** The code stores embeddings but it's unclear where they're generated. If different agents use different embedding models, the similarity scores are meaningless.
- **No deduplication.** Running the same corrosion analysis twice on SS316 produces duplicate factoids. There's no content hashing or similarity-based dedup.
- **Redis as vector store.** Redis Stack has native vector search (RediSearch with VECTOR fields + KNN). The codebase doesn't use it — it reinvents vector search in Python. This is slower and less capable than what Redis already offers.

**Recommendation:** Add 30-day TTL to factoids (configurable). Switch to RediSearch vector indexing (`FT.CREATE` with VECTOR field, `FT.SEARCH` with KNN) — this gives you proper ANN search with sub-millisecond latency at scale. Add content hashing to prevent duplicates: hash `(material_id, analysis_type, content)` and skip if exists. Standardize on a single embedding model (e.g., `text-embedding-3-small`) called via LiteLLM.

---

## 6. Artifact System: Chainlit Integration

**Verdict: Clean schema, awkward integration seam.**

**Schema strengths:**
- `ArtifactReference` is well-designed: ID, conversation scoping, MIME type, producer agent tracking, tags, metadata. The 7-day TTL is sensible.
- Name-based resolution (normalized, lowercase) is a good UX touch — users can reference "corrosion report" without knowing artifact IDs.
- Backward compatibility with both snake_case and camelCase is practical for a system where multiple codebases interact.

**Integration concerns:**
- **Two artifact catalogs.** The Chainlit frontend maintains its own artifact list in session state (`cl.user_session.get("artifacts")`), and the backend has `ArtifactRegistry` in Redis. These can diverge. If the user refreshes the page, the Chainlit session resets but Redis artifacts persist. If an agent produces an artifact mid-conversation, it goes to Redis but the frontend won't know until the next response.
- **URI resolution.** Artifact URIs are HTTP URLs, but some point to `localhost:8008` (artifact-debug-agent). In Docker, this resolves to the container. From the browser, it doesn't. There's no URI rewriting layer.
- **Viewer routing is fragile.** The frontend routes artifacts to viewers by checking `metadata.type`, then file extension, then tags, then MIME type — in that order. This means the same artifact could render differently depending on which fields are populated. A PDF with `tags: ["ifc"]` would get the IFC viewer.
- **No artifact content in A2A response.** Artifacts are references (URIs), not inline data. This means the client needs HTTP access to the artifact storage. In a firewalled environment, the browser may not reach the agent's artifact endpoint.

**Recommendation:** Make Redis the single source of truth for artifacts. On Chainlit session start, hydrate from Redis by conversation ID. Add a `/artifacts/{id}/content` proxy endpoint on the client-agent so the browser doesn't need direct access to specialist agents. Fix viewer routing: use MIME type as the primary discriminator, not a 4-level fallback cascade. Define a strict mapping: `application/pdf` -> PDF viewer, `model/ifc` -> IFC viewer, etc.

---

## 7. LangGraph Choice: Framework Tradeoffs

**Verdict: Defensible but heavy for the current use case.**

**Why it works here:**
- The conditional routing (`route_by_decision`) maps naturally to LangGraph's graph edges.
- State management across multi-turn conversations (collecting params, approving plans, executing) benefits from LangGraph's checkpoint system.
- Dynamic tool binding (discovered from registry) integrates cleanly with LangChain's tool abstraction.

**Tradeoffs:**
- **Dependency weight.** LangGraph pulls in LangChain core, which pulls in a substantial dependency tree. For what's essentially a state machine with 4-5 nodes, this is a lot of framework.
- **Debugging opacity.** When something goes wrong in a LangGraph execution, the stack traces go through multiple layers of framework code. The `understand_query` -> `route_by_decision` -> `plan` -> `execute` flow is conceptually simple but the runtime path is not.
- **Version coupling.** LangGraph and LangChain release frequently with breaking changes. The dynamic tool creation code (`create_input_schema_from_skill`) is tightly coupled to LangChain's `StructuredTool` internals. A LangChain minor version bump could break tool discovery.
- **Overkill for blocking calls.** Every A2A call is `blocking: true`. There's no parallel execution, no streaming, no async fan-out. The graph executes as a linear sequence of blocking HTTP calls. A simple `async for step in plan: await call_agent(step)` loop would produce identical behavior with zero framework overhead.

**Recommendation:** Keep LangGraph for now — the migration cost isn't worth it, and it does provide useful structure for the conversation state machine. But isolate the LangChain dependency: wrap tool discovery behind your own interface so you can swap the underlying tool abstraction without touching agent code. When you add real streaming or parallel execution, LangGraph will justify its weight. Until then, treat it as a structured state machine, not an execution engine.

---

## 8. Docker Compose Structure

**Verdict: Good for dev, not production-ready.**

**Well-organized aspects:**
- Service dependency graph is correct: registry starts first (healthcheck), then Redis, then agents that depend on both.
- Shared volume (`./shared:/app/shared`) for artifact exchange between agents is practical.
- ML model cache volumes for OSTI agent prevent re-downloading on container restart.
- CA certificate support for corporate proxy environments shows real-world deployment awareness.

**Missing for production:**
- **No resource limits.** Any agent can consume unbounded CPU/memory. A runaway LLM call or large mesh processing could starve other containers. Add `deploy.resources.limits` for CPU and memory.
- **No restart policies.** If an agent crashes, it stays dead. Add `restart: unless-stopped` at minimum.
- **No logging configuration.** All agents log to stdout with no structured format, no log levels, no aggregation. Add a logging driver (json-file with max-size, or ship to a log aggregator).
- **Redis has no persistence config.** The `redis-data` volume exists, but Redis runs with default RDB snapshotting. For conversation state that matters, enable AOF or at least configure `save` intervals.
- **No TLS between services.** All inter-agent communication is plaintext HTTP on a Docker bridge network. The Bearer token is sent in cleartext. For production, add TLS or use a service mesh.
- **Single Redis instance.** No replication, no sentinel. Redis failure takes down memory, artifacts, capability cache, and conversation state simultaneously.
- **No health checks on specialist agents.** Only the registry has a healthcheck. If the corrosion agent's `/health` endpoint starts returning 500, Docker won't restart it and the registry won't know.
- **Frontend is Streamlit, not Chainlit.** The `docker-compose.yml` defines a Streamlit frontend on port 8501. The merge target is Chainlit on port 8500. This service definition needs to be replaced entirely.

**Recommendation:** For the merged compose file: (1) Add healthchecks to every agent service. (2) Add `restart: unless-stopped` globally. (3) Add resource limits (start with 512MB/0.5 CPU per specialist, 1GB/1 CPU for client-agent). (4) Replace the Streamlit frontend service with the Chainlit frontend. (5) Add LiteLLM as a new service. (6) Configure Redis AOF persistence. (7) Add a `prometheus-net` network with internal DNS. Leave TLS and log aggregation for a later production hardening pass.

---

## 9. Concrete Recommendations for the Combined Project

### Architecture Decisions (Do These First)

| # | Decision | Recommendation | Rationale |
|---|----------|---------------|-----------|
| 1 | **Backend selection** | Drop `prometheus_platform` backend. Use `multi_agent_testbed` client-agent as sole backend. | The PP backend is a thin proxy that duplicates what the client-agent already does. Two backends = two places for bugs. |
| 2 | **Workflow engine** | Delete YAML workflow library. Keep LangGraph planner only. | Three workflow systems is two too many. The LLM planner handles sequencing; canned workflows become system prompts. |
| 3 | **Model proxy** | Add LiteLLM as a Docker service. Point all agents at it. | Centralizes API keys, enables model fallback, gives you spend tracking. The registry stays for agent discovery. |
| 4 | **Frontend** | Chainlit frontend talks directly to client-agent via A2A. No intermediate backend. | Eliminates a network hop and a codebase to maintain. |

### Code Changes (Do These During Merge)

| # | Change | Files Affected | Priority |
|---|--------|---------------|----------|
| 5 | Remove hardcoded credentials; use env vars everywhere | `chat.py`, `deeplynx.py`, `.env` | **Critical** |
| 6 | Remove 3-second sleep from A2A client | `orchestrator/a2a_client.py` | High |
| 7 | Add TTL to Redis factoids (30 days default) | `memory_manager.py` | High |
| 8 | Switch to RediSearch vector indexing | `memory_manager.py` | Medium |
| 9 | Standardize A2A response location (status.message.parts for text, artifacts for binary) | All agents, `tool_discovery.py` | Medium |
| 10 | Add healthchecks to all Docker services | `docker-compose.yml` | Medium |
| 11 | Add artifact proxy endpoint on client-agent | `client-agent/agent.py` | Medium |
| 12 | Add content-hash deduplication for factoids | `memory_manager.py` | Low |
| 13 | Add `message/cancel` to A2A protocol | `prometheus_api` | Low |

### Technical Debt to Accept (Don't Fix Now)

- LangGraph dependency weight — migration cost exceeds benefit
- In-memory registry storage — Redis-backed registry is nice-to-have, not blocking
- No TLS between services — acceptable on a Docker bridge network for now
- No streaming from specialists — add this post-merge when UX testing confirms it matters
- Execution priority system — harmless complexity, not worth removing

---

## Summary

The multi_agent_testbed is the stronger codebase. Its orchestration (LangGraph + dynamic tool discovery + A2A) is the right foundation. The prometheus_platform's main contribution is the Chainlit frontend and its specialized viewers (IFC, Exodus, Mermaid) — these are genuinely valuable and should be preserved. The prometheus_platform backend should be retired.

The biggest risks in the merge are: (1) maintaining two artifact catalogs that can diverge, (2) inheriting three workflow execution systems instead of converging on one, and (3) not adding LiteLLM early enough, leading to continued credential sprawl across agents.

The system is well-architected for its current scale (7 specialists, single-user). The gaps are in production hardening (resource limits, health checks, Redis persistence) and UX (no streaming, no cancellation, opaque long-running operations). These are solvable problems — the foundational abstractions are sound.
