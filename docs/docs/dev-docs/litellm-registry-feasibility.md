# LiteLLM as Agent Registry Replacement — Feasibility Assessment

**Date:** 2026-03-16
**Scope:** Replace the homemade FastAPI registry (`registry/app.py`) with LiteLLM proxy as the single service for agent discovery and call routing.

---

## What the Homemade Registry Actually Does

Before assessing LiteLLM, it is worth being precise about the scope of the current registry. It is not just a lookup table. It does five things that are tightly coupled to how the client-agent works:

1. **Self-registration.** Agents call `POST /agents/register` at startup, pushing their full `agent_card.json` (including per-skill `inputSchema`, `usage_notes`, `tags`, `derivation_rules`, `expected_duration_seconds`, `requires_approval`, `execution_priority`). This is driven by `PrometheusAgent.register_with_registry()` in `prometheus_api/agent/base.py`.

2. **Capability enumeration with rich metadata.** `GET /capabilities` flattens all agent skills into a single list, preserving the full `inputSchema` JSON object for each skill. The client-agent's `CapabilityCache` (Redis-backed, 5-minute TTL) stores these per-skill `AgentCapability` objects including `input_schema`, `derivation_rules`, `provides`, and `execution_priority`.

3. **Dynamic Pydantic model generation.** `tool_discovery.create_input_schema_from_skill()` reads each skill's `inputSchema` and dynamically creates a Pydantic `BaseModel` subclass. This model is passed as `args_schema` to `StructuredTool.from_function()`, giving the LLM exact field-level type information for tool calls.

4. **Direct A2A call dispatch.** `tool_discovery.call_a2a_agent()` calls agents using JSON-RPC 2.0 (`message/send` method) with a `skillId` in the context, `blocking=True`, and Bearer token auth. The response unwrapping handles A2A's layered envelope (status.message, artifacts, history).

5. **Capability-based routing metadata for the orchestrator.** The `CapabilityCache` is used by `planner.py` and (per `CLAUDE.md`) the `dynamic_router.py` to make LLM-guided decisions about which skills to invoke and in what order, based on `usage_notes`, `tags`, `provides`, and `derivation_rules`.

---

## What LiteLLM Is

LiteLLM is an LLM proxy and SDK whose core job is to normalize calls to 100+ LLM providers behind a single OpenAI-compatible API. Its main features relevant here:

- **`config.yaml` model list.** Defines models by `model_name` + `litellm_params`. Can point `api_base` at any OpenAI-compatible HTTP endpoint.
- **Router.** Load-balances across multiple deployments of the same model using strategies like latency-based, usage-based, least-busy, and weighted. Designed exclusively for LLM completions.
- **Pass-through endpoints.** Forwards HTTP requests verbatim to third-party APIs (Cohere, Bria, Azure Assistants, etc.). Limited to HTTP REST; no JSON-RPC or custom protocol support.
- **Dynamic `/model/new` API (beta).** Allows adding models at runtime without a config reload.
- **`model_info` metadata.** Stores cost/pricing fields (`input_cost_per_token`, `output_cost_per_token`, etc.). Does not support arbitrary schema fields.
- **Virtual keys, spend tracking, budgets.** Fine-grained usage controls per key/team/project.

---

## Point-by-Point Assessment

### 1. Agent Discovery — Can LiteLLM's model list act as an agent registry?

**Partially, with significant compromises.**

LiteLLM's `/model/new` (beta) endpoint could receive a POST at agent startup, mimicking the self-registration pattern. Each agent could be registered as a "model" with a custom `api_base`. However:

- The model list is designed around the concept of a single model with multiple deployments, not multiple distinct agents each with multiple distinct skills. One corrosion agent has three skills (`analyze_corrosion`, `predict_corrosion_rate`, `assess_coating_integrity`) — you would need either three LiteLLM "models" per agent, or abandon per-skill granularity entirely.
- Heartbeat / liveness tracking (`POST /agents/{id}/heartbeat`) does not exist in LiteLLM. There is no equivalent health-gating mechanism per endpoint.
- Capability search by tag or text (`GET /capabilities/search`) is absent. LiteLLM has no query interface for this.

**Verdict: Structural mismatch.** The registry's agent→skills hierarchy maps poorly onto LiteLLM's model→deployments hierarchy.

### 2. Capability Metadata — Can LiteLLM carry per-skill inputSchema?

**No.**

LiteLLM's `model_info` is explicitly for cost/pricing fields. It has no extension points for arbitrary JSON blobs. Storing an `inputSchema` like the corrosion agent's nested `context` object (with `temperature_c`, `pressure_mpa`, `coolant_chemistry`, etc.) is not supported.

This is the single most critical blocker. The entire dynamic tool creation pipeline in `tool_discovery.py` depends on fetching these schemas at discovery time:

```python
input_schema = create_input_schema_from_skill(skill)  # needs skill["inputSchema"]
return StructuredTool.from_function(..., args_schema=input_schema)
```

Without per-skill `inputSchema`, the LLM cannot know what parameters each tool requires, and the `StructuredTool` wrappers collapse to the generic `DefaultGenericInput` fallback (a plain `extra="allow"` model). This degrades routing quality and eliminates input validation.

**Verdict: Hard blocker.** LiteLLM cannot store or serve the metadata the client-agent requires.

### 3. A2A Protocol Compatibility — Is there a mismatch?

**Yes, fundamental.**

Every specialist agent speaks JSON-RPC 2.0. The client-agent sends:
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "params": {
    "message": { ... },
    "configuration": { "blocking": true },
    "context": { "skillId": "analyze_corrosion", "conversationId": "..." }
  }
}
```

LiteLLM's proxy and router exclusively understand the OpenAI Chat Completions API format (`POST /v1/chat/completions` with `{"model": "...", "messages": [...]}`). The pass-through feature can forward HTTP bodies verbatim, but:

- The request would still be wrapped or intercepted by LiteLLM middleware.
- LiteLLM has no concept of `skillId` routing within a single backend.
- LiteLLM's response unwrapping expects a `{"choices": [{"message": {"content": "..."}}]}` structure. The A2A response envelope (`result.status.message.parts`, `result.artifacts`, `result.history`) would either be returned opaque or cause parse errors.
- The multi-step response extraction logic in `call_a2a_agent()` (200+ lines handling status.message, artifacts, and history fallback chains) would need to be reimplemented as a LiteLLM custom adapter — which still operates within HTTP but would need to handle the A2A envelope on every call.

Even with pass-through, you would be writing a full A2A↔OpenAI protocol adapter and running it inside LiteLLM's plugin system. That is more work than the existing direct `httpx` call.

**Verdict: Requires full protocol translation layer that negates any simplicity gain.**

### 4. Tool/Function Call Routing — Does LiteLLM fit in the tool pipeline?

**No, it is the wrong layer.**

The client-agent's tool routing is:
1. `CapabilityCache` → enumerate skills → build `StructuredTool` list
2. LangGraph agent selects tool by name based on skill description + `inputSchema`
3. `call_a2a_agent()` dispatches the call with validated parameters

LiteLLM sits between an LLM client and an LLM backend. The client-agent is itself the LLM client (using `ChatAnthropic` directly). LiteLLM would add a proxy hop between the client-agent's LLM calls and Anthropic — which is useful for key management or cost tracking, but has nothing to do with specialist agent routing.

LiteLLM's function/tool calling support is about passing `tools=[...]` in a completions request so the LLM can return tool_call responses. This is already handled natively by `ChatAnthropic`. LiteLLM does not orchestrate which HTTP backend to call based on a tool name.

**Verdict: LiteLLM operates at the wrong architectural layer. It proxies LLM API calls; the client-agent's routing problem is dispatching to specialist A2A HTTP services.**

### 5. What Would Actually Change

If you attempted a replacement, the mandatory rewrite surface would be:

| Component | Current behavior | Required change |
|---|---|---|
| `registry/app.py` | FastAPI service storing agent cards with full skill metadata | Remove; replace with LiteLLM proxy config |
| `prometheus_api/agent/base.py` `register_with_registry()` | POSTs full `agent_card_dict` including `inputSchema` to registry | POSTs to LiteLLM `/model/new` — but cannot send `inputSchema` |
| `tool_discovery.py` `get_agent_card()` | Fetches skill metadata from `GET /agents/{id}/card` | No equivalent endpoint in LiteLLM |
| `tool_discovery.py` `create_input_schema_from_skill()` | Builds Pydantic model from `skill["inputSchema"]` | Loses all per-skill schema information |
| `tool_discovery.py` `call_a2a_agent()` | Sends JSON-RPC 2.0 directly via httpx | Needs A2A↔OpenAI adapter or bypass LiteLLM entirely |
| `capability_cache.py` | Caches `AgentCapability` with `input_schema`, `derivation_rules`, `tags` | None of this is retrievable from LiteLLM |
| Planner / routing logic | Uses `usage_notes`, `tags`, `provides`, `derivation_rules` | All lost without schema-bearing registry |

You would not be replacing the registry with LiteLLM. You would be removing the registry, rewriting all metadata storage, rewriting all protocol dispatch, and adding LiteLLM on top to proxy LLM API calls — which is a separate concern.

### 6. Is It Worth It?

**No, not as a registry replacement.**

The concrete benefits LiteLLM would provide:
- **Unified LLM proxy:** One endpoint for `claude-sonnet-4`, `claude-opus`, future model swaps. Virtual API keys.
- **Cost and token tracking:** Per-conversation or per-user spend tracking across Anthropic API calls.
- **Rate limit management:** Automatic retry and fallback if Anthropic rate-limits the client-agent.
- **Model-level load balancing:** Run multiple Anthropic API keys in rotation.

The concrete costs of using it as an agent registry:
- The `inputSchema` metadata that drives dynamic Pydantic model generation and LLM tool call accuracy has no home in LiteLLM. You would need a second store (a database, a static config file, or keep the current registry) anyway.
- Every specialist agent call goes through an extra HTTP hop and a full OpenAI-format translation roundtrip for no benefit (the specialists are not LLMs; they are A2A services).
- The A2A response envelope parsing (`call_a2a_agent`'s 200+ lines) would still need to exist somewhere — either bypassing LiteLLM or implemented as a custom plugin.
- Dynamic self-registration is beta in LiteLLM, not production-hardened, and has no analog for per-skill capability decomposition.

---

## Verdict

**Not a good fit as a registry replacement. Partially applicable as an LLM proxy add-on.**

LiteLLM solves a different problem: normalizing and managing calls to LLM inference APIs. The homemade registry solves agent service discovery with rich per-skill capability metadata. These are distinct concerns.

The homemade registry is also not overbuilt. It is ~220 lines of FastAPI that does exactly what the system needs: store agent cards, serve per-skill metadata, and support capability search. Its main genuine weaknesses are no persistent storage (in-memory only, lost on restart) and no health-based deregistration. Neither weakness is solved by LiteLLM.

---

## Concrete Recommendation

**Keep the registry. Consider LiteLLM independently for LLM proxying.**

### Short-term: Harden the existing registry (high value, low effort)

1. **Add persistence.** Replace the in-memory `dict` with Redis (already in the stack) or SQLite. Agents re-register on startup anyway, so a simple append-log with TTL expiry is sufficient.
2. **Add health-based deregistration.** The heartbeat endpoint already exists (`POST /agents/{id}/heartbeat`). Add a background task that marks agents stale if no heartbeat is received within N seconds, and exclude stale agents from capability enumeration.

### Medium-term: Consider LiteLLM for LLM proxying only (separate concern)

Add LiteLLM in front of the Anthropic API in `client-agent/agent.py` and potentially the specialist agents. Benefits:
- Centralized API key management (one `ANTHROPIC_API_KEY` in LiteLLM, virtual keys per service).
- Cost and token tracking per agent or per conversation.
- Easy model swap (change `claude-sonnet-4-20250514` to `claude-opus-4` in one config file).
- Rate limit retry and fallback across multiple API keys.

This requires changing `ChatAnthropic(model=MODEL_NAME)` to point at `http://litellm-proxy/v1` with `model=claude-sonnet-4-20250514`. It is a two-line change and is fully independent of agent discovery.

### What LiteLLM is NOT suitable for in this system

- Acting as the agent registry
- Routing calls to specialist agents
- Storing `inputSchema` or capability metadata
- Proxying A2A JSON-RPC traffic
