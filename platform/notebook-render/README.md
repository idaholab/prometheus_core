# notebook-render

Static baked-HTML server for UQ notebook reports, plus a dormant secret-safe
re-run proxy. One process, one origin. Container binds port **8000** (platform
convention on `agent-network`); the compose host-port map exposes it at **8876**
for hybrid dev, which is where the vite dev proxy `/notebook` points.

> **Migration note (2026-09-02):** `upstream/dev` (PR #91) removed this service
> along with the old Chainlit frontend. Now re-ported onto the React `frontend/`
> . It is reached purely through the frontend
> proxy — the vite dev `/notebook` key (`frontend/vite.config.ts`) and the nginx
> `location /notebook/` block (`frontend/nginx.conf`) — since the new stack has
> no Chainlit ASGI mount. The dual bare-and-`/notebook`-prefixed route
> registration means proxy.py itself needs no change.

## What it does

The UQ agent (`~/projects/multiphysics-uq-agent`, its own repo) writes both
`{artifact_id}.ipynb` and a sibling fully-baked `{artifact_id}.html`
(nbconvert, images embedded, Plotly as `<div>`s) into `NOTEBOOK_DIR`.

| Endpoint | Purpose |
|---|---|
| `GET /render/{artifact_id}` | Serve the baked static HTML report as-is. No Voila, no live kernel, no WebSocket — renders on load, never blanks on a kernel starve. |
| `GET /result/{artifact_id}` | Return the full `uq_result` (`parameters` + per-sample `samples` + `metrics`) extracted from the notebook's data cell. This is the data source the standalone 3D UQ console's `?result=…` link points at. Not on the A2A wire. |
| `POST /rerun` | **Dormant** structured re-invocation. Nothing calls it today. Injects the `AGENT_SECRET` Bearer server-side (never reaches the browser), re-invokes the UQ agent's `/api/chat` (or the client-agent when `RERUN_ROUTE=client-agent`), then extracts the full `uq_result` from the freshly written notebook. See `docs/docs/dev-docs/rerun-invocation-path.md`. |
| `GET /health` | Liveness. |

The browser only ever sees same-origin relative paths; no host, no `file://`,
no secret. All config is env-driven (`NOTEBOOK_DIR`, `RERUN_ROUTE`, agent URLs,
`AGENT_SECRET`) — nothing hard-coded.

## Building (corporate CA)

This image is **not** built on the `prometheus_api` base (it runs no agent
code — plain `python:3.12-slim`), so it does not inherit that base's trusted
CA store. Its `pip install` still has to reach pypi.org, which behind a
TLS-intercepting corporate proxy needs that proxy's CA. The Dockerfile therefore trusts the corporate
CA the same way the `frontend`/`backend` images do: it `COPY --from=certs
ca-bundle.pem …` and runs `update-ca-certificates`, and the compose service
supplies that bundle via `additional_contexts: { certs: ./certs }`. Do not
remove either half — without it a fresh `make up` fails on
`CERTIFICATE_VERIFY_FAILED (unable to get local issuer certificate)` while
resolving `voila`/etc. from PyPI.

## Run (hybrid dev)

Started as a host process by `dev.sh` in the `prom` tmux session (window on
:8876). See the canonical launch commands in the UQ agent README; do not
reconstruct from `ps`. Health check: `curl -s localhost:8876/health`.

## Tests

`cd notebook-render && python -m pytest` — proxy endpoint tests (render/result/rerun).
