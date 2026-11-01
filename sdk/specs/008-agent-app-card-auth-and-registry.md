# 008 — Agent app, card, auth, and registry

status: implemented
sources: README.md, docs/agent/GUIDE.md, docs/agent/QUICK_START.md, docs/ENV_SETUP.md, prometheus_api/agent/base.py, prometheus_api/agent/middleware.py, prometheus_api/agent/registry.py, prometheus_api/agent/debug_routes.py, tests/test_agent.py, tests/test_a2a_payloads.py, tests/test_registry_keepalive.py
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
- REQ-008-12: retired. Registration no longer deletes a same-name entry before every post: the platform backend keys entries by agent name, so a POST replaces it, and a delete first left a window in which the agent was not listed. The delete now happens only when the registry refuses the name (see REQ-008-17).
- REQ-008-13: Registry retry counts MUST resolve from explicit args or `REGISTRY_MAX_RETRIES`, ignore invalid values without blocking startup, clamp negative values to zero, and use exponential backoff up to `max_delay`.
- REQ-008-14: App lifespan MUST run subclass `lifespan(app)` and, when `register_on_startup=True`, start `keep_registered_async` as a background task: registration (`register_with_registry_async`), then the registry checks of REQ-008-16.
- REQ-008-15: `/api/chat` MUST accept `{"params": {...}}`, `{"message": {...}}`, or string `message`, execute the standard executor with local task/context IDs, and optionally return serialized events and artifact catalog entries.
- REQ-008-16: After startup registration, the background task MUST check the registry every `REGISTRY_CHECK_INTERVAL_SECONDS` and re-register when no entry has the agent's name. The interval is 5 s by default (unset or empty means the default), 0 disables the checks, a negative or non-finite value MUST warn and use the default, and a positive value below 0.1 s MUST warn and use 0.1 s. The checks MUST also run when startup registration gave up, so the agent joins a registry that comes up later. A failed check (registry unreachable, or a listing that is neither a list nor one wrapped in `data` / `agents`) MUST be logged and retried on the next tick, never stop the agent, and never be treated as a missing entry. The first failed check MUST be logged at WARNING and repeats at DEBUG until a check succeeds, which MUST be logged at INFO, since `registry_url()` always has a value and an agent without a registry would otherwise warn on every check. The checks MUST NOT run for an agent that overrides `register_with_registry_async`, which owns its registration; the SDK MUST log a WARNING saying so. `AgentRegistryClient.register_and_keep_registered_async` MUST let such an override register with the startup retry policy and then run the checks, returning after registration when the interval is 0.
- REQ-008-17: Registration MUST post the payload without deleting an existing entry first. Only when the registry answers 400 or 409 with a body saying the agent already exists (LiteLLM's `POST /v1/agents` does; the platform backend overwrites) MUST it list the entries, delete the one with the agent's name by its `agent_id`, and post again.
- REQ-008-18: Registry log lines MUST NOT contain credentials: a failure is logged as the exception type plus the HTTP status for an HTTP error (never the exception text, which holds the request URL), and the registry URL is logged without userinfo. The SDK MUST NOT log httpx's per-request INFO line for its own registry requests, and MUST leave other httpx logging unchanged.

## Behavior
- BEH-008-01: GIVEN workflow YAML next to `agent_card.json` WHEN the app serves `/api/agent-card` THEN the workflow metadata appears in the response and the card remains A2A-valid.
- BEH-008-02: GIVEN unset `REGISTRY_URL` and transient registry failures WHEN registration runs THEN retries target `http://litellm:4000` and eventual failure does not stop the agent.
- BEH-008-03: GIVEN `AGENT_SECRET_REQUIRED=false` WHEN app auth is configured THEN no bearer middleware is added.
- BEH-008-04: GIVEN a running, registered agent WHEN its registry entry disappears (the registry was cleared or flushed, e.g. `clear-agent-registry`) THEN within about one check interval the agent registers again, without restarting. Platform `make up`/`restart` recreate the in-tree agents anyway; this matters for agents composed separately (such as a template agent) and for agents whose startup registration gave up.
- BEH-008-05: GIVEN an agent that overrides `register_with_registry_async` (for example to opt out, or calling `super()`) WHEN the registry no longer lists it THEN the SDK does not register it.
- BEH-008-06: GIVEN a LiteLLM registry that already lists the agent's name WHEN the agent registers THEN it deletes that entry by `agent_id` and posts again, once; GIVEN the platform backend THEN it only posts.

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
- `PrometheusAgent.registry_check_interval() -> float`
- `PrometheusAgent.keep_registered_async(agent_card: AgentCard) -> None`
- `BearerTokenMiddleware(app, secret: str | None = None, required: bool = True)`
- `AgentRegistryClient(registry_url: str, *, master_key: str = "", agent_secret: str | None = None, timeout: float = 15.0)`
- `AgentRegistryClient.from_env(registry_url: str) -> AgentRegistryClient`
- `AgentRegistryClient.headers -> dict[str, str]`
- `AgentRegistryClient.build_payload(agent_card: AgentCard, *, raw_agent_card: dict | None = None) -> tuple[str, dict]`
- `AgentRegistryClient.register_once/register_once_async/register_with_retries/register_with_retries_async`
- `AgentRegistryClient.resolve_check_interval(raw_value: str | None = None) -> float`
- `AgentRegistryClient.is_registered_async(agent_card: AgentCard) -> bool`
- `AgentRegistryClient.keep_registered_async(agent_card: AgentCard, *, raw_agent_card: dict | None = None, interval: float = 5.0) -> None`
- `AgentRegistryClient.register_and_keep_registered_async(agent_card: AgentCard, *, raw_agent_card: dict | None = None, interval: float = 5.0, max_retries: int | None = None) -> None`
- `AgentRegistryClient.safe_registry_url -> str`
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
