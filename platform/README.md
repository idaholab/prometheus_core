# Prometheus Platform

A multi-agent analysis platform for engineering and science. Users interact through a React chat UI (served by a FastAPI backend) that routes queries to specialist agents via a central client-agent orchestrator. The platform supports 3D visualization (Exodus, STL, IFC), multi-step analysis workflows, conversation state, and a DeepLynx-backed artifact catalog.

## Architecture

```mermaid
graph TD
  U[User] -->|chat / file upload| FE[React Frontend]
  FE -->|JSON / SSE| BE[FastAPI Backend]
  BE -->|A2A JSON-RPC| CA[Client Agent]
  CA -->|agent discovery + A2A routing| GW[Backend Agent Registry + A2A Gateway]
  CA -->|state + factoids| RED[(Valkey<br/>Redis-compatible)]
  GW -->|A2A| CORR[Corrosion Agent]
  GW -->|A2A| RAD[Radiation Agent]
  GW -->|A2A| THERM[Thermal Agent]
  GW -->|A2A| DATA[Data Agent]
  GW -->|A2A| SYNTH[Synthesis Agent]
  GW -->|A2A| OSTI[OSTI Research Agent]
  FE -->|renders| VIZ[MeshViewer / IFCViewer / MermaidViewer]
```

**Request flow:** A user sends a message in the React frontend, which posts it to the FastAPI backend over its JSON/SSE contract. The backend forwards it as an A2A JSON-RPC request to the client-agent, which classifies the query, discovers relevant specialist agents through the backend's agent registry (`/v1/agents`), collects any missing parameters, builds an execution plan, and dispatches work through the backend's A2A gateway (`/a2a/{agent_name}`). Results (including artifacts) flow back through the client-agent and backend to the frontend for rendering.

## Prerequisites

- Docker with Compose. On Windows, run everything from a WSL2 distro; see
  [Windows + WSL2 setup](docs/docs/windows-wsl2-setup.md).
- `make` and `openssl`. On RHEL-based distros: `sudo dnf groupinstall "Development Tools"` and
  `sudo dnf install openssl`.
- Python 3, used by the setup scripts.
- For Kubernetes only: [k3d](https://k3d.io/stable/#installation),
  [kubectl](https://kubernetes.io/docs/tasks/tools/), [Helm](https://helm.sh/docs/intro/install/)
  and [Tilt](https://docs.tilt.dev/install.html).

## Quickstart

### 1. Configure the environment

```bash
cp .env.example .env
echo "LOCAL_SDK=true" >> .env
```

In `.env`, set `LLM_CONFIG_PROFILE` and `LLM_API_KEY`. The comments in `.env.example` list the
providers.

On Kubernetes behind a TLS-inspecting proxy, also set `EXTRA_CA_CERT` in `.env` to your proxy's CA
certificate file. On the INL network, use `EXTRA_CA_CERT=../common/certs/INL.pem`.

### 2a. Run with Docker Compose

```bash
make up
```

The first run builds every image and takes 5 to 15 minutes. Open http://localhost:5150 and create
your login.

### 2b. Run on a local Kubernetes cluster

```bash
make cluster-up    # create the k3d cluster; safe to run again
make cluster-dev   # build the images, deploy, and reload on every code change
```

`make cluster-dev` installs the stack with the Helm chart in
[`infrastructure/helm/prometheus/`](../infrastructure/helm/prometheus/) and keeps running. When you
edit backend, agent or frontend code, the change is copied into the running pod and the service
reloads. Once the pods are ready, open http://localhost:8080 and create your login. Tilt's dashboard,
with every service's status and logs, is at http://localhost:10350.

## Setup details

### Secrets

The first start fills in every blank secret in `.env`. Back up `.env` after that: without it, the
encrypted data in the admin database can't be read. See
[Encryption and keys](docs/docs/dev-docs/encryption-and-keys.md).

### Base image

Every agent is built on a shared image that contains the Prometheus SDK. There are two ways to
get it:

- **Build it yourself.** This is what `LOCAL_SDK=true` in the Quickstart does. It builds the image
  from the `sdk/` folder in this repo and needs no account.
  The SDK, backend and frontend images reuse the build cache that CI publishes, which needs
  Docker's containerd image store (the default in recent Docker Desktop). Set
  `USE_BUILD_CACHE=false` to build without it, for example when offline.
- **Download it.** Remove `LOCAL_SDK=true` from `.env`. `make up` then pulls
  `ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel` at the tag pinned by
  `PROMETHEUS_API_BASE_IMAGE_HASH` in the `Makefile`, with no login. Set that variable in `.env` to
  use a different tag.

### DeepLynx

Every agent writes an execution record to DeepLynx and won't start without it. To run DeepLynx
with the platform, add `LOCAL_DEEPLYNX=true` to `.env`; `make up` then starts it and fills in the
`DEEPLYNX_*` settings (see [Local DeepLynx install](docs/docs/local-deeplynx.md)). To use an
existing DeepLynx, set `DEEPLYNX_JWT_TOKEN` or both `DEEPLYNX_KEY` and `DEEPLYNX_SECRET`, together
with `DEEPLYNX_ORG_ID` and `DEEPLYNX_PROJECT_ID`.

### Everyday commands

With Docker Compose:

```bash
make up      # start the stack
make logs    # follow the logs
make down    # stop the stack
```

On the Kubernetes cluster:

| Command | What it does |
|---|---|
| `make cluster-status` | Lists the pods |
| `make cluster-logs SVC=backend` | Follows one service's logs |
| `make cluster-down` | Deletes the cluster and everything in it |
| `make cluster-reset` | Deletes the cluster and creates a new one, for a clean start. This erases users and chat history |

Press Ctrl+C to stop `make cluster-dev`. The pods keep running until `make cluster-down`.

## Local frontend development (hot reload)

The React frontend supports hot reload against an already-running Compose stack:

```bash
# 1. Start the stack. The backend is published on 8600 regardless of PROFILE.
#    Use PROFILE= to skip the containerized frontend so it doesn't hold port 5150.
make PROFILE= up

# 2. Run the Vite dev server locally.
cd frontend
make install
make dev           # http://localhost:5150
```

The Vite dev server proxies `/api` to the backend at `VITE_BACKEND_URL` (default `http://localhost:8600`), which maps to the containerized backend.

## Full-system tests

Full-system tests exercise the same LLM-driven planning, parameter requests, specialist agents, and artifacts as the frontend. They never start or reconfigure Docker. Start the full platform with the client-agent host port enabled, then run the suite separately:

```bash
make PROMETHEUS_SYSTEM_TESTING=true up
make test-system
```

`tests/system/prometheus.py` provides concise test helpers for starting a chat, prompting, submitting requested parameters, approving plans, inspecting typed artifacts, and making LLM-judged semantic assertions. It wraps the lower-level lifecycle stream and production artifact APIs in `tests/system/a2a_client.py`.

## Configuration

### Services and ports

These are the Docker Compose ports. On Kubernetes, `make cluster-dev` serves the app and the API
through one address, http://localhost:8080, and nothing else is published.

| Service           | URL / Port                                               | Role                                                                                            |
| ----------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| React frontend    | http://localhost:5150, or 8080 with `PROFILE=prod`       | Entry point                                                                                     |
| Backend (FastAPI) | http://localhost:8600 (`BACKEND_PORT`)                   | JSON/SSE API + auth/sessions; agent registry (`/v1/agents`) + A2A gateway (`/a2a/{agent_name}`) |
| Client agent      | internal only; http://localhost:8001 in system-test mode | Orchestrator                                                                                    |
| Valkey            | localhost:6379                                           | Redis-compatible state, status, artifact metadata, agent registrations                          |
| Postgres          | internal only                                            | `admin-db`: users, OIDC config, signing keys                                                    |

### Backend settings

Backend settings come from `backend/app/config.yml` (override the path with `PROMETHEUS_CONFIG_PATH`):

| Key                    | Description                                                                                     |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| `agent-url`            | Client-agent A2A endpoint (default: `http://localhost:8001`). Overridden by `CLIENT_AGENT_URL`. |
| `agent-secret`         | Bearer token for agent auth. Overridden by `AGENT_SECRET`.                                      |
| `redis-url`            | Redis connection URL for session/conversation state. Overridden by `REDIS_URL`.                 |
| `jwt-secret`           | Session-cookie signing key. Overridden by `BACKEND_JWT_SECRET`.                                 |
| `debug`                | Enable debug features                                                                           |
| `auto-approve-steps`   | Skip manual approval between workflow steps                                                     |
| `workflow-suggestions` | Chat suggestions shown on startup                                                               |

The React app itself is configured through `frontend/config.ts` and `VITE_*` environment variables (e.g. `VITE_BACKEND_URL`).

Notable environment variables (see `.env.example` for the full list):

| Variable                                  | Purpose                                                                                                                                                      |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `LLM_CONFIG_PROFILE`                      | LLM provider; `.env.example` lists the values                                                                                                                |
| `LLM_CONFIG_FILE`                         | Optional custom YAML path inside the agent container; overrides `LLM_CONFIG_PROFILE`                                                                         |
| `DEBUG_AGENTS`                            | When `true`, also build and start the mock agents in `agents/debug-agents/`                                                                                  |
| `OPTIONAL_AGENTS`                         | When `true`, also build and start the heavy agents in `agents/optional/` (OSTI research; its PDF/ML dependencies make it the slowest image to build)         |
| `LOCAL_DEEPLYNX`                          | When `true`, also start DeepLynx from its published images and point the `DEEPLYNX_*` settings at it ([Local DeepLynx install](docs/docs/local-deeplynx.md)) |
| `PROMETHEUS_SYSTEM_TESTING`               | When `true`, Make includes the Compose override that publishes the client-agent on `CLIENT_AGENT_PORT`                                                       |
| Provider API keys                         | Credentials referenced by the selected profile; see `.env.example`                                                                                           |
| `AGENT_SECRET_REQUIRED`                   | Enforce Bearer auth on specialist agents (default `true`)                                                                                                    |
| `LOCAL_CERT_FILE` / `CERT_FILE`           | CA bundle path on host / inside containers                                                                                                                   |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | Corporate proxy settings                                                                                                                                     |

### DeepLynx storage

DeepLynx configuration is required for standard agent execution records. The simplest setup is `LOCAL_DEEPLYNX=true` in `.env` (step 1): `make up` then also starts DeepLynx from its published images and `make deeplynx-setup` fills in the settings below for it. See [Local DeepLynx install](docs/docs/local-deeplynx.md), which also covers building DeepLynx from source.

To use a DeepLynx you already have instead, set either `DEEPLYNX_JWT_TOKEN` or both `DEEPLYNX_KEY` and `DEEPLYNX_SECRET`, together with `DEEPLYNX_ORG_ID` and `DEEPLYNX_PROJECT_ID`. `DEEPLYNX_BASE_URL` is optional and uses the SDK default when omitted. `DEEPLYNX_DATA_SOURCE_ID` is also optional when the project has a default data source.

### Optional integrations (work in progress)

**OIDC single sign-on** — alternative to the local-users login. Providers are *not* configured by environment variable: an admin registers each one at runtime through the in-app admin UI (`POST /api/admin/oidc-providers`), which stores it in admin-db with the client secret encrypted at rest. Login then lives at `GET /api/auth/login/{provider_id}`. See `docs/docs/dev-docs/multi-user-setup.md`.

## Project structure

```
platform/
  Makefile                  # Top-level orchestration (Compose, generate, tests)
  docker-compose.yml        # Core infra: Valkey, Postgres (admin-db), client-agent, backend, frontend
  docker-compose.agents.yml # Auto-generated from agents/*/docker-compose.yml — do not edit
  scripts/
    generate-agents-compose.sh
  backend/
    app/                    # FastAPI app: routers, services, contract, config
    tests/
  frontend/                 # React + Vite single-page app
    src/                    # App, components, viewers, lib (backend contract adapter)
    public/                 # Static assets, custom-element JSX, IFC/VTK JS bundles
    Dockerfile              # dev (Vite) + prod (nginx) build stages
    nginx/                  # prod nginx template (SPA, /api proxy via $BACKEND_UPSTREAM, /healthz)

  agents/
    client-agent/           # A2A orchestrator
    optional/               # heavy agents, only with OPTIONAL_AGENTS=true
      osti-research-agent/  # OSTI literature search (PDF/ML deps, slow build)
    artifact-debug-agent/   # Artifact handling test agent
    (debug) corrosion-agent/        # Corrosion analysis specialist
    (debug) radiation-agent/        # Radiation damage specialist
    (debug) thermal-agent/          # Thermal analysis specialist
    (debug) material-data-agent/    # Material data retrieval
    (debug) synthesis-agent/        # Report synthesis

  tests/                    # Infrastructure / integration tests for the full stack
  docs/                     # Project documentation (Zensical site)
```

## Development

### Agent discovery

`make up` scans `agents/*/docker-compose.yml` and writes `docker-compose.agents.yml`, so don't edit
that file by hand. Agents in `agents/debug-agents/` and `agents/optional/` are included only with
`DEBUG_AGENTS=true` and `OPTIONAL_AGENTS=true`.

On Kubernetes, each agent also needs an `agents/<name>/helm-values.yaml`. The chart's
`values.yaml` documents the settings.

### Frontend (`frontend/Makefile`)

```bash
cd frontend

make install     # npm install
make dev         # Vite dev server on port 5150 (hot reload)
make build       # Production bundle → dist/
make lint        # eslint
make typecheck   # tsc
make check       # lint + typecheck
```

The Vite dev server proxies `/api` to the backend (`VITE_BACKEND_URL`, default `http://localhost:8600`). React unit tests live alongside the source as `src/**/*.test.ts`.

### Per-agent

Each agent has its own `pyproject.toml`; the client-agent additionally ships a `tests/` suite. Run from the agent directory:

```bash
cd agents/client-agent
uv sync
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests
```

### Infrastructure tests (`tests/`)

```bash
make test-static       # Static checks of compose, env vars, ports — no Docker needed
make test-integration  # Hits the running containers (start the stack first via make up)
make test-infra        # Both
```

See `tests/README.md` for how the integration tests pick a stack and run in CI without real LLM or DeepLynx credentials.

### Startup check

`make up` returns only once the platform is up. It first waits for every service with a healthcheck to report healthy (`docker compose up --wait`), then runs `make check`. That checks the backend and frontend on their host ports, the frontend's `/api` proxy, and that the client-agent and every included agent have registered with the backend's agent registry. `restart`, `ng-up` and `ng-restart` do the same, and the `-fg` targets can't, since they never return. Set `CHECK=false` to return as soon as the containers start, and run `make check` later against a running stack. CI's `platform: up` job runs the same `make up`, then `make test-integration` against that stack.

A healthy agent shows only that it serves HTTP. Registration with the backend runs in the background, so `make check` is what confirms that the platform can route to the agent. Every per-agent `docker-compose.yml` must define a healthcheck on the base class's health endpoint, and `make test-static` enforces it.

## Troubleshooting

**Forgot your password (Docker Compose).** With the platform running, delete the local user
accounts and refresh the app. You are prompted to create a new username and password.

```bash
make clear-admin-users
```

**Reinstalled, or lost `.env` (Docker Compose).** The old volumes still use the old database
passwords, and their rows are encrypted with the old key, so the backend can't connect.
`make clobber` deletes those volumes, including all users, keys and history, so the next `make up`
starts fresh.

**Either of those, on Kubernetes.** `make cluster-reset` deletes the cluster and creates a new one,
which erases every user, key and conversation.

## Documentation

- [Windows + WSL2 setup](docs/docs/windows-wsl2-setup.md) - installing and verifying Docker Desktop's WSL2 integration before running `make up`
- [Architecture](docs/docs/dev-docs/architecture.md)
- [Client-agent developer guide](agents/client-agent/README.md)
- [Adding agents](docs/docs/dev-docs/adding-agents.md)
- [Artifacts](docs/docs/dev-docs/artifacts.md)
- [Multi-user setup](docs/docs/dev-docs/multi-user-setup.md) - identity JWTs, credential broker, running single-user without signing keys
- [Visualization plugins](docs/docs/dev-docs/visualization-plugins.md)
- [Migration guide](docs/docs/dev-docs/migration.md) - what changed from the original projects and why
- [Self-hosted DeepLynx](docs/docs/local-deeplynx.md) - roll out your own DeepLynx instance and connect the platform to it
