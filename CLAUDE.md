# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack at a glance

Multi-agent platform for nuclear engineering analysis. A React frontend (`frontend/`) talks to a FastAPI **`backend/`** service over a JSON/SSE contract; the backend relays to a tool-calling **client-agent** orchestrator over A2A JSON-RPC 2.0; the client-agent dispatches to specialist agents (corrosion, radiation, thermal, data, synthesis, OSTI research, form-filler, plus the debug agents artifact-debug and code-render-debug) through a **LiteLLM proxy** that doubles as the agent registry/gateway and the LLM proxy. Valkey holds conversation state, browser-session state, short-lived status updates, the SSE event bus and the artifact registry via the Redis-compatible protocol. Postgres backs LiteLLM's persistent agent registrations, and separately the backend's admin plane (local users, OIDC config, signing keys) — migrated by Alembic from `backend/docker-entrypoint.sh`.

The `frontend/` is a Node/TypeScript app (React + Vite). The `backend/` runs Python 3.12+ (also 3.13); the client-agent and infra tests use 3.13.

## Frontend: FastAPI backend + React app

The frontend is a standalone FastAPI **`backend/`** service (its own JSON/SSE contract) plus an in-house React app in **`frontend/`** (React + Vite) whose element/viewer plumbing lives in `frontend/src/lib/elements/`.

- Design: `plan.md` (reconstructed brief + ordered work plan) and `backend/CONTRACT.md` (frozen wire contract).
- Ordered steps + live status: `tasks/README.md` — steps 00–09 done (skeleton, contract, auth/sessions, lifted utils, chat turn, SSE events, uploads, artifacts content proxy + `render_hint`, conversation history, docker/compose/nginx); only 10 (end-to-end verify) still pending. The `backend` service is in the root `docker-compose.yml` (host port 8600 → container 8000), built from the prometheus_api base image; it comes up with `make up` regardless of `PROFILE`.
- `backend/` is `uv`-managed Python 3.13: `uv run pytest`, `uv run ruff check`, `uv run mypy app/` (see `backend/README.md`). The backend owns its own contract in `app/contract.py` — do not couple it to `prometheus_api` base-image types on the wire. It no longer migrates itself at startup, so a local run needs an explicit `uv run alembic upgrade head` first.
- **The backend holds no per-session state in memory.** Sessions (`session:{sid}`), logout markers (`revoked:sid:{sid}`) and the SSE event bus (pub/sub on `sse:{sid}`) are all in Valkey, so a restart no longer forks conversations and `BACKEND_WORKERS` > 1 is valid — default 1; see the *Multi-worker* section of `backend/README.md`. `SessionState` is a **frozen snapshot**: change session state through a `SessionStore` coroutine, never by assigning to a field.

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

Run from `frontend/` with Node + npm. The Vite dev server proxies `/api` to the backend at `VITE_BACKEND_URL` (default `http://localhost:8600`), so bring up the `backend` (and the stack behind it) first. The root `Makefile` also exposes `make react-dev` / `react-build` / `react-check`.

```bash
make install     # npm install
make dev         # npm run dev -- --port 5150   (Vite dev server, hot reload)
make build       # npm run build                (production bundle → dist/)
make lint        # npm run lint                 (eslint)
make typecheck   # npm run typecheck            (tsc)
make check       # lint + typecheck
```

Config comes from `frontend/config.ts` plus `VITE_*` env vars (e.g. `VITE_BACKEND_URL`); there is no `config.yml`.

The client-agent and each specialist agent have their own `pyproject.toml` and `tests/` (e.g. `agents/client-agent/tests/test_workflow_library.py`). Run them per-agent with `uv run pytest` from inside that agent's directory.

## Architecture

### Request flow (read this before changing routing)

```
User → React frontend (frontend/, Vite dev server or nginx-served build)
     → FastAPI backend (backend/app, JSON/SSE contract; session-cookie auth)
     → A2A JSON-RPC over httpx (backend → client-agent, Bearer = AGENT_SECRET)
     → client-agent (agents/client-agent/agent.py)
        ├─ Tool-calling loop: orchestrator/agent_loop.py (entry: chat_flow.chat)
        │     every skill / workflow template is an LLM tool; the model picks the next
        │     parameterized call after each result (artifact ids flow via tool results).
        │     Pauses persist in state: missing user inputs / ask_user / INPUT_REQUIRED
        │     → needs_info; requires_approval → plan_ready.
        │     Design: docs/docs/dev-docs/agent-loop-orchestration.md
        ├─ Tool/agent discovery: tool_discovery.py + capability_cache.py
        │     hits LiteLLM `/v1/agents` and each agent's well-known card
        ├─ Workflow library: workflow_library/  (YAML templates in workflows/)
        ├─ Conversation state: conversation_store.py → Valkey  (key: conversation:{id})
        └─ Status updates: store_status_update() → Valkey  (key: agent:status:{id})
     → LiteLLM proxy (litellm-proxy:4000) routes A2A calls via /a2a/{agent_name}
     → Specialist agent (built on PrometheusAgent base class from the `prometheus_api`
       package, baked into the prometheus_api base image at PROMETHEUS_API_BASE_IMAGE_HASH)
```

The backend consumes the client-agent's A2A `message/stream` and re-emits status and artifact events to the React frontend over SSE (`/api/events`). Do not add `/status/{conversation_id}` polling for new long-running agent calls.

### Why LiteLLM is in the loop

LiteLLM plays two roles simultaneously:
1. **Agent gateway / registry**: each specialist registers at startup; the client-agent reads `/v1/agents` and forwards A2A traffic via `/a2a/{agent}`. Registrations persist in `litellm-db` (Postgres) so a LiteLLM restart doesn't lose them.
2. **Optional LLM proxy**: agents selecting the `registry` LLM profile use LiteLLM for inference. Other installed profiles call their configured providers directly.

The client-agent still falls back to each agent's `/.well-known/agent.json` for full per-skill metadata because LiteLLM's listing can be a lossy summary. If you change capability metadata, verify both paths.

### Agents

Every specialist subclasses `PrometheusAgent` (provided by the prebuilt `prometheus_api` base image; see `agents/<name>/Dockerfile`). The base class handles HTTP serving, Bearer auth (`AGENT_SECRET`), agent-card serving, LiteLLM registration on startup, A2A JSON-RPC parsing, task lifecycle, and auto-wrapping the `process_analysis()` return value as a JSON artifact. To add a new agent see `docs/docs/dev-docs/adding-agents.md` — the short version: create `agents/<name>/{agent.py, agent_card.json, Dockerfile, docker-compose.yml, pyproject.toml}` and `make generate` will pick it up.

Specialist agents currently in tree: `client-agent`, `corrosion-agent`, `radiation-agent`, `thermal-agent`, `data-agent`, `synthesis-agent`, `osti-research-agent`, `form-filler-agent`, `artifact-debug-agent`, `code-render-debug-agent` (debug agents, included with `DEBUG_AGENTS=true`; `code-render-debug-agent` returns fixed sample files per language to exercise the `code` and `table` viewers).

### Artifacts

Artifacts are conversation-scoped, tracked in Valkey (with in-memory fallback) by `ArtifactReference` records (`artifact_id`, `uri`, `mime_type`, `tags`, etc.). The backend serves artifact content and attaches a `render_hint`; the React frontend routes each artifact by `render_hint`/`mime_type`/`tags` to the matching viewer in `frontend/src/viewers/` (MeshViewer for Exodus/STL, IFC, Mermaid, PDF, image, JSON, citation/reference, or a file download). Returning a plain dict from `process_analysis()` is auto-wrapped as JSON; for richer artifacts emit them explicitly via the event queue. See `docs/docs/dev-docs/artifacts.md`.

### Visualization plugins

The React viewers live in `frontend/src/viewers/` (`mesh/MeshViewer` for Exodus/STL, `ifc/`, Mermaid, PDF, image, JSON, PlanViewer, FollowUpSuggestions, Report, ThermalAnalysis, Reference); some older custom-element JSX also lives in `frontend/public/elements/`. They are driven by the backend's artifact/event payloads (via `render_hint`). Exodus/STL meshes are rendered client-side by the VTK.js-based engine in `frontend/src/viewers/mesh/MeshViewerEngine.ts` (supporting bundles in `frontend/public/js/`). See `docs/docs/dev-docs/visualization-plugins.md`.

### Shared protocol types

Two contracts sit back to back. The **React frontend ↔ backend** wire contract (JSON/SSE) is owned by the backend: frozen in `backend/CONTRACT.md`, typed in `backend/app/contract.py`, and mirrored in TypeScript under `frontend/src/lib/` (see `frontend/AGENT-CONTRACT.md`) — deliberately decoupled from the base-image types. The **backend ↔ client-agent** contract (`ConversationRequest`, `ConversationResponse`, `ConversationStatus`) lives in `prometheus_api.contract` (available in every Python container via the base image); the client-agent re-exports it from `orchestrator/models.py` — change it in `prometheus_api`, not here. The raw A2A wire types (messages, parts, tasks) come from the `a2a-sdk`. There is no longer a `shared/` bind mount: every service runs from its image, so the only runtime host mounts left are `litellm_config.yaml` (config) and `./frontend` on the `dev`-profile Vite container (HMR).

## Configuration & secrets

- `.env` (copied from `.env.example`) holds `LLM_CONFIG_PROFILE`, optional `LLM_CONFIG_FILE`, provider keys, `AGENT_SECRET`, `REDIS_PASSWORD`, `BACKEND_JWT_SECRET`, `LITELLM_MASTER_KEY`, `LITELLM_DB_PASSWORD`, `LITELLM_LOCAL_PORT`, optional `DEEPLYNX_*`, and optional proxy vars.
- The backend loads `backend/app/config.yml` (`agent_url`, `agent_secret`, `redis_url`, session/JWT settings). Env vars (`CLIENT_AGENT_URL`, `AGENT_SECRET`, `REDIS_URL`, `BACKEND_JWT_SECRET`, `BACKEND_COOKIE_NAME`, `BACKEND_TOKEN_TTL_SECONDS`) override individual keys; `PROMETHEUS_CONFIG_PATH` overrides the file path. The React app is configured via `frontend/config.ts` + `VITE_*` env (e.g. `VITE_BACKEND_URL`).
- Multi-user identity is a **separate key** from the session cookie above: `USER_IDENTITY_PRIVATE_KEY` (RS256, backend only) signs the short-lived JWT the backend mints per turn (`backend/app/identity.py`) to prove the caller's identity to agents; every agent verifies with `USER_IDENTITY_PUBLIC_KEY`, never the private key. Generate a keypair with `prometheus-identity-keygen`. `CREDENTIAL_BROKER` selects the per-user credential backend (`env` default, `vault` for production). See `docs/dev-docs/multi-user-setup.md`.
- Agents hardcode semantic flavors such as `medium`. Their selected installed or custom YAML maps those flavors to provider models. `litellm_config.yaml` supplies the proxy mapping used by the `registry` profile.
- The base image `prometheus_api` is pulled from `mooseharbor.hpc.inl.gov`; pinned via the `PROMETHEUS_API_BASE_IMAGE_HASH` build arg in `docker-compose.yml`. Bumping the platform's PrometheusAgent SDK = bumping that hash.

## Service map (default ports)

| Service | Container | Host port | Notes |
|---------|-----------|-----------|-------|
| React frontend (dev) | `frontend-dev` | 5150 (`FRONTEND_DEV_PORT`) | Vite dev server; compose profile `dev` |
| React frontend (prod) | `frontend-prod` | 8080 (`FRONTEND_PROD_PORT`) | nginx-served build; compose profile `prod` |
| Backend (FastAPI) | `backend` | 8600 (`BACKEND_PORT`) | JSON/SSE contract; container port 8000 |
| Client agent | `client-agent` | 8001 (`CLIENT_AGENT_PORT`) | Container port 8000 |
| LiteLLM proxy | `litellm-proxy` | `LITELLM_LOCAL_PORT` (e.g. 9977) | Gateway + LLM proxy |
| LiteLLM Postgres | `litellm-db` | (internal) | Persistent agent registrations |
| Valkey | `agent-valkey` | 6379 (`REDIS_LOCAL_PORT`) | Auth via `REDIS_PASSWORD` |
| Specialist agents | per-agent containers | 8002–8009 typically | Each on container port 8000 |

All services share the `agent-network` bridge.

## Conventions worth knowing

- **Don't edit `docker-compose.agents.yml`** — it's regenerated by `make generate` from the per-agent compose files. Edit the per-agent file instead, then re-run.
- The React `frontend/` uses **ESLint + TypeScript** (`npm run lint`, `npm run typecheck`). The Python `backend/` and agents use **Ruff** + **mypy** (`uv run ruff check`, `uv run mypy app/`). Match the toolchain of whichever tree you touch.
- Tests are split: `tests/` (infra/integration of the whole stack), `backend/tests/` (backend units + contract), `frontend/src/**/*.test.ts` (React unit tests), `agents/<name>/tests/` (per-agent unit tests). The infra suite uses the `integration` pytest marker for tests that need running containers.
- Agents choose semantic model flavors in code; deployment configuration must not override that choice.

## Further reading (in repo)

- `docs/docs/dev-docs/architecture.md` — full architecture write-up with sequence diagrams
- `docs/docs/dev-docs/adding-agents.md` — agent template and registration walkthrough
- `docs/docs/dev-docs/artifacts.md` — artifact reference model and rendering rules
- `docs/docs/dev-docs/visualization-plugins.md` — JSX viewer components and triggers
- `docs/docs/dev-docs/migration.md` — what changed when `multi_agent_testbed` was merged in (and why)
- `docs/docs/dev-docs/multi-user-setup.md` — multi-user configuration, credential broker, isolation (operator + developer guide)
- `docs/docs/dev-docs/encryption-and-keys.md` — every secret and key in the platform, what protects what, and what breaks if one is lost or rotated

## Further reading (prometheus_api repo)

- `prometheus_api/docs/agent/MULTI_USER.md` — identity JWT flow, credential broker backends, per-user worker pool, conversation ownership (agent author reference)
- `prometheus_api/docs/agent/IDENTITY_KEY_MANAGEMENT.md` — RS256 key generation and distribution per service, third-party agent integration via JWKS, rotation (agent author reference; no HS256 option exists)
