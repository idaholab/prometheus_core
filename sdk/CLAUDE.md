# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`prometheus-api` is a Python 3.12+ package shipping three cooperating components against a DeepLynx storage backend:

1. **`prometheus_api.storage_client`** — Pydantic-typed sync (`StorageClient`) and async (`AsyncStorageClient`) HTTP clients for items, files (incl. chunked uploads), relationships, search, tags, timeseries. Also registers a `deeplynx://` fsspec filesystem (`DeepLynxFileSystem`) via the `fsspec.specs` entry point.
2. **`prometheus_api.agent`** — `PrometheusAgent` base class for A2A-protocol agents (built on `a2a-sdk` + Starlette/uvicorn). Subclasses override `async _execute(params, context, event_queue)` and the base handles agent-card loading, bearer-token auth, registry registration, status/artifact emission, and per-`contextId` state persistence.
3. **`prometheus_api.llm_client`** — provider-agnostic sync (`LLMClient`) and async (`AsyncLLMClient`) chat/embedding clients over LiteLLM. Agent code selects a *semantic flavor* (`default`, `small`, `medium`, `large`, `vision`, `embedding`); deployments map flavors to provider models in the installed YAML profiles under `llm_configs/`. Also owns tool calling (`llm_client/tools.py`), secret redaction, and opt-in MLflow tracing. LLM credentials come only from `LLMConfig`/the environment, never from A2A requests.

`prometheus_api.contract` (package top level, importable with only pydantic — no agent runtime) holds the canonical frontend ↔ client-agent wire contract (`ConversationRequest`, `ConversationResponse`, `ConversationStatus`) — the JSON payload exchanged in A2A text parts. The Prometheus platform's frontend and client-agent must import these models rather than redefining them; change them here and the change propagates to both sides. They are also re-exported from `prometheus_api.agent`.

Two more shared, dependency-light top-level modules (do not copy their logic into consumers):
- `prometheus_api.a2a_stream` — client-side consumption of A2A `message/stream` responses (SSE/NDJSON parsing, heartbeat skipping, status/background callbacks, artifact merge). Used by the platform frontend and client-agent.
- `prometheus_api.redis_utils` — `create_redis_client()`, the single Redis connection recipe (`REDIS_URL`/`REDIS_PASSWORD`, `decode_responses=True`, fail-fast ping, logged `None` on failure). The agent stores (`ArtifactRegistry`, `ContextStateStore`, `RedisTaskStore`) build their connections through it.

Artifact-to-file resolution (cache layout, allowed local roots, fsspec downloads, inline materialization) lives in `prometheus_api.agent.artifact_resolver.ArtifactResolver`; `PrometheusAgent.get_artifact_file_path` is a thin delegate bound to the agent's registry.

The agent component depends on the storage client (used internally for `ContextStateStore` and artifact persistence). The A2A server stack (`a2a-sdk[http-server]`, `starlette`, `uvicorn`) is part of the base `dependencies` — there is no `[agent]` extra.

## Common Commands

Use `uv run` (the project is uv-managed; see `uv.lock`). The Makefile wraps the common targets:

```bash
make lint             # ruff check .
make format           # ruff format --check .
make typecheck        # mypy prometheus_api/
make test             # alias for `test-unit` (skips integration)
make test-unit        # pytest -m "not integration" --cov (enforces the coverage floor)
make test-integration # pytest -m integration (requires .env)
make test-all         # pytest --cov (every marker, including integration)
make fix              # ruff check --fix . && ruff format .
make check            # lint + format + typecheck
make hooks            # install pre-commit + pre-push hooks
make test-install     # build wheel via `uv build`, install in clean venv, smoke-test imports
```

`make test` is an alias for `make test-unit` — it does **not** run integration tests by default. Use `make test-all` to include them.

### Targeted test runs

```bash
uv run pytest -m "not integration"                          # unit only (no .env required)
uv run pytest -m integration                                # integration (requires .env w/ DeepLynx creds)
uv run pytest tests/test_agent.py::TestPrometheusAgentExecutor::test_execute_calls_enqueue_event
uv run pytest --cov --cov-report=html
```

`make test`, `make test-all`, and CI fail if coverage drops below `fail_under` in `[tool.coverage.report]`, the lowest total across the supported Python versions. Raise it as coverage improves; never lower it. Running a subset of tests with `--cov` will fail the floor, so leave `--cov` off for targeted runs.

`pyproject.toml` sets `asyncio_mode = "auto"`, so async tests do **not** need `@pytest.mark.asyncio`. Tests in `test_integration.py` are auto-marked `integration` by `tests/conftest.py`.

### Versioning & container builds

```bash
make version                                         # prints version from pyproject.toml
make bump-patch | bump-minor | bump-major            # rewrites pyproject.toml
make build-image IMAGE_TAG=<tag>                     # local amd64+arm64 builds
make build-local [LOCAL_IMAGE=<name:tag>]           # host-arch build into the local store (default prometheus_api:local; used by platform LOCAL_SDK=true)
make build-push IMAGE_REPO=<repo> [PUSH_LATEST=true] # multi-arch buildx push (default repo: containers.github.inl.gov/...)
```

Default `IMAGE_TAG` is `git rev-parse --short HEAD`.

## Architecture Notes

### StorageClient layout
`StorageClient` (sync) and `AsyncStorageClient` (async) are thin lifecycle managers; all real work lives in **resource handlers** lazy-loaded as properties (`client.items`, `.files`, `.relationships`, `.search`, `.tags`, `.timeseries`). The sync and async resource trees are kept as parallel modules — `storage_client/resources/` and `storage_client/async_resources/` — and must be edited together when adding/changing endpoints. Models (`storage_client/models/`) are shared between both.

`ConnectionConfig` is a frozen Pydantic model that requires either (`api_key` + `api_secret`) **or** `jwt_token`, never both. It validates at construction. Use `ConnectionConfig.from_env()` to load from `DEEPLYNX_*` env vars (see `.env.example`). The default `base_url` is `https://deeplynx.inl.gov/api/v1`.

`DeepLynxFileSystem` (fsspec) maps `deeplynx://` URIs to DeepLynx file records, storing object keys in record metadata rather than building a separate index. It's wired up automatically via the `[project.entry-points."fsspec.specs"]` declaration in `pyproject.toml`.

### PrometheusAgent contract
Subclasses override `async _execute(self, params, context: RequestContext, event_queue: EventQueue) -> dict`. The base class emits the returned dict as the terminal `TaskStatusUpdateEvent`.

Before `_execute`, the standard executor uses a just-in-time `deeplynx` credential to create a mandatory execution item. It records the agent, task, context, verified user, and effective parameters. Parameters are recursively redacted and stored as JSON in the scalar `parameters_json` property to avoid DeepLynx's properties-depth limit; decode them with `json.loads(...)`. If record creation fails, the task fails before subclass work begins.

During `_execute`, `self.execution_record_id` provides the request-scoped item ID and returns `None` outside that invocation. The verified identity replaces any caller-provided `params["user_id"]`. Deployments require valid DeepLynx credentials and either `DEEPLYNX_DATA_SOURCE_ID` or a project default data source.

Inside `_execute`, use the helpers rather than constructing A2A events manually:

- `send_status_update(...)` — transient progress
- `send_artifact_reference(...)` — URI-backed file artifact (e.g. `deeplynx://...`)
- `send_json_artifact(..., catalog_artifact=True)` — reusable inline JSON artifact
- `send_conversation_message(...)` — durable chat-visible message
- `send_input_required(missing_inputs=[MissingInput(...)])` — INPUT_REQUIRED with canonical payload
- `load_context_state(...)` / `save_context_state(...)` — per-`contextId` resumable state via `ContextStateStore`

The agent module also re-exports common A2A types (`RequestContext`, `EventQueue`, `TaskState`, `TaskStatus`, `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`, `Artifact`, `TextPart`) from `prometheus_api.agent`, so subclasses normally don't need to import directly from `a2a.*`.

Streaming (`message/stream`) is opt-in: set `"capabilities": {"streaming": true}` in the agent's `agent_card.json`. Bearer-token auth via `BearerTokenMiddleware` is enforced when `AGENT_SECRET` is set; setting `AGENT_SECRET_REQUIRED=false` is a development-only escape hatch.

Artifact metadata produced by helpers always carries `conversation_id`, `producer_agent_id` (normalized: lowercased, spaces → hyphens), and `created_at` (UTC ISO). When adding new helper paths that emit artifacts, route through `_build_artifact_metadata` to preserve this envelope.

### LLM client layout

`LLMClient` (sync) and `AsyncLLMClient` (async) are **two fully independent implementations** in `llm_client/client.py`. Spec 006 requires they stay aligned for alias selection, fallback behavior, request payloads, response fields, and logging — so shared behavior belongs on `_ClientMixin`, not duplicated in both. `ChatResponse` is built only through `_ClientMixin._build_chat_response`; do not construct it inline (there are four call sites and they must not drift). `tests/test_llm_client.py::test_sync_and_async_chat_signatures_match` guards the signatures.

Two dispatch paths hide behind one API. When the selected YAML has a reachable `proxy_url`, chat POSTs to `{proxy_url}/v1/chat/completions` and the response is a **plain dict**. Otherwise (or when the proxy raises a request-level error) it calls the LiteLLM SDK and the response is a **`ModelResponse` object**. Every response accessor must therefore tolerate both shapes — use `_get` from `llm_client/tools.py` rather than subscripting.

Flavors are deployment configuration and live in YAML; per-call capabilities live in `chat()` kwargs. **Tool calling is per-call, not a flavor** — do not add a seventh alias. `chat()` takes keyword-only `tools` and `tool_choice`; `ToolDefinition` values are converted to OpenAI function schemas while plain mapping schemas pass through untouched, so hand-built tool dicts keep a byte-identical payload. Read tool calls off `ChatResponse.tool_calls` / `.finish_reason` (a pure tool-call turn has `text == ""`), replay a turn with `assistant_message(...)` + `tool_result_message(...)`, and gate strictness with `require_tool_calls(...)`. `finish_reason` is observability, **not** a loop terminator — some providers return `"stop"` alongside tool calls, so a multi-turn loop terminates on `not response.tool_calls` and must bound its turns (spec 014 Constraints). Parsing is deliberately lenient so `chat()` never raises on model-authored output. `tools=[]` is omitted from the payload, and `tool_choice` without at least one tool raises `LLMToolCallError` before dispatch. `tool_result_message` substitutes `"(empty result)"` for blank results so replay passes normalization.

`llm_client/tools.py` MUST NOT import `llm_client/client.py` at runtime (the client imports it, so the reverse would cycle); use a `TYPE_CHECKING` guard. New tool errors subclass `LLMClientError`, not `LLMAliasError` — note those two live in unrelated exception trees (`RuntimeError` vs `ValueError`).

Streaming is not supported: a truthy `stream` raises `LLMClientError` before any backend is contacted.

### Tests
- `test_*.py` files at the top level of `tests/` are unit tests.
- `test_integration.py` requires a `.env` with valid `DEEPLYNX_KEY`/`SECRET`/`ORG_ID`/`PROJECT_ID` and optionally `DEEPLYNX_DATA_SOURCE_ID` (without it, code that creates records will hit "DataSource with id 0 not found").
- `make test-install` builds a wheel, installs it into a clean venv, and imports every package under `prometheus_api/` from it (`python -I`, so the source tree can't stand in). It fails if a package is missing from `[tool.setuptools] packages`. CI runs it as the `sdk: install` job. Use this rather than ad-hoc shell scripts.

### Specs (spec-driven development)

`specs/` is the SDD contract, with `specs/000-index.md` as the entry point and one numbered file per capability. Requirement and behavior bullets use front-loaded stable IDs (`REQ-NNN-XX:`, `BEH-NNN-XX:`). When you change public behavior, update the owning spec in the same change: amend requirements in place, never renumber or reuse IDs, and mark inferred-but-untested requirements `⚠ untested`. Authoring rules are in `docs/SDD_SPEC_AUTHORING.md`; test traceability rules are in `docs/SDD_TESTING_STANDARD.md`. LLM specs are 005 (config/aliases), 006 (chat/embeddings), 007 (security/tracing), and 014 (tool calling).

## Conventions

- **Python ≥ 3.12** is hard-required (`requires-python` and `target-version` in ruff/mypy).
- Line length is **100** (ruff). `examples/` is excluded from ruff and mypy.
- Use the Makefile targets rather than running `pytest`/`ruff`/`mypy` directly, so dev tooling stays in sync with `uv.lock`.
- Container images target both `linux/amd64` and `linux/arm64`; the Dockerfile installs the base package and the CA certificates in [common/certs](../common/certs/README.md).
- When you make a change, ensure that this file gets updated to reflect those changes. We do not want this file getting out of date so it is important that when you make changes, they are accurately documented in this file.
