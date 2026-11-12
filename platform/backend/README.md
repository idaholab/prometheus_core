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
      health.py      # GET /healthz (liveness), GET /readyz (readiness)
  tests/
```

## Development

Requires Python 3.12+ and `uv` (the backend image is built on Python 3.12; the app also runs on 3.13).

```bash
uv sync
uv run alembic upgrade head          # once, and after pulling a new migration
uv run uvicorn app.main:app --port 8600
curl localhost:8600/healthz          # {"status":"ok"}  (liveness: no dependencies)
curl localhost:8600/readyz           # 200 if Valkey + admin-db answer, else 503

uv run ruff check
uv run mypy app/
uv run pytest --cov
```

CI fails if coverage drops below `fail_under` in `[tool.coverage.report]`, the lowest total across the supported Python versions. Raise it as coverage improves; never lower it. Running a subset of tests with `--cov` will fail the floor, so leave `--cov` off for targeted runs.

The `alembic upgrade head` step is **not optional locally**: the app used to migrate
itself from its lifespan, and no longer does (see *Multi-worker* below). Skipping it
gives you a backend that starts and then fails on the first admin-plane query.
`uv run pytest` needs no database — the suite runs against SQLite and `fakeredis`.

### OpenAPI document

`openapi/openapi.json` is the OpenAPI document the backend serves at `/openapi.json`:
every URL and method, the parameters it reads, the statuses it returns, the shape of
its request and response bodies, and their documentation. It's committed so that an
API change can't slip through unnoticed. Renaming a response field from `title` to
`name` passes every unit test while the frontend, which still reads `title`, breaks.

Regenerate it after changing a route, a model or the API's documentation, and commit
the diff alongside the change:

```bash
uv run python scripts/export_openapi.py
```

The JSON diff then shows up in the PR, so reviewers see exactly which endpoints
changed without digging through the code. Nobody needs to read the file itself; it's
long because it lists every endpoint in full. Only its diff matters. Because it
includes the documentation, editing a summary, description or example changes it
too, so check whether a diff changes a field, a parameter or a status, or only its
wording. On a merge conflict, regenerate it rather than resolving it by hand.

CI's `platform: backend openapi` job regenerates the document and fails if that
changes the committed file, printing the diff. It then checks that the document is
complete, such as that every route declares its authentication, by linting it with
[Redocly](https://redocly.com/docs/cli/). Problems show up on the lines of
`openapi/openapi.json` in a PR. The rules are in `openapi/redocly.yaml`: Redocly's
`recommended-strict` set, which fails on warnings too, with each rule that doesn't
apply turned off and the reason given. The problems the document had when the lint
was added are listed in `openapi/.redocly.lint-ignore.yaml`, one rule at one location
each, so new problems still fail. Remove an entry when you fix it; don't add new ones,
except for the existing problems of a rule you add to `redocly.yaml`. To run it locally
(needs Node):

```bash
cd openapi && npm ci && npm run lint
```

### Documenting a route

The document is generated from the code, so each piece of a route's documentation is
written once, in the place FastAPI reads it:

| What | Where it goes |
|------|---------------|
| operationId | The handler's function name, such as `get_recent_conversations`, so name it for what the route does. `app.openapi.operation_id` sets it, and handler names must be unique across routers |
| Summary | `summary="List recent conversations"` on the route decorator: short and imperative |
| Description | The handler's docstring: what the route does, its side effects, and how it orders with other calls, written for API consumers. Notes for backend developers go after a `\f` line, which FastAPI leaves out of the document |
| Parameters | `Annotated[int, Query(ge=1, le=100, description="…")]`, with the limits as constraints rather than prose |
| Request and response bodies | Pydantic models, with `response_model=`. Don't parse the raw `Request` |
| Model fields | `Field(description="…")`, plus `examples=` on request bodies that aren't trivial |
| Errors | `responses=` built from the shared entries in `app/api_responses.py`, plus the route's own errors |
| Authentication | `Depends(current_claims)`, `current_user` or `require_admin` from `app/security.py`, or `require_agent_secret` on the agent registry. Never a bare `APIKeyCookie` or `HTTPBearer`: those only check that a credential is present, not that it's valid. Until these dependencies declare security schemes ([PPLT-339](https://nstinl.atlassian-us-gov-mod.net/browse/PPLT-339)), a new route fails `security-defined` |
| Streams, files and redirects | `response_class=`, plus the right content type in `responses=` |
| Tag | One, from the catalog in `app/openapi.py` |

For example:

```python
@router.get(
    "/conversations/recent",
    summary="List recent conversations",
    response_model=ConversationHistoryResponse,
    responses=AUTH_RESPONSES,
)
async def get_recent_conversations(
    limit: Annotated[int, Query(ge=1, le=100, description="Most conversations to return.")] = 20,
    claims: TokenClaims = Depends(current_claims),
) -> ConversationHistoryResponse:
    """The caller's most recent conversations, newest first.

    When conversation history is unavailable, answers 200 with `available: false`
    and no conversations, rather than an error.
    \f
    Reads ConversationStateClient in a worker thread because it's synchronous.
    """
```

Don't list parameters, types or return values in the docstring. FastAPI doesn't read
them, so they repeat the signature and drift out of date.

The lint checks the parts of this it can: a unique operationId, a description, a
description on every parameter and model field, a schema on every success response,
one declared tag, and a declared security scheme. It also checks the naming rules
below.
Reviewers check the rest:

- **Summary.** FastAPI makes one from the function name when `summary=` is missing,
  so the lint can't tell a written summary from a generated one.
- **Errors.** The lint can't see which errors a handler raises, so it can't check that
  `responses=` lists them all.
- **Response shape.** The lint only sees the declared response, so it can't check that
  the route really returns it.

New routes follow the [Zalando RESTful API
guidelines](https://opensource.zalando.com/restful-api-guidelines/), which match the
existing API: kebab-case paths (`/api/admin/signing-keys`), and snake_case field and
parameter names. Existing routes aren't being redesigned to fit the guide; a change to
one goes through the same review as any other API change.

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
  named volume at `/cache/prometheus-mesh`). The cache is content-hash keyed, so anything it
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
