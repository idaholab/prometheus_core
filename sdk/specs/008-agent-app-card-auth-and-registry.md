# 008 — Agent app, card, auth, and registry

status: implemented
sources: README.md, docs/agent/GUIDE.md, docs/agent/QUICK_START.md, docs/ENV_SETUP.md, prometheus_api/agent/base.py, prometheus_api/agent/middleware.py, prometheus_api/agent/registry.py, prometheus_api/agent/debug_routes.py, tests/test_agent.py, tests/test_a2a_payloads.py
depends-on: 009, 012

## Purpose
Let specialist agents become hosted A2A services with minimal boilerplate while preserving agent-card metadata, authentication, health/debug routes, and LiteLLM registry integration.

## Requirements
- REQ-008-01: `PrometheusAgent.registry_url()` MUST return stripped `REGISTRY_URL` or the default `http://litellm:4000`.
- REQ-008-02: `load_agent_card()` MUST load JSON from the configured path, resolving relative paths next to `__main__.__file__` when available.
- REQ-008-03: `load_agent_card()` MUST set the runtime card URL from `EXTERNAL_AGENT_URL` or derive `http://{hostname}:{AGENT_PORT}`.
- REQ-008-04: Loaded raw cards MUST preserve Prometheus-specific skill metadata and workflows while adding A2A-valid defaults such as `defaultInputModes`, `defaultOutputModes`, and skill `tags`.
- REQ-008-05: Workflow files in `AGENT_WORKFLOWS` or the default `workflows` directory next to the card MUST be loaded from JSON/YAML, accept a single object, list, or `{workflows: [...]}`, and append to any card-defined workflows.
- REQ-008-06: Missing workflow directories MUST be ignored; non-directory workflow paths or non-object workflow entries MUST raise `ValueError`. ⚠ untested
- REQ-008-07: `build_app(register_on_startup=...)` MUST load the card, create the executor, configure an A2A request handler, add `/healthz`, `/api/chat`, `/api/agent-card`, `/.well-known/agent.json`, `/.well-known/agent-card.json`, and `/api/artifacts/{conversation_id}` routes, then call `configure_app(app)`.
- REQ-008-08: Agent apps MUST use `RedisTaskStore` by default and `InMemoryTaskStore` only when `PROMETHEUS_TASK_STORE=memory`.
- REQ-008-09: Bearer auth MUST be required by default; if `AGENT_SECRET_REQUIRED=true` and `AGENT_SECRET` is unset, app configuration MUST fail fast with `RuntimeError`.
- REQ-008-10: Bearer auth middleware MUST exempt health and public agent-card endpoints, reject missing/malformed/invalid authorization with JSON-RPC 401 responses, and never log token values.
- REQ-008-11: Registry registration MUST build payloads with the route key derived from the agent-card name and MUST include `static_headers.Authorization` when `AGENT_SECRET` is configured.
- REQ-008-12: Registry registration MUST delete a stale registration with the same agent name before posting a replacement.
- REQ-008-13: Registry retry counts MUST resolve from explicit args or `REGISTRY_MAX_RETRIES`, ignore invalid values without blocking startup, clamp negative values to zero, and use exponential backoff up to `max_delay`.
- REQ-008-14: App lifespan MUST run subclass `lifespan(app)` and start registry registration as a background task when `register_on_startup=True`.
- REQ-008-16: After startup registration, the background task MUST check the registry every `REGISTRY_CHECK_INTERVAL_SECONDS` (default 5; empty means default; 0 disables) and re-register when the agent's entry is missing. A failed check (registry unreachable) MUST be logged and retried on the next tick, never stop the agent, and never be treated as a missing entry.
- REQ-008-15: `/api/chat` MUST accept `{"params": {...}}`, `{"message": {...}}`, or string `message`, execute the standard executor with local task/context IDs, and optionally return serialized events and artifact catalog entries.

## Behavior
- BEH-008-01: GIVEN workflow YAML next to `agent_card.json` WHEN the app serves `/api/agent-card` THEN the workflow metadata appears in the response and the card remains A2A-valid.
- BEH-008-02: GIVEN unset `REGISTRY_URL` and transient registry failures WHEN registration runs THEN retries target `http://litellm:4000` and eventual failure does not stop the agent.
- BEH-008-04: GIVEN a running, registered agent WHEN the registry restarts or is cleared (e.g. `make up` clears it) THEN within one check interval the agent registers again, without restarting.
- BEH-008-03: GIVEN `AGENT_SECRET_REQUIRED=false` WHEN app auth is configured THEN no bearer middleware is added.

## Interfaces
- `PrometheusAgent(agent_name: str = "Agent", agent_card_path: str | None = None)`
- `PrometheusAgent.registry_url() -> str`
- `PrometheusAgent.get_raw_agent_card() -> dict[str, Any]`
- `PrometheusAgent.load_agent_card() -> AgentCard`
- `PrometheusAgent.create_executor() -> PrometheusAgentExecutor`
- `PrometheusAgent.configure_app(app) -> None`
- `PrometheusAgent.lifespan(app) -> AsyncIterator[None]`
- `PrometheusAgent.build_app(register_on_startup: bool = True) -> Starlette`
- `PrometheusAgent.run(host: str = "0.0.0.0", port: int | None = None) -> None`
- `PrometheusAgent.register_with_registry(agent_card: AgentCard, *, max_retries: int | None = None, initial_delay: float = 2.0, max_delay: float = 30.0, backoff_factor: float = 2.0) -> None`
- `PrometheusAgent.register_with_registry_async(...) -> None`
- `BearerTokenMiddleware(app, secret: str | None = None, required: bool = True)`
- `AgentRegistryClient(registry_url: str, *, master_key: str = "", agent_secret: str | None = None, timeout: float = 15.0)`
- `AgentRegistryClient.from_env(registry_url: str) -> AgentRegistryClient`
- `AgentRegistryClient.headers -> dict[str, str]`
- `AgentRegistryClient.build_payload(agent_card: AgentCard, *, raw_agent_card: dict | None = None) -> tuple[str, dict]`
- `AgentRegistryClient.register_once/register_once_async/register_with_retries/register_with_retries_async`
- `add_debug_chat_route(app, *, agent: Any, executor: Any) -> None`

## Constraints
- Registry HTTP and retry behavior belongs in `agent/registry.py`; debug compatibility route logic belongs in `agent/debug_routes.py`.
- Agent registry URL lookups should go through `PrometheusAgent.registry_url()` to keep the default centralized.
- Agent-card public metadata endpoints remain unauthenticated so registries and clients can discover cards.

## Out of scope / Non-goals
- This package does not manage TLS termination, external reverse proxy behavior, or registry service availability.
- `/api/chat` is a compatibility/debug endpoint, not a replacement for A2A `message/send` or `message/stream`.

## Open questions
- Workflow file validation is structural only; semantic workflow validation is outside this package.
- Route behavior for `/api/artifacts/{conversation_id}` has limited direct coverage compared with `/api/chat` and card routes.
