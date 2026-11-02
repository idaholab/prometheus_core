# Development Guide

Architecture, conventions, and the day-to-day commands for working on `prometheus-api`. For installation see [INSTALL.md](INSTALL.md); for environment variables and quick-start examples see [README.md](README.md).

## Project overview

`prometheus-api` is a Python 3.12+ package shipping two cooperating components against a DeepLynx storage backend:

1. **`prometheus_api.storage_client`** — Pydantic-typed sync (`StorageClient`) and async (`AsyncStorageClient`) HTTP clients for items, files (incl. chunked uploads), relationships, search, tags, timeseries. Also registers a `deeplynx://` fsspec filesystem (`DeepLynxFileSystem`) via the `fsspec.specs` entry point.
2. **`prometheus_api.agent`** — `PrometheusAgent` base class for A2A-protocol agents (built on `a2a-sdk` + Starlette/uvicorn). Subclasses override `async _execute(params, context, event_queue)` and the base handles agent-card loading, bearer-token auth, registry registration, status/artifact emission, and per-`contextId` state persistence.

The agent component depends on the storage client (used internally for `ContextStateStore` and artifact persistence). The A2A server stack is part of the base dependencies — there is no `[agent]` extra.

## Common commands

The project is `uv`-managed (see `uv.lock`). The Makefile wraps the common targets so dev tooling stays in sync with the lockfile:

```bash
make lint        # ruff check .
make format      # ruff format --check .
make typecheck   # mypy prometheus_api/
make test        # unit tests only (excludes integration), with the coverage floor
make test-integration # DeepLynx integration tests (requires .env)
make test-all    # all tests, including integration
make fix         # ruff check --fix . && ruff format .
make check       # lint + format + typecheck
make hooks       # install pre-commit and pre-push hooks
make test-install # build wheel, install in clean venv, smoke-test imports
```

### Targeted test runs

```bash
make test                                                   # unit only (no .env required)
uv run pytest -m "not integration"                            # unit only (no .env required)
make test-integration                                        # integration (requires .env w/ DeepLynx creds)
uv run pytest tests/test_agent.py::TestPrometheusAgentExecutor::test_execute_calls_enqueue_event
uv run pytest --cov --cov-report=html
```

`make test`, `make test-all`, and CI fail if coverage drops below `fail_under` in `[tool.coverage.report]`, the lowest total across the supported Python versions. Raise it as coverage improves; never lower it. Running a subset of tests with `--cov` will fail the floor, so leave `--cov` off for targeted runs.

`pyproject.toml` sets `asyncio_mode = "auto"`, so async tests do **not** need `@pytest.mark.asyncio`. Tests in `test_integration.py` are auto-marked `integration` by `tests/conftest.py`.

### Local hooks

Install hooks once per checkout:

```bash
make hooks
```

The pre-commit hook runs ruff format and lint checks. The pre-push hook runs mypy and unit tests. Run all configured hooks manually with:

```bash
uv run pre-commit run --all-files
uv run pre-commit run --all-files --hook-stage pre-push
```

### Versioning & container builds

```bash
make version                                       # prints version (uv version --short)
make bump-patch | bump-minor | bump-major          # uv version --bump <part>
make build-image IMAGE_TAG=<tag>                   # local amd64+arm64 builds
make build-local [LOCAL_IMAGE=<name:tag>]           # host-arch build into the local store (default prometheus_api:local; used by platform LOCAL_SDK=true)
```

Default `IMAGE_TAG` is `git rev-parse --short HEAD`.

## Architecture notes

### StorageClient layout
`StorageClient` (sync) and `AsyncStorageClient` (async) are thin lifecycle managers; all real work lives in **resource handlers** lazy-loaded as properties (`client.items`, `.files`, `.relationships`, `.search`, `.tags`, `.timeseries`). The sync and async resource trees are kept as parallel modules — `storage_client/resources/` and `storage_client/async_resources/` — and must be edited together when adding/changing endpoints. Models (`storage_client/models/`) are shared between both.

`ConnectionConfig` is a frozen Pydantic model that requires either (`api_key` + `api_secret`) **or** `jwt_token`, never both. It validates at construction. Use `ConnectionConfig.from_env()` to load from `DEEPLYNX_*` env vars (see `.env.example`). The default `base_url` is `https://deeplynx.inl.gov/api/v1`.

`DeepLynxFileSystem` (fsspec) maps `deeplynx://` URIs to DeepLynx file records, storing object keys in record metadata rather than building a separate index. It's wired up automatically via the `[project.entry-points."fsspec.specs"]` declaration in `pyproject.toml`.

### PrometheusAgent contract
Subclasses override `async _execute(self, params, context: RequestContext, event_queue: EventQueue) -> dict`. The returned dict becomes the final task status — the base class emits the terminal `TaskStatusUpdateEvent` automatically. Inside `_execute`, use the helpers rather than constructing A2A events manually:

- `send_status_update(...)` — transient progress
- `send_artifact_reference(...)` — URI-backed file artifact (e.g. `deeplynx://...`)
- `send_json_artifact(..., catalog_artifact=True)` — reusable inline JSON artifact
- `send_conversation_message(...)` — durable chat-visible message
- `send_input_required(missing_inputs=[MissingInput(...)])` — INPUT_REQUIRED with canonical payload
- `load_context_state(...)` / `save_context_state(...)` — per-`contextId` resumable state via `ContextStateStore`

Streaming (`message/stream`) is opt-in: set `"capabilities": {"streaming": true}` in the agent's `agent_card.json`. Bearer-token auth via `BearerTokenMiddleware` is enforced when `AGENT_SECRET` is set; setting `AGENT_SECRET_REQUIRED=false` is a development-only escape hatch.

Artifact metadata produced by helpers always carries `conversation_id`, `producer_agent_id` (normalized: lowercased, spaces → hyphens), and `created_at` (UTC ISO). When adding new helper paths that emit artifacts, route through `_build_artifact_metadata` to preserve this envelope.

### Tests
- `test_*.py` files at the top level of `tests/` are unit tests.
- `test_integration.py` requires a `.env` with valid `DEEPLYNX_KEY`/`SECRET`/`ORG_ID`/`PROJECT_ID` and optionally `DEEPLYNX_DATA_SOURCE_ID` (without it, code that creates records will hit "DataSource with id 0 not found").
- `tests/test_sync_async_parity.py` keeps sync and async resource handlers aligned for endpoint payloads and response parsing.
- `make test-install` builds a wheel, installs it into a clean venv, and imports every package under `prometheus_api/` from it. CI runs it as the `sdk: install` job.
- `examples/verify_connection.py` is a manual DeepLynx smoke test; it is intentionally outside pytest discovery.

## Conventions

- **Python ≥ 3.12** is hard-required (`requires-python` and `target-version` in ruff/mypy).
- Line length is **100** (ruff). `examples/` is excluded from ruff and mypy.
- Use the Makefile targets rather than running `pytest`/`ruff`/`mypy` directly, so dev tooling stays in sync with `uv.lock`.
- Container images target both `linux/amd64` and `linux/arm64`; the Dockerfile installs the base package and the CA certificates in [common/certs](../common/certs/README.md).
