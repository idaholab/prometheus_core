# Repository Guidelines

## Project Structure & Module Organization

`prometheus_api/` contains the package source. `storage_client/` implements the DeepLynx sync and async clients, resource handlers, shared Pydantic models, filesystem integration, and utilities. `agent/` contains A2A agent base classes, middleware, artifact helpers, status event helpers, registry registration helpers, debug route helpers, and context state handling. `llm_client/` contains provider-agnostic LiteLLM sync and async chat/embedding clients, config parsing, input normalization, tool-calling primitives (`tools.py`), optional MLflow chat tracing, response models, and secret redaction. `llm_configs/` contains the installed registry and provider YAML profiles; every provider profile must keep the `default`, `small`, `medium`, `large`, `vision`, and `embedding` flavor contract. Keep sync and async storage resources aligned when changing endpoint behavior.

`specs/` contains the spec-driven-development contract for implemented capabilities, with `specs/000-index.md` as the entry point and one numbered file per capability. Requirement and behavior bullets use front-loaded IDs such as `REQ-001-01:` and `BEH-001-01:`. `docs/agent/LLM_CLIENT_MIGRATION.md` guides people and AI coding assistants through replacing vendor-specific LLM utilities with `llm_client`. `llm_config.example.yaml` is the tracked local-development fallback template, including optional LiteLLM `api_base` examples; developer-specific copies such as `llm_config.yaml` must stay untracked.
The agent framework targets A2A SDK and Protocol v1. Use protobuf-native
`a2a.types`: SCREAMING_SNAKE_CASE enums, unified `Part` fields, and
`MessageToDict`/`ParseDict` for JSON conversion. Task streams must enqueue the
initial `Task` before any status or artifact updates, and status finality is
derived from `TaskState` because v1 has no `TaskStatusUpdateEvent.final` field.
Assemble custom servers with `a2a.server.routes` factories; prefer
`PrometheusAgent.build_app()` so agent-card routes, request limits,
authentication, and lifecycle behavior stay aligned.
`prometheus_api.a2a_stream` accepts only v1 `task`, `statusUpdate`, and
`artifactUpdate` envelopes with direct `Part` fields; do not add pre-v1 wire
shape fallbacks. Preserve exact ProtoJSON `TASK_STATE_*` values in accumulated
statuses and reject invalid state spellings instead of normalizing them.

`tests/` contains pytest tests named `test_*.py`; integration coverage is concentrated in `tests/test_integration.py`. `examples/` has runnable usage examples and is excluded from ruff and mypy checks. `docs/` contains longer guides; update it when public behavior changes. `docs/agent/LLM_CLIENT_MIGRATION.md` guides people and AI coding assistants through replacing vendor-specific LLM utilities with `llm_client`.

## Build, Test, and Development Commands

Use the Makefile so tools run through the locked `uv` environment:

```bash
make test          # run unit tests with project defaults
make lint          # run ruff check .
make format        # verify ruff formatting
make typecheck     # run mypy on prometheus_api/
make fix           # apply ruff fixes and formatting
make check         # lint + format + typecheck
make test-install  # build wheel, install in a clean venv, smoke-test imports
make build-image IMAGE_TAG=dev
```

`make test-install` creates its clean smoke-test environment with Python 3.12, the
project's minimum supported version, so the result does not depend on a newer system Python.

For targeted tests, use `uv run pytest tests/test_agent.py::TestPrometheusAgentExecutor`.

## Coding Style & Naming Conventions

This project targets Python 3.12+. Ruff uses a 100-character line length and excludes `examples/`. Prefer typed Pydantic models for API payloads, explicit resource classes for endpoints, and clear async/sync parity between `storage_client/resources/` and `storage_client/async_resources/`. Keep `llm_client` sync and async behavior aligned when changing aliases, fallback behavior, logging, or response objects. Use `snake_case` for modules, functions, variables, and test functions; use `PascalCase` for classes.

Preserve the surrounding logging interpolation style when editing existing modules. In
f-string-heavy sections such as `agent/base.py`, prefer f-strings for straightforward values
unless lazy interpolation provides a material benefit.

Agent registry URL lookups should go through `PrometheusAgent.registry_url()` so the `REGISTRY_URL` fallback value stays centralized. Registry HTTP/retry behavior belongs in `agent/registry.py`; registration starts from the app lifespan as a background async task. Keep `REGISTRY_MAX_RETRIES` docs and tests aligned with that startup behavior, including retries against the built-in fallback URL. Invalid retry configuration should not prevent an agent from starting.

LiteLLM A2A routing requires the registered copy of a v1 agent card to retain
top-level `url` and `protocolVersion` fields derived from its JSON-RPC
`supportedInterfaces` entry. Keep those compatibility fields in registry
payloads only; the agent's own discovery card remains strict protocol v1.

Environment variables passed through Docker Compose may be present with an empty value. For agent defaults, prefer the existing pattern `(os.getenv("NAME") or "default").strip()` so unset and empty values both fall back consistently. `AGENT_WORKFLOWS` follows this convention when selecting the workflow-template directory.

Keep debug/compatibility HTTP route logic (including `/api/chat`) in `agent/debug_routes.py` rather than growing `agent/base.py`.

LLM agents choose semantic flavors in code; deployments map those flavors to
provider models in YAML. `LLM_CONFIG_FILE` overrides `LLM_CONFIG_PROFILE`, and
an unset selector uses the installed `registry` profile. Do not reintroduce a
configurable default model alias.

Tool calling is a per-call chat capability, not a flavor: do not add a seventh
YAML alias for it. Pass `tools` and `tool_choice` as keyword arguments to
`chat(...)` and read results from `ChatResponse.tool_calls` and
`ChatResponse.finish_reason` rather than reaching into `ChatResponse.raw`. Build
`ChatResponse` only through `_ClientMixin._build_chat_response` so the four
construction sites cannot drift. Keep `llm_client/tools.py` free of runtime
imports from `llm_client/client.py`, and subclass new tool errors from
`LLMClientError` rather than `LLMAliasError`.

Keep task status event construction in `agent/events.py` and route public helper methods through those helpers instead of duplicating `TaskStatusUpdateEvent` boilerplate.

Base-agent behavior changes that downstream agents may need to react to should be documented in `docs/agent/AGENT_MIGRATIONS.md` under a version heading, with each migration as a short subheading followed by migration steps and a compact code example.

Spec-impacting behavior changes should update `specs/` in the same change and follow `docs/SDD_SPEC_AUTHORING.md`. Add or revise requirement and behavior IDs before implementing new behavior, keep deleted IDs marked retired rather than reusing them, use front-loaded `REQ-NNN-XX:` and `BEH-NNN-XX:` bullets, and tag inferred-but-untested requirements with `⚠ untested` until coverage exists. Spec-backed tests should follow `docs/SDD_TESTING_STANDARD.md`.

Keep the A2A SDK dependency on the supported v1 range (`>=1.0.0,<2`), keep the
directly imported `protobuf` runtime dependency aligned with the SDK's
supported range (`>=5.29.5,<7`), and keep `types-protobuf` development-only. Keep
protobuf migration coverage in `tests/test_agent.py`, `tests/test_a2a_payloads.py`,
and `tests/test_task_store.py` aligned with agent behavior.

## Testing Guidelines

Pytest configuration lives in `pyproject.toml`. Test files, classes, and functions should follow `test_*.py`, `Test*`, and `test_*`. Async tests are supported through `asyncio_mode = "auto"`. Run unit tests with `uv run pytest -m "not integration"`. Integration tests require a configured `.env` based on `.env.example` with valid `DEEPLYNX_*` credentials.

## Commit & Pull Request Guidelines

Recent commits use short, direct summaries such as `fix tag ids` or `Cleaned up docs`. Keep commit subjects concise and focused on one change. For pull requests, include a brief description, test commands run, linked issue or context, and note any credential, environment, Docker image, or DeepLynx behavior changes. Add screenshots only for documentation or UI-facing changes.

## Security & Configuration Tips

Do not commit `.env`, secrets, API keys, generated certificates, or local caches. Use `.env.example` for documenting required variables. Treat integration credentials, DeepLynx IDs, `REGISTRY_URL`, `REGISTRY_MAX_RETRIES`, `LLM_API_KEY`, `EMBEDDING_API_KEY`, `MLFLOW_API_KEY`, MLflow tracking settings, and other LLM provider keys as environment-specific configuration, not hard-coded defaults. LLM debug logging must keep prompt and embedding content hidden unless `LLM_DEBUG_LOG_MESSAGES=true`, LLM credentials must never be read from A2A requests, and agent parameter/registration logging must not emit prompt content or bearer tokens. `ENABLE_MLFLOW_TRACING` must remain opt-in because MLflow traces can record chat inputs and outputs.

## Additional Instructions

When you make a change, ensure that this file gets updated to reflect those changes. We do not want this file getting out of date so it is important that when you make changes, they are accurately documented in this file.
