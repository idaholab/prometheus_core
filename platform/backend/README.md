# backend

Standalone FastAPI service that replaces Chainlit's server role for the Prometheus
Platform, exposing its own JSON/SSE contract. It has **zero Chainlit dependency** and
talks to the client-agent over A2A JSON-RPC (Bearer `AGENT_SECRET`), using Valkey/Redis
for session and conversation state.

The React frontend (`frontend/`) is rewired onto this backend's contract separately;
the old Chainlit app has been removed.

## Layout

```
backend/
  pyproject.toml
  app/
    main.py          # FastAPI() + lifespan + router mounts
    config.py        # pydantic-settings loader
    config.yml       # default configuration
    routers/
      health.py      # GET /healthz
  tests/
```

## Development

Requires Python 3.12+ and `uv` (the backend image is built on Python 3.12; the app also runs on 3.13).

```bash
uv sync
uv run alembic upgrade head          # once, and after pulling a new migration
uv run uvicorn app.main:app --port 8600
curl localhost:8600/healthz          # {"status":"ok"}

uv run ruff check
uv run mypy app/
uv run pytest
```

The `alembic upgrade head` step is **not optional locally**: the app used to migrate
itself from its lifespan, and no longer does (see *Multi-worker* below). Skipping it
gives you a backend that starts and then fails on the first admin-plane query.
`uv run pytest` needs no database — the suite runs against SQLite and `fakeredis`.

## Configuration

`app/config.py` loads `app/config.yml` (override the path with `PROMETHEUS_CONFIG_PATH`).
Environment overrides:

| Env var | Setting |
|---------|---------|
| `CLIENT_AGENT_URL` | `agent_url` |
| `AGENT_SECRET` | `agent_secret` |
| `REDIS_URL` | `redis_url` |
| `PROMETHEUS_MAX_UPLOAD_BYTES` | `max_upload_bytes` (default 100 MB) |
| `BACKEND_JWT_SECRET` | `jwt_secret` |
| `BACKEND_COOKIE_NAME` | `cookie_name` |
| `BACKEND_TOKEN_TTL_SECONDS` | `token_ttl_seconds` |
| `PROMETHEUS_MESH_CACHE_DIR` | `mesh_cache_dir` |
| `PROMETHEUS_MESH_WORKERS` | `mesh_workers` (default 2) |
| `PROMETHEUS_MESH_TIMEOUT_SECONDS` | `mesh_timeout_seconds` (default 120) |
| `BACKEND_WORKERS` | uvicorn worker count (read by `docker-entrypoint.sh`, not `config.py`; default 1) |

Default host port is **8600** (wired into compose/nginx in task 09).

### Mesh conversion runs out-of-process

Exodus/STL → VTP conversion (`app/services/mesh/service.py`) runs in a spawn-based
`ProcessPoolExecutor`, not in the web process. VTK is a C++ library reached through Python
bindings: a segfault or an OOM kill inside it would otherwise take the interpreter — and every
live conversation — down with it. In a child it costs exactly one artifact, which degrades to a
file download. Each worker is retired after a single conversion (`max_tasks_per_child=1`)
because VTK does not reliably release memory between datasets.

Consequences worth knowing:

- `PROMETHEUS_MESH_WORKERS` is **per web worker**. With `BACKEND_WORKERS=N` the peak child
  count is `N × PROMETHEUS_MESH_WORKERS`, and all of it counts against the container's
  `BACKEND_MEM_LIMIT`.
- A conversion exceeding `PROMETHEUS_MESH_TIMEOUT_SECONDS` cannot be cancelled cooperatively, so
  the pool's workers are killed. That can also abort a conversion running concurrently; it
  degrades down the same "no mesh data" path.
- `PROMETHEUS_MESH_CACHE_DIR` should be a persistent volume (compose mounts the `mesh-cache`
  named volume at `/var/cache/prometheus-mesh`). The cache is content-hash keyed, so anything it
  retains is a conversion never repeated — including when a past conversation is reopened.

### Session state lives in Valkey

Everything a logged-in browser session carries is in Valkey, keyed by the JWT `sid`, not in
process memory (`app/sessions.py`). The two `session:` keys carry the cookie's TTL and are
refreshed on every write, so there is no reaper; the logout marker carries its own TTL:

| Key | Type | Holds |
|-----|------|-------|
| `session:{sid}` | HASH | `conversation_id`, `profile`, `consecutive_needs_info`, `artifacts` (JSON array), `bind_seq` |
| `session:{sid}:awaited` | SET | root task ids this session is waiting on |
| `revoked:sid:{sid}` | STRING | logout marker, TTL = the token's remaining lifetime |

Two consequences for anyone touching this code:

- **`SessionState` is a frozen snapshot, not the live object.** A mutation would not reach Valkey, so it
  raises instead. Every former in-place mutation is an explicit `SessionStore` coroutine
  (`ensure_conversation`, `reset`, `set_artifacts`, `bump_needs_info`, `await_task`, `claim_task`, …).
- **`claim_task` is the exactly-once primitive** for announcing a finished background task. It is
  a single `SREM` whose return count *is* the claim, so the subscriber loop, the fast-finish
  guard and the router's reconcile can all race it and exactly one wins — atomically, and across
  workers.

A restart therefore no longer forks the conversation, drops the SSE task subscriber or wipes the
artifact catalog. Valkey being unreachable does mean chat cannot work: sessions are core state,
so a request fails (a 503 on `GET /api/events`, a 500 elsewhere) rather than seeing a confusingly empty session.

### Multi-worker

`BACKEND_WORKERS` is a real dial now; it was previously *incorrect* rather than merely untuned,
because two workers would have disagreed about every session. What made it valid:

- session state, revocation and the SSE event bus (Valkey pub/sub on `sse:{sid}`, so a status
  event published by the worker handling the turn reaches the worker holding the tab) are all
  out of process;
- `alembic upgrade head` moved out of the app lifespan and into `docker-entrypoint.sh`, so it
  runs once per container instead of once per worker. `alembic/env.py` additionally takes a
  Postgres advisory lock before running migrations, which covers two containers — or a developer
  running the CLI against a booting one — starting together.

The default stays **1**. Raising it is a deliberate operational decision, and remember that
`PROMETHEUS_MESH_WORKERS` is per web worker, so the peak VTK child count is the product.
