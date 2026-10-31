# notebook-render

Serves the baked HTML reports of agent-generated UQ notebooks. Container port
**8000** (the platform convention on `agent-network`); compose maps it to
**8876** on the host for hybrid dev. The browser reaches it same-origin at
`/notebook/...`, through the Vite dev proxy (`frontend/vite.config.ts`) or the
nginx `location /notebook/` block.

## What it does

A UQ agent writes `uq_<model>_<timestamp>.ipynb` and a sibling, fully baked
`.html` (nbconvert, images embedded, figures baked) into `NOTEBOOK_DIR`, the
`uq-notebooks` volume.

| Endpoint | Purpose |
|---|---|
| `GET /render/{artifact_id}` | Serve the baked HTML report as-is. No live kernel, so it renders on load and never comes up blank. The opaque id is mapped to its filename through the platform artifact registry (Valkey, read-only), falling back to `{artifact_id}.html`. |
| `GET /health` | Liveness. |

Both routes are also registered under `/notebook/`, since the frontend proxies
keep that prefix. The browser only ever sees same-origin relative paths; no
host, no `file://`, no secret. Configuration is env-driven (`NOTEBOOK_DIR`,
`REDIS_URL`, `REDIS_PASSWORD`).

## Building (corporate CA)

The image is **not** built on the `prometheus_api` base (it runs no agent
code), so it does not inherit that base's trusted CA store. Its `pip install`
still has to reach PyPI, which behind a TLS-intercepting proxy needs that
proxy's CA. The Dockerfile trusts it the same way the frontend and backend
images do, from the `certs` build context (`additional_contexts: { certs:
../common/certs }`). Without it a fresh `make up` fails with
`CERTIFICATE_VERIFY_FAILED`.

## Tests

`cd platform/notebook-render && python -m pytest`: render, registry lookup,
traversal guard and health.
