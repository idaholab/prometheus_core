### Backend

You own the FastAPI service in `platform/backend/` (Python 3.12+, uv, Ruff, mypy, Alembic,
Valkey, Postgres). Review the change as the person who will be paged for it:

1. **The contract:** does `app/contract.py` still agree with `CONTRACT.md` and with the frontend
   types in `platform/frontend/src/lib/api/`? Is a change backward compatible for a frontend
   that is one release behind? Do base-image (`prometheus_api`) types stay off the wire?
2. **No per-process state:** sessions, logout markers and the SSE bus live in Valkey, and
   `SessionState` is a frozen snapshot that changes only through a `SessionStore` coroutine. Does
   the change keep `BACKEND_WORKERS` > 1 correct? Look for module-level caches, in-memory dicts
   keyed by session or conversation, and background tasks tied to one worker.
3. **Async correctness:** blocking calls in `async` code (sync I/O, CPU-heavy work like mesh
   conversion outside its subprocess), missing timeouts on httpx and Valkey calls, cancelled SSE
   streams that leak a subscription, and error paths that leave a turn hanging.
4. **Auth and isolation:** every new route has the right dependency (session, admin), a user
   can't read another user's conversation, upload or artifact, and errors don't leak internals.
5. **Data:** a schema change has an Alembic migration that upgrades and downgrades and is safe on
   a populated database. Run `uv run alembic upgrade head` against a temp SQLite database or a
   throwaway Postgres, and run `alembic check` if CI does.
6. **Checks:** unless the `ruff` and `platform: backend python` CI jobs passed on this commit, run `cd platform/backend && uv run ruff check && uv run ruff format --check &&
   uv run mypy app/ && uv run pytest` (no database or Valkey needed; it uses SQLite and
   `fakeredis`). Say which behavior changed without a test, and name the simplest test, in
   `tests/`, that would cover it.

Read: the diff; `platform/backend/README.md` (above all "Session state lives in Valkey" and
"Multi-worker"); `CONTRACT.md`; `app/main.py` and the routers and services the change touches;
`platform/docs/docs/dev-docs/multi-user-setup.md` for identity changes.
