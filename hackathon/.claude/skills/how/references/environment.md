# Environment: prerequisites, .env files, and the base image

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

The laptop needs (deck 01, homework; deck 03, bonus; each has a check in `checks.md`): Docker
with Compose 2.20+ (`docker`), make, git, uv and Python 3.12 (`tools`), a clone of
`github.com/idaholab/prometheus_core` (`repo-access`, `siblings`), `LOCAL_SDK=true` for the base image
(`base-image-pin`), an LLM profile and key (`llm-key`), and a local DeepLynx (`deeplynx-env`).

## Fill the platform .env

In the platform folder, `make init-env` (also run by every `make up`): it copies `.env.example`,
fills every blank secret (`AGENT_SECRET`, `REDIS_PASSWORD`, `ADMIN_DB_PASSWORD`, `BACKEND_JWT_SECRET`,
`ADMIN_DB_ENCRYPTION_KEY`, …) without printing it, and shows the LLM profile menu and the hidden key
prompt while `LLM_CONFIG_PROFILE` or its key is empty (`scripts/init_env.py`). You add by hand:
`LOCAL_SDK=true` and the `DEEPLYNX_*` lines from your local DeepLynx. Keep `REDIS_URL` and
`BACKEND_PORT=8600` as they are. There are no `LITELLM_*` values any more.

Two traps: `ADMIN_DB_PASSWORD` is fixed at the first start (a change gives `password
authentication failed for user "admin"`; restore it, or `make down-v`). A new value makes the
agent copy stale: run `agent-env-sync`, then `make up` in the agent folder.

## The base image

The client-agent and every agent build `FROM` the `prometheus_api` base image, which holds
`prometheus_api`, `a2a-sdk` 1.x, starlette, and uvicorn (deck 02, appendix): never list them in
`pyproject.toml`. With `LOCAL_SDK=true` it is `prometheus_api:local`, built from `../sdk` by `make
base-image` (automatic in `make up`). The backend builds on its own image and needs none.

## The pin rule

1. `LOCAL_SDK=true` in the platform `.env` (or the shell) wins: repo `prometheus_api`, tag `local` (`Makefile:19-31`).
2. Else an uncommented, non-empty `PROMETHEUS_API_BASE_IMAGE_HASH=` line, else the Makefile `?=` value,
   pulled from `containers.github.inl.gov` (needs `registry-login`).

An empty `PROMETHEUS_API_BASE_IMAGE_HASH=` line gives "invalid reference format". A plain `docker
compose up` with `LOCAL_SDK=true` breaks when `prometheus_api:local` was never built: always use
`make`. `setup_agent.py` copies `LOCAL_SDK=true` into the agent `.env` (`agent-base-image`).

## Your agent's .env

`setup_agent.py` copies `AGENT_SECRET`, `REDIS_PASSWORD`, `USER_IDENTITY_PUBLIC_KEY`,
`USER_IDENTITY_ISS`, `USER_IDENTITY_AUD`, `LLM_CONFIG_PROFILE`, `LLM_API_KEY`, `EMBEDDING_API_KEY`,
`DEEPLYNX_*`, and `LOCAL_SDK=true` (`setup_agent.py`; `--env-only <dir>` refreshes an existing agent).
The agent compose sets `REGISTRY_URL=http://backend:8000` and `LITELLM_MASTER_KEY: ${AGENT_SECRET}`
(the SDK's name for the registry token). External mode: `REGISTRY_URL=http://prometheus.host.internal:8600`.
Add `USER_IDENTITY_REQUIRED=false` only when the platform sets it. After each edit, `make up` in the agent folder.

## First login and the signing key

Open http://localhost:5150 and complete the setup wizard (the first user is admin). The backend has
already created and activated the signing key (it needs `ADMIN_DB_ENCRYPTION_KEY`); Admin › Signing
Keys is only for rotation. Without an active key every turn fails with "No 'userToken' found…"
(deck 03; `admin-user`, `signing-key`). Never commit or paste a
`.env`. This repository ignores `.env*`; check with `git check-ignore -v <agent>/.env`.
