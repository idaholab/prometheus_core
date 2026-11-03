# MOOSEnger Agent

Prometheus specialist agent that hosts [MOOSEnger](https://arxiv.org/abs/2603.04756),
INL's simulation-aware assistant for the MOOSE multiphysics framework. Through
the Prometheus chat UI a user can ask MOOSE questions, have a validated HIT
(`.i`) input generated from a natural-language description, and run it.

| Skill | What it does | Returns |
|---|---|---|
| `moose_general_qa` | MOOSE objects, syntax, modules, workflows | `answer` (text) |
| `moose_input_generation` | Draft → MOOSE-aware checks → `--check-input` → repair loop until valid | `current.i` as text artifact (CodeViewer, MOOSE highlighting) + JSON (`outputs`, `assurance`) |
| `moose_input_execution` | Generate if needed, validate, run through an MCP execution server, diagnose/repair runtime failures | `moose_stdout.log` / `moose_stderr.log` artifacts + JSON. `requires_approval`, long-running |

This directory is only a launcher. The agent class --
`moosenger.a2a.prometheus_agent.MOOSEngerPrometheusAgent(PrometheusAgent)` --
and its agent card live **in the MOOSEnger repository**, behind MOOSEnger's
optional `prometheus` extra, so MOOSEnger can use every `prometheus_api`
utility while people without the platform are unaffected. The Dockerfile
installs MOOSEnger from a checkout (`MOOSENGER_SRC`) on top of the
`prometheus_api` base image, without its `prometheus` extra (the base image
already has the platform's SDK); `agent.py` here is three lines. MOOSEnger is never
vendored under `platform/agents/`: it imports provider SDKs that
`make test-static` forbids in agent source trees, and it is a separately
versioned project.

## How it maps onto Prometheus

* `PrometheusAgent.build_app()` owns the server: Bearer auth, `/healthz`, user
  identity, Redis task store, registry registration. The agent only implements
  `_execute`, `lifespan` and `configure_app` (`/health`, which reports
  MOOSEnger's startup status and, unlike `/healthz`, needs the bearer token).
* One Prometheus conversation ↔ one MOOSEnger session: the A2A `context_id` is
  hashed into MOOSEnger's session id, so follow-up turns ("now make it
  transient", "run it") land in the same workspace under
  `$MOOSENGER_PROJECT_DIR/sessions/...`.
* MOOSEnger's `pending_interaction` (a modeling clarification or a tool
  approval) becomes a Prometheus `INPUT_REQUIRED` form with two fields,
  `moosenger_action` (dropdown of MOOSEnger's `allowed_actions`) and
  `moosenger_answer` (free text). The orchestrator re-sends the original
  params plus the answers; `agent.py` rebuilds MOOSEnger's
  `interaction_response` from them. Pending state is kept in the agent's
  context store (Redis) so a stale form answer on a later turn is ignored.
* The execution skill calls `declare_long_running()` so the orchestrator hands
  the turn back to the user and delivers the result when the run finishes.
* A Q&A turn always returns its answer, even when an earlier generation in the
  same conversation was blocked.
* Startup: `lifespan()` renders `config/moosenger.yaml` with the environment,
  bridges `LLM_API_KEY` → `OPENAI_API_KEY`, then runs MOOSEnger's strict
  startup validation and (optionally) warmup off the event loop. A failure is
  logged and every request answers `backend_unavailable` until fixed; set
  `MOOSENGER_STARTUP_STRICT=true` to make the container exit instead.

## Where MOOSEnger comes from (no submodule)

`MOOSENGER_SRC` is a Docker build context: a git URL with a pinned ref
(`https://<host>/<group>/moosenger.git#<tag>`, fetched by BuildKit at build
time) for reproducible platform builds, or a local checkout path while
developing MOOSEnger. The platform repo therefore records *which* MOOSEnger
(the ref in `.env.example`/docs) without vendoring it. Do not add MOOSEnger as
a submodule under `platform/agents/`: `make test-static` scans every `*.py`
and `pyproject.toml` there for provider-SDK usage that MOOSEnger legitimately
contains, and `make generate` would try to treat the checkout as an agent. If a
submodule is ever required (air-gapped builds), put it outside `agents/`, e.g.
`platform/vendor/moosenger`, and point `MOOSENGER_SRC` at it.

## Prerequisites

1. **MOOSEnger checkout** that contains `src/moosenger/a2a/prometheus_agent.py`
   (MOOSEnger with the Prometheus agent, commit `0180985ee6` or later). The
   image build fails its import check otherwise. That commit also adds the
   `.dockerignore` that keeps `.git`, `.venv` and the MOOSE submodule out of
   the build context.
2. **A MOOSE execution server** for `moose_input_execution`: MOOSEnger's own
   FastMCP server (`python -m moosenger.mcp.moose_server`) next to a MOOSE
   build. `docker-compose.moose-mcp.yml` runs one as a sidecar from a MOOSE
   image; or point `MOOSE_MCP_URL` at an existing server (e.g. on HPC).
   Without it, Q&A and generation still work (generation's `--check-input`
   smoke step also goes through MCP; set `domains.moose.smoke_required: false`
   in `config/moosenger.yaml` if you have no execution backend at all).
3. **MOOSE source checkout** (read-only) for syntax data, pyhit, the language
   server and the knowledge base. Optional but strongly recommended. Agent
   compose files may not bind-mount host paths (`make test-static` enforces
   this), so `/moose` is an empty named volume by default; bind your checkout
   in `platform/docker-compose.override.yml` (below).
4. **Vector database**: warmup pulls MOOSEnger's pre-built one from its ORAS
   registry when `MOOSENGER_REGISTRY_USERNAME/PASSWORD` are set, otherwise copy
   `vector_data/` into the `moosenger-workspace` volume once.
5. An **OpenAI-compatible LLM endpoint** for MOOSEnger's own client (defaults
   to INL LiteLLM, i.e. the same key as the platform's `inl_litellm` profile).
6. **DeepLynx credentials**, as for every agent: the SDK refuses to start
   without `DEEPLYNX_JWT_TOKEN` (or `DEEPLYNX_KEY` + `DEEPLYNX_SECRET`),
   `DEEPLYNX_ORG_ID` and `DEEPLYNX_PROJECT_ID`.

## Enable it

Add to `platform/.env` (see `.env.example` additions):

```dotenv
OPTIONAL_AGENTS=true
MOOSENGER_SRC=/abs/path/to/moosenger            # or https://<host>/<group>/moosenger.git#<tag>
MOOSE_MCP_AUTH_KEY=<random string>              # shared with the MCP server
MOOSENGER_LLM_HOST=https://litellm.inl.gov/     # default
MOOSENGER_MODEL=gpt-5-1-gov-va                  # default
MOOSENGER_EMBEDDINGS=text-embedding-3-large-gov-va
# only when using the sidecar:
MOOSE_IMAGE=<moose image>@sha256:<digest>
MOOSE_MCP_EXE=/opt/moose/modules/combined/combined-opt
```

Local additions go in `platform/docker-compose.override.yml`, which the
Makefile auto-includes and git ignores. The MOOSE execution sidecar is not part
of `make generate` (the static tests want only PrometheusAgents in
`agents/**/docker-compose.yml`), and a local MOOSE checkout is a host bind
mount, which agent compose files may not declare:

```yaml
# platform/docker-compose.override.yml
include:
  - agents/optional/moosenger-agent/docker-compose.moose-mcp.yml   # sidecar
services:
  moosenger-agent:
    volumes:
      - /abs/path/to/moose:/moose:ro                               # MOOSE checkout
```

Then:

```bash
cd platform
make generate          # picks up agents/optional/moosenger-agent/docker-compose.yml
make up                # builds the image (slow the first time: LangChain stack)
make logs SERVICE=moosenger-agent
curl -s -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents | python -m json.tool | grep -i moosenger
```

The healthcheck has a 180 s `start_period` because startup validation and
warmup run before `/healthz` answers.

## Development

```bash
cd platform/agents/optional/moosenger-agent
uv lock                                  # uv.lock is required by the Dockerfile
uv venv && uv pip install pytest pytest-asyncio ../../../../sdk
uv pip install /path/to/moosenger        # optional; without it the tests skip
.venv/bin/python -m pytest               # smoke: packaged card builds on this SDK
```

The wrapper's behavior tests (response shaping, artifacts, `INPUT_REQUIRED`
round-trip, long-running declaration, startup bridging) live in the MOOSEnger
repository under `tests/a2a/`, next to the code.

## Environment reference

| Variable | Default | Purpose |
|---|---|---|
| `MOOSENGER_PROJECT_DIR` | `/workspace` | Config, vector DB, knowledge, session workspaces (volume) |
| `MOOSENGER_CONFIG` | `/app/config/moosenger.yaml` | Template rendered at startup; or a hand-written file with `MOOSENGER_RENDER_CONFIG=false` |
| `MOOSENGER_API_KEY` | (empty → `LLM_API_KEY`) | Key for MOOSEnger's LLM endpoint, exported as `OPENAI_API_KEY` |
| `MOOSENGER_LLM_HOST` / `MOOSENGER_MODEL` / `MOOSENGER_EMBEDDINGS` | INL LiteLLM values | MOOSEnger `core` / `rag` settings |
| `MOOSE_MCP_URL` | `http://moose-mcp:8000/mcp` | MOOSE execution server |
| `MOOSE_MCP_AUTH_KEY` | (empty = no auth) | Shared secret with that server |
| `MOOSENGER_A2A_WARMUP` | `true` | Run warmup at startup (vector DB pull, syntax data, MCP probe) |
| `MOOSENGER_A2A_WARMUP_DOWNLOAD` | `auto` | Pull the vector DB from the ORAS registry if missing |
| `MOOSENGER_A2A_WARMUP_COMPILE` | `false` | Never compile syntax/executable in the container |
| `MOOSENGER_STARTUP_STRICT` | `false` | Exit on startup failure instead of serving `backend_unavailable` |
| `MOOSENGER_EXECUTION_ESTIMATE_SECONDS` | `600` | Hint sent with `declare_long_running` |
| `MOOSENGER_TRACE_TOOLS` | `false` | Dump MOOSEnger's tool trace into the container log |

## Known limitations

* Progress inside a MOOSEnger turn is not streamed (the runtime returns only
  when the turn ends); the base class heartbeat keeps the connection alive.
* Only text outputs (`.i`, logs) are published; Exodus/CSV results stay in the
  MCP server's run directory.
* The agent is not in the `platform-agent` CI matrix: that job installs only
  the SDK and this directory's lock, so the smoke tests would skip.
* MOOSEnger's LLM settings are configured separately from the platform's
  `LLM_CONFIG_PROFILE` (same key, separate host/model).
