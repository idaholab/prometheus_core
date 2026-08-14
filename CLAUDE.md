# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack at a glance

Multi-agent platform for nuclear engineering analysis. A Chainlit frontend talks to a LangGraph **client-agent** orchestrator over A2A JSON-RPC 2.0; the client-agent dispatches to specialist agents (corrosion, radiation, thermal, data, synthesis, OSTI research, form-filler, artifact-debug) through a **LiteLLM proxy** that doubles as the agent registry/gateway and the LLM proxy. Valkey holds conversation state, short-lived status updates, and the artifact registry via the Redis-compatible protocol. Postgres backs LiteLLM's persistent agent registrations.

Python versions are split: frontend pins `>=3.12,<3.13` (Chainlit/VTK constraints); client-agent and infra tests use 3.13.

## Top-level commands (root Makefile)

The root `Makefile` drives the full Docker Compose stack. It picks `podman-compose` if present, else `docker compose`, and auto-discovers any `agents/*/docker-compose.yml` to generate `docker-compose.agents.yml` via `scripts/generate-agents-compose.sh`. The compose file uses project-root-relative paths and shared build args because Compose YAML anchors do not cross included files.

```bash
make up              # generate + build + start everything (detached)
make up-fg           # same, foreground
make restart         # restart without rebuild (still re-runs generate)
make ng-up           # skip the regenerate step (use existing docker-compose.agents.yml)
make down            # stop services (add down-v to drop volumes)
make clear-litellm-db # stop services + remove only LiteLLM's Postgres volume
make logs SERVICE=client-agent
make generate        # only (re)write docker-compose.agents.yml
make clean-generated # delete the generated agents compose file

make test-static       # infra tests that don't need Docker
make test-integration  # infra tests against running containers
make test-infra        # both
```

Launch and restart targets clear LiteLLM's Postgres volume before starting services so stale agent registrations do not survive across platform launches. Valkey state is left intact.

To temporarily exclude an agent, remove (or rename) its `agents/<name>/docker-compose.yml` and re-run `make generate`. `docker-compose.override.yml` is auto-included if present for local-only tweaks.

## Frontend commands (`frontend/Makefile`)

Run from `frontend/` with `uv` available. The dev server expects a running client-agent on `agent-url` from `frontend/config.yml` (override via `CLIENT_AGENT_URL`).

```bash
make run-local   # chainlit run main.py -h --port 8500
make run-dev     # chainlit run main.py -h (default port)
make test        # uv run pytest
make lint        # ruff check
make format      # ruff format --check
make typecheck   # mypy main.py components/ utils/
make check       # lint + format + typecheck
make fix         # ruff --fix + ruff format
```

Single-test invocation: `uv run pytest tests/test_chat.py` or `uv run pytest -k <name>`.

The client-agent and each specialist agent have their own `pyproject.toml` and `tests/` (e.g. `agents/client-agent/tests/test_workflow_library.py`). Run them per-agent with `uv run pytest` from inside that agent's directory.

## Architecture

### Request flow (read this before changing routing)

```
User → Chainlit (frontend/main.py + components/message_handler.py)
     → A2A JSON-RPC over httpx (frontend/utils/a2a_client.py, Bearer = AGENT_SECRET)
     → client-agent (agents/client-agent/agent.py)
        ├─ LangGraph orchestration: understand_query → route_by_decision
        │     ├─ "fallback"         → fallback_response
        │     ├─ "direct_invoke"    → invoke_agent_generic
        │     ├─ "collect_params"   → ask_followup_dynamic   (returns to frontend as needs_info)
        │     └─ "plan_and_approve" → plan → show_plan → [approval] → execute
        ├─ Tool/agent discovery: tool_discovery.py + capability_cache.py
        │     hits LiteLLM `/v1/agents` and each agent's well-known card
        ├─ Workflow library: workflow_library/  (YAML templates in workflows/)
        ├─ Conversation state: conversation_store.py → Valkey  (key: conversation:{id})
        └─ Status updates: store_status_update() → Valkey  (key: agent:status:{id})
     → LiteLLM proxy (litellm-proxy:4000) routes A2A calls via /a2a/{agent_name}
     → Specialist agent (built on PrometheusAgent base class from the `prometheus_api`
       package, baked into the prometheus_api base image at PROMETHEUS_API_BASE_IMAGE_HASH)
```

The frontend uses A2A `message/stream`; streamed status events render progress in a `cl.Step`. Do not add `/status/{conversation_id}` polling for new long-running agent calls.

### Why LiteLLM is in the loop

LiteLLM plays two roles simultaneously:
1. **Agent gateway / registry**: each specialist registers at startup; the client-agent reads `/v1/agents` and forwards A2A traffic via `/a2a/{agent}`. Registrations persist in `litellm-db` (Postgres) so a LiteLLM restart doesn't lose them.
2. **Optional LLM proxy**: agents selecting the `registry` LLM profile use LiteLLM for inference. Other installed profiles call their configured providers directly.

The client-agent still falls back to each agent's `/.well-known/agent.json` for full per-skill metadata because LiteLLM's listing can be a lossy summary. If you change capability metadata, verify both paths.

### Agents

Every specialist subclasses `PrometheusAgent` (provided by the prebuilt `prometheus_api` base image; see `agents/<name>/Dockerfile`). The base class handles HTTP serving, Bearer auth (`AGENT_SECRET`), agent-card serving, LiteLLM registration on startup, A2A JSON-RPC parsing, task lifecycle, and auto-wrapping the `process_analysis()` return value as a JSON artifact. To add a new agent see `docs/docs/dev-docs/adding-agents.md` — the short version: create `agents/<name>/{agent.py, agent_card.json, Dockerfile, docker-compose.yml, pyproject.toml}` and `make generate` will pick it up.

Specialist agents currently in tree: `client-agent`, `corrosion-agent`, `radiation-agent`, `thermal-agent`, `data-agent`, `synthesis-agent`, `osti-research-agent`, `form-filler-agent`, `artifact-debug-agent`.

### Artifacts

Artifacts are conversation-scoped, tracked in Valkey (with in-memory fallback) by `ArtifactReference` records (`artifact_id`, `uri`, `mime_type`, `tags`, etc.). The frontend's `message_handler.render_artifacts()` routes by `mime_type`/`tags` to MeshViewer (Exodus/STL), IFCViewer, MermaidViewer, PDF viewer, citation markdown, or `cl.File`. Returning a plain dict from `process_analysis()` is auto-wrapped as JSON; for richer artifacts emit them explicitly via the event queue. See `docs/docs/dev-docs/artifacts.md`.

### Visualization plugins

Custom React/JSX components live in `frontend/public/elements/` (MeshViewer, IFCViewer, MermaidViewer, PlanViewer, DynamicForm, FollowUpSuggestions). They receive props from Python via `cl.CustomElement` and have no protocol coupling. Exodus and STL uploads run through a shared VTK pipeline (`frontend/components/exodus/vtk_pipeline.py`, reused by `frontend/components/stl_integration.py`) that writes VTP files into `frontend/public/mesh-data/{id}/` and renders them in the single `MeshViewer`. Plugin Python wrappers live under `frontend/plugins/` and are imported eagerly from `main.py` so element JSX is copied into `public/elements/` before Chainlit starts serving.

### Shared protocol types

The frontend ↔ client-agent wire contract (`ConversationRequest`, `ConversationResponse`, `ConversationStatus`) lives in `prometheus_api.contract` (in the `prometheus_api` repo, available in every container via the base image). The frontend re-exports it from `frontend/utils/a2a_client.py` and the client-agent from `orchestrator/models.py` — change it in `prometheus_api`, not here. The raw A2A wire types (messages, parts, tasks) come from the `a2a-sdk`. The `shared/` directory is still mounted into every container at `/app/shared` via the `*common-volumes` anchor in `docker-compose.yml`, but only as a scratch file-exchange area (e.g. `shared/artifact-debug/`).

## Configuration & secrets

- `.env` (copied from `.env.example`) holds `LLM_CONFIG_PROFILE`, optional `LLM_CONFIG_FILE`, provider keys, `AGENT_SECRET`, `REDIS_PASSWORD`, `CHAINLIT_AUTH_SECRET`, `LITELLM_MASTER_KEY`, `LITELLM_DB_PASSWORD`, `LITELLM_LOCAL_PORT`, optional `DEEPLYNX_*`, and optional proxy vars.
- `frontend/config.yml` controls Chainlit-side behavior (`agent-url`, `agent-secret`, `redis-url`, `auto-approve-steps`, `local-users`, workflow suggestions). Env vars (`CLIENT_AGENT_URL`, `AGENT_SECRET`, `REDIS_URL`) override individual keys; `PROMETHEUS_CONFIG_PATH` overrides the file path.
- Agents hardcode semantic flavors such as `medium`. Their selected installed or custom YAML maps those flavors to provider models. `litellm_config.yaml` supplies the proxy mapping used by the `registry` profile.
- The base image `prometheus_api` is pulled from `mooseharbor.hpc.inl.gov`; pinned via the `PROMETHEUS_API_BASE_IMAGE_HASH` build arg in `docker-compose.yml`. Bumping the platform's PrometheusAgent SDK = bumping that hash.

## Service map (default ports)

| Service | Container | Host port | Notes |
|---------|-----------|-----------|-------|
| Chainlit frontend | `chainlit-frontend` | 8500 (`CHAINLIT_FRONTEND_PORT`) | OAuth/Okta optional |
| Client agent | `client-agent` | 8001 (`CLIENT_AGENT_PORT`) | Container port 8000 |
| LiteLLM proxy | `litellm-proxy` | `LITELLM_LOCAL_PORT` (e.g. 9977) | Gateway + LLM proxy |
| LiteLLM Postgres | `litellm-db` | (internal) | Persistent agent registrations |
| Valkey | `agent-valkey` | 6379 (`REDIS_LOCAL_PORT`) | Auth via `REDIS_PASSWORD` |
| Specialist agents | per-agent containers | 8002–8009 typically | Each on container port 8000 |

All services share the `agent-network` bridge.

## Conventions worth knowing

- **Don't edit `docker-compose.agents.yml`** — it's regenerated by `make generate` from the per-agent compose files. Edit the per-agent file instead, then re-run.
- The frontend uses **Ruff** (`E`,`F`, ignore `E501`, line-length 120, target py312) and **mypy** (`warn_return_any`, `ignore_missing_imports`). Match these for new frontend code.
- Tests are split: `tests/` (infra/integration of the whole stack), `frontend/tests/` (Chainlit + a2a client), `agents/<name>/tests/` (per-agent unit tests). The infra suite uses the `integration` pytest marker for tests that need running containers.
- Agents choose semantic model flavors in code; deployment configuration must not override that choice.

## Further reading (in repo)

- `docs/docs/dev-docs/architecture.md` — full architecture write-up with sequence diagrams
- `docs/docs/dev-docs/adding-agents.md` — agent template and registration walkthrough
- `docs/docs/dev-docs/artifacts.md` — artifact reference model and rendering rules
- `docs/docs/dev-docs/visualization-plugins.md` — JSX viewer components and triggers
- `docs/docs/dev-docs/migration.md` — what changed when `multi_agent_testbed` was merged in (and why)
- `docs/docs/dev-docs/multi-user-setup.md` — multi-user configuration, credential broker, isolation (operator + developer guide)

## Further reading (prometheus_api repo)

- `prometheus_api/docs/agent/MULTI_USER.md` — identity JWT flow, credential broker backends, per-user worker pool, conversation ownership (agent author reference)
