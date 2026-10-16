# Prometheus API A2A Routing Refactor Plan

> **See also** [`hierarchical-agents.md`](./hierarchical-agents.md), which bridges this plan with
> [`background-tasks.md`](./background-tasks.md): the shared router must also become the **Task Graph writer**
> (move `task_tracking` into the base class), so distributed delegations get correct node parentage. That note
> resolves the seam between the two plans and answers the deep-hierarchy questions (ownership, waiting, context).

## Goal

Move specialist-agent discovery, routing, and invocation out of the client-agent and into `prometheus_api`, so any agent built on `PrometheusAgent` can call other agents through a shared, policy-enforced A2A client layer.

This should preserve the current external architecture:

- frontend talks to client-agent
- agent-to-agent traffic goes through LiteLLM as the authoritative proxy
- specialist agents do not bypass proxy policy by directly calling each other

At the same time, it should enable:

- specialist-to-specialist delegation
- shared streaming and blocking call handling
- shared auth and downstream header behavior
- shared allowlist enforcement
- loop detection and hop limits

## Current state

Today, routing and invocation logic is concentrated in the client-agent:

- discovery and agent-card fetch: [agents/client-agent/tool_discovery.py](../../agents/client-agent/tool_discovery.py)
- capability cache: [agents/client-agent/capability_cache.py](../../agents/client-agent/capability_cache.py)
- orchestration-time skill invocation: [agents/client-agent/agent.py](../../agents/client-agent/agent.py#L1088)

This creates three problems:

1. Only the client-agent knows how to discover and call specialists.
2. Specialist agents cannot safely delegate to other specialists.
3. Transport, auth, streaming, and response normalization are duplicated at the wrong layer.

## Target architecture

Introduce a shared `prometheus_api` agent-routing subsystem that provides:

1. Registry-backed capability discovery
2. Agent-card loading and caching
3. Policy-aware downstream routing through LiteLLM
4. Shared A2A request building and response normalization
5. Shared streaming support for SSE and NDJSON
6. Shared auth injection for downstream specialist calls
7. Shared delegation policy enforcement
8. Shared loop detection and hop accounting

The client-agent should become one consumer of this subsystem, not the owner of it.

## Design principles

1. Keep the proxy boundary explicit.
   All agent-to-agent traffic should continue to flow through LiteLLM.

2. Centralize wire-level A2A behavior.
   Request envelopes, stream parsing, error mapping, and artifact normalization should live in one place.

3. Centralize policy enforcement.
   Agent allowlists, hop limits, and loop detection should be enforced in shared code, not ad hoc inside each agent.

4. Keep agent business logic thin.
   Specialist agents should call a high-level SDK method, not hand-build JSON-RPC.

5. Separate planning from transport.
   Discovery and capability metadata should be usable independently from low-level invocation.

## Proposed module split in `prometheus_api`

The exact file names can vary, but the responsibilities should split roughly like this:

### `prometheus_api/agent/discovery.py`

- list registered agents from the registry or LiteLLM-backed directory
- fetch full agent cards
- normalize card metadata
- expose cacheable capability records

### `prometheus_api/agent/capabilities.py`

- `AgentCapability` model
- capability indexing and refresh logic
- filtering by tags, skill id, or agent id

### `prometheus_api/agent/a2a_client.py`

- build native A2A requests
- invoke `message/send` and `message/stream`
- parse blocking responses
- parse streamed SSE and NDJSON responses
- normalize artifacts and final payloads
- map transport failures to a Prometheus-specific error taxonomy

### `prometheus_api/agent/routing_policy.py`

- per-agent allowlist rules
- optional denylist rules
- max hop count
- loop detection rules
- proxy-only routing requirements

### `prometheus_api/agent/delegation_context.py`

- call-chain metadata propagation
- request lineage
- caller identity
- visited-agent tracking
- remaining hop budget

### `prometheus_api/agent/router.py`

- high-level orchestration-facing entry point
- choose target agent/skill
- enforce policy
- construct downstream call
- attach delegation headers/metadata
- return normalized result

### `prometheus_api/agent/errors.py`

- `AgentRoutingError`
- `AgentNotAllowedError`
- `AgentLoopDetectedError`
- `AgentHopLimitExceededError`
- `AgentUnavailableError`
- `AgentUnauthorizedError`
- `AgentProtocolError`
- `AgentTimeoutError`

## Public SDK surface

Add a small public interface on `PrometheusAgent` or adjacent helper objects.

Example shape:

```python
result = await self.agent_router.invoke_skill(
    agent_id="artifact-debug-agent",
    skill_id="create_svg_artifact",
    params={"word": "secure", "color": "green"},
    conversation_id=conversation_id,
)
```

And optionally:

```python
capabilities = await self.agent_router.list_capabilities()
capability = await self.agent_router.get_capability("create_svg_artifact")
```

The important constraint is that agents should not need to know:

- LiteLLM URL details
- JSON-RPC envelope details
- stream content-type differences
- downstream auth header details

## Configuration model

Add shared config fields in `prometheus_api`:

- `REGISTRY_URL`
- `LITELLM_MASTER_KEY`
- `AGENT_ID` or equivalent local identity
- `AGENT_ROUTING_ENABLED=true`
- `AGENT_DELEGATION_ALLOWLIST`
- `AGENT_DELEGATION_MAX_HOPS`
- `AGENT_DELEGATION_ALLOW_SELF=false`
- `AGENT_DELEGATION_STRICT_PROXY=true`

Recommended allowlist format:

```env
AGENT_DELEGATION_ALLOWLIST=artifact-debug-agent,data-agent,osti-research-agent
AGENT_DELEGATION_MAX_HOPS=4
```

If more structure is needed later, move to JSON:

```json
{
  "allowed_agents": ["data-agent", "artifact-debug-agent"],
  "allowed_skills": {
    "data-agent": ["search_materials", "get_material_record"]
  },
  "max_hops": 4
}
```

## Delegation context and loop detection

Every downstream A2A call should carry a delegation context. This should not replace the native A2A message body; it should be attached in a consistent metadata location.

Minimum fields:

- `origin_agent_id`
- `caller_agent_id`
- `conversation_id`
- `delegation_id`
- `hop_count`
- `visited_agents`
- `visited_skills`

Loop detection rules:

1. Reject if `hop_count > max_hops`.
2. Reject if the next target agent already appears in `visited_agents` and no explicit reentry policy exists.
3. Optionally reject repeated `(agent_id, skill_id)` tuples within one delegation chain.
4. Log the full delegation path on rejection.

Initial implementation should be simple:

- hop-count based hard stop
- repeated-agent detection

Do not start with graph-theoretic complexity. The first goal is to prevent obvious cycles like:

- client-agent -> synthesis-agent -> client-agent
- client-agent -> data-agent -> artifact-debug-agent -> data-agent

## Auth model

This refactor is a good place to fix the current auth ambiguity.

### Required trust boundary

1. Caller authenticates to LiteLLM.
2. LiteLLM authenticates to downstream agents.
3. Downstream agents trust LiteLLM's downstream credential, not the original inbound caller token.

### Required SDK behavior

The shared `prometheus_api` router should:

- always call LiteLLM, not specialist direct URLs
- authenticate to LiteLLM with the configured LiteLLM credential
- carry stable caller identity and delegation metadata for auditability

### Required proxy behavior

LiteLLM needs an explicit downstream auth mechanism for A2A calls. That can be:

- one shared internal bearer token, or
- per-agent downstream token config

The shared router should be built assuming that outbound downstream auth is proxy-owned, not caller-header-forwarded.

## Streaming design

The shared router must support both:

- blocking A2A calls
- streaming A2A calls

And it must tolerate the proxy transport variants already observed:

- `text/event-stream`
- `application/x-ndjson`

Selection rule:

1. If target agent advertises `capabilities.streaming: true`, prefer streaming.
2. Otherwise use blocking `message/send`.
3. If the proxy rejects streaming for a given route, fail clearly or fall back based on explicit policy.

Do not hide transport mismatch errors silently. They should be visible as routing errors with agent id, skill id, and content type.

## Migration plan

### Phase 1: Extract pure transport code

Move these responsibilities from client-agent into `prometheus_api`:

- request envelope creation
- blocking call logic
- streaming call logic
- response normalization
- artifact normalization
- transport error mapping

Client-agent should switch to the shared transport layer without changing behavior.

Success criteria:

- no functional change for client-agent
- client-agent no longer owns `call_a2a_agent()`

### Phase 2: Extract discovery and capability cache

Move these into `prometheus_api`:

- `discover_agents()`
- `get_agent_card()`
- `CapabilityCache`
- `AgentCapability`

Client-agent should consume the shared cache and shared discovery API.

Success criteria:

- one capability model for all agents
- one discovery implementation for all agents

### Phase 3: Add router and policy layer

Introduce the high-level router API:

- `invoke_skill()`
- `get_capability()`
- `list_capabilities()`

Add:

- allowlist enforcement
- hop limit enforcement
- visited-agent loop detection

Success criteria:

- client-agent uses router instead of transport primitives
- specialist agents can opt into the same router

### Phase 4: Add specialist-agent delegation support

Expose router access on `PrometheusAgent` instances.

Example:

- data-agent can call artifact-debug-agent
- synthesis-agent can call data-agent

Initially keep this off by default behind config:

- `AGENT_ROUTING_ENABLED=false` unless explicitly enabled

Success criteria:

- at least one specialist agent uses SDK-level delegation
- allowlist rules are enforced

### Phase 5: Add observability and audit trail

Add structured logs for:

- caller agent
- target agent
- target skill
- conversation id
- delegation id
- hop count
- allowlist decision
- loop rejection decision

If available, also emit this into tracing.

Success criteria:

- every delegated call is traceable
- loop rejections are diagnosable from logs alone

### Phase 6: Remove client-agent-specific routing code

After the shared router is proven:

- delete or heavily thin `agents/client-agent/tool_discovery.py`
- delete client-agent-local capability cache implementation
- keep only client-agent-specific planning logic

Success criteria:

- client-agent contains planning/orchestration code, not A2A transport infrastructure

## Compatibility strategy

This should be done as a compatibility-preserving refactor, not a flag day.

Recommended rollout:

1. Introduce shared code in `prometheus_api`.
2. Keep existing client-agent functions as wrappers around the shared code.
3. Migrate call sites one layer at a time.
4. Only delete old wrappers after tests and real traffic confirm stability.

This reduces risk and keeps blame localized during rollout.

## Testing strategy

### Unit tests

Add shared tests in `prometheus_api` for:

- blocking response normalization
- streamed SSE response parsing
- streamed NDJSON response parsing
- artifact normalization
- input-required propagation
- downstream 401 mapping
- downstream timeout mapping
- unsupported content-type handling
- allowlist reject behavior
- hop limit reject behavior
- loop detection

### Integration tests

Add docker-compose or service-level tests for:

1. client-agent -> specialist through LiteLLM
2. specialist -> specialist through LiteLLM
3. streaming specialist through LiteLLM
4. auth-enforced downstream specialist
5. allowlist denial
6. loop rejection

### Regression tests

Keep regression coverage for the issues already observed:

- proxy stream route shape mismatch
- NDJSON vs SSE mismatch
- missing downstream auth header
- capability-advertised streaming selection

## Open decisions

These should be resolved before Phase 4:

1. Registry source of truth
   Decide whether the shared router discovers specialists from the existing registry, from LiteLLM, or from a hybrid abstraction.

2. Downstream auth ownership
   Decide whether LiteLLM supports per-agent downstream tokens or a single internal token.

3. Delegation metadata location
   Decide whether delegation context lives in A2A message parts, context metadata, or a Prometheus-specific header set.

4. Fallback behavior
   Decide whether a streaming transport mismatch should:
   - fail hard
   - fall back to blocking
   - be configurable per environment

5. Self-call policy
   Decide whether any agent may deliberately call itself for sub-skills. Default should be no.

## Recommended implementation order

1. Extract transport code into `prometheus_api`.
2. Extract discovery and capability cache.
3. Introduce shared router interface.
4. Migrate client-agent to shared router.
5. Add delegation context and allowlist enforcement.
6. Add hop limits and loop detection.
7. Enable one specialist agent to delegate.
8. Expand usage after logs and tests are stable.

## Expected outcome

After this refactor:

- `prometheus_api` owns A2A routing behavior
- the client-agent owns planning and orchestration only
- specialist agents can safely delegate to approved peers
- LiteLLM remains the authoritative proxy
- loop prevention and auth policy are enforced in one place
- streaming support is shared instead of reimplemented per caller

## Note on repository context

The `prometheus_api` package source is not present in this checkout, so the module layout above is a target design rather than a patch against visible local files. The plan is anchored to the current client-agent implementation and the existing docs that describe `PrometheusAgent` as the shared base layer.
