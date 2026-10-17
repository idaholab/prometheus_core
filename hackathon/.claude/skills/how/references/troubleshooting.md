# Troubleshooting

Facts as of `prometheus_api` 95c32b5 (v0.13.0) and `prometheus_platform` `dev` 22fed42, 2026-10-05. When the code disagrees with this file, the code is correct.

The deck symptom tables (deck 03, slides 11, 17, A18-A21; deck 04, slide 19; deck 05). Run the
named checks of `checks.md` to confirm. Around a platform `make up`/`restart`/`down`, run
`make down`, then `make up`, in your agent folder.

## The stack won't start

| symptom | cause → fix | checks |
|---|---|---|
| `failed to resolve …prometheus_api:` or `invalid reference format` | An empty `PROMETHEUS_API_BASE_IMAGE_HASH=` line, or `docker compose` without `make`. Remove the line; start through `make`. | [base-image-pin](checks.md#base-image-pin) |
| `unauthorized` or `denied` on the base image | No registry login, no `read:packages`, or off the INL network. Log in in your own terminal. | [registry-login](checks.md#registry-login) |
| `port is already allocated` | An old stack or another process. `make down` there, or change the `*_PORT` value. | [ports-free](checks.md#ports-free) |
| The backend exits: "jwt_secret is not configured" | `BACKEND_JWT_SECRET` empty or `change-me…`. Generate it. | [platform-env](checks.md#platform-env), [backend-logs](checks.md#backend-logs) |
| `[ERROR] .env does not exist.` | `cp .env.example .env`, then fill it (`environment.md`). | [platform-env](checks.md#platform-env) |
| "Docker is installed, but the Docker daemon is unavailable" | Start Docker Desktop. | [docker](checks.md#docker) |
| `network … has active endpoints` | Your agent is still on the network. `make down` in the agent folder first. | [agent-running](checks.md#agent-running) |
| The backend exits in an alembic step; `password authentication failed for user "admin"` | `ADMIN_DB_PASSWORD` changed after the first start. | [backend-logs](checks.md#backend-logs) |
| SSL or certificate errors in `npm ci` or `pip` | TLS inspection. Pull the latest platform `dev` (`certs/INL.pem`). | [platform-current](checks.md#platform-current) |
| Build killed, exit code 137 | Out of memory. Raise the Docker Desktop limit. | [docker](checks.md#docker) |
| Downloads time out behind a proxy | Set `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` (with `backend`, `admin-db`, your agents) in the `.env`. | - |

## My agent is missing or never called

| symptom | cause → fix | checks |
|---|---|---|
| My agent is not in `/agents`, or it disappeared | The platform restarted and emptied the registry. `docker restart <container>`, then a discovery refresh. | [agent-running](checks.md#agent-running), [registry-agents](checks.md#registry-agents), [agent-registered-log](checks.md#agent-registered-log), [discovery-refresh](checks.md#discovery-refresh) |
| Listed, but never called | A weak `description` or `usage_notes`, a duplicate skill id, an unreachable or old card. Try other phrasings in fresh conversations, then `/diagnose trace my last chat` and `/create-agent improve my card`. | [registry-details](checks.md#registry-details), [card-in-image](checks.md#card-in-image), [client-agent-reaches-agent](checks.md#client-agent-reaches-agent), [discovery-refresh](checks.md#discovery-refresh) |
| `make up` fails: "The Prometheus Platform must be launched first…" | The platform network is missing. Start the platform. | [stack-ps](checks.md#stack-ps) |
| Called with the wrong arguments | Weak parameter descriptions, or the previous result lacks a value. Trace the turn, then improve the card. | [card-in-image](checks.md#card-in-image) |
| "Registry registration attempt … failed" or "Continuing without registration" | A 401: the agent's `LITELLM_MASTER_KEY` differs. A connection error: LiteLLM is down, or the network mode is wrong. | [agent-registered-log](checks.md#agent-registered-log), [agent-env-sync](checks.md#agent-env-sync), [litellm-health](checks.md#litellm-health) |
| The agent container exits or restarts | Read the traceback: often `ModuleNotFoundError`, or "AGENT_SECRET_REQUIRED=true but AGENT_SECRET is not set". | [agent-running](checks.md#agent-running), [agent-logs](checks.md#agent-logs) |
| The chat still uses the old card or code | `docker restart` keeps the old image. `make up`, then a discovery refresh. | [card-in-image](checks.md#card-in-image), [discovery-refresh](checks.md#discovery-refresh) |
| Two agents replace each other in `/agents` | Same card name, same route key (deck 05, slide 1). Use your own names. | [registry-details](checks.md#registry-details) |
| "Capability '<skill_id>' is currently unavailable." | The client-agent did not discover the skill. | [registry-agents](checks.md#registry-agents), [client-agent-reaches-agent](checks.md#client-agent-reaches-agent) |

## An error in the chat or the logs

| symptom | cause → fix | checks |
|---|---|---|
| Every chat turn fails: "No 'userToken' found…" | No active signing key: Admin › Signing Keys → generate, activate. Only your agent fails: `USER_IDENTITY_REQUIRED` differs. | [signing-key](checks.md#signing-key), [identity-required-match](checks.md#identity-required-match) |
| An LLM call gets HTTP 401 | In this order: under `registry` the code does not attach the master key; the key is missing in the agent `.env`; the key does not reach the container. | [llm-master-key-pattern](checks.md#llm-master-key-pattern), [llm-key-in-agent-env](checks.md#llm-key-in-agent-env), [llm-key-in-container](checks.md#llm-key-in-container) |
| `LLMAliasError: LLM alias 'small' is not available` | `registry` has only `medium`. Use a listed flavor, an own `LLM_CONFIG_FILE`, or another profile. Never edit `litellm_config.yaml` (deck 03, A19 says to). | [llm-flavors](checks.md#llm-flavors), [llm-models](checks.md#llm-models) |
| `ModuleNotFoundError` in the container | No `COPY` line for your module, or the package is not in `pyproject.toml`. | [dockerfile-copy](checks.md#dockerfile-copy), [agent-logs](checks.md#agent-logs) |
| "Unknown LLM config profile" | A typo, or an image without that profile. | [llm-profile-valid](checks.md#llm-profile-valid) |
| "Identity verification failed: userToken has expired" | The turn took longer than `USER_IDENTITY_TTL` (7200 s). Raise it. | - |
| "Identity verification failed: …issuer mismatch", "…audience mismatch", "No matching key found in JWKS" | Stale `USER_IDENTITY_*` in the agent `.env`, or a key the JWKS does not list. | [agent-env-sync](checks.md#agent-env-sync), [signing-key](checks.md#signing-key) |
| HTTP 401 from LiteLLM on a `curl` | The `Authorization: Bearer $LITELLM_MASTER_KEY` header is missing or wrong. | [registry-auth](checks.md#registry-auth) |
| "Error during execution" with a traceback | An exception in your code. Read it; trace the turn for the arguments. | [agent-logs](checks.md#agent-logs) |
| A `curl` to my agent returns `-32601`, `-32009`, `-32603`, `-32004`, or 401 | See "A2A errors" in `run-and-register.md`. | - |
| "Live updates stopped — the server is unreachable" | The backend or Valkey restarted. Reload the page. | [store](checks.md#store), [backend-health](checks.md#backend-health) |

## Files, uploads, plots, or DeepLynx

| symptom | cause → fix | checks |
|---|---|---|
| An upload says "…but DeepLynx storage is not configured." | Set `DEEPLYNX_*` in the platform `.env`, then `make restart`. | [deeplynx-env](checks.md#deeplynx-env), [deeplynx-backend](checks.md#deeplynx-backend) |
| The plot does not render | Publish with `mime_type="image/png"` and configure DeepLynx (`artifacts.md`). | [deeplynx-agent](checks.md#deeplynx-agent), [agent-logs](checks.md#agent-logs) |
| A `deeplynx://` URI does not resolve | The agent needs the same org and project. Re-sync `DEEPLYNX_*`. | [agent-env-sync](checks.md#agent-env-sync), [deeplynx-agent](checks.md#deeplynx-agent) |
| `AuthenticationError` or 401 from DeepLynx | Key and secret swapped or cut. Generate a new key. | [deeplynx-backend](checks.md#deeplynx-backend) |
| `ValueError: invalid literal for int() with base 10: ''` | `DEEPLYNX_ORG_ID` or `DEEPLYNX_PROJECT_ID` is empty. | [deeplynx-env](checks.md#deeplynx-env) |
| "Failed to get data source ID…" | Set `DEEPLYNX_DATA_SOURCE_ID` and add it to `environment:` (no compose file forwards it). | - |
| Connection refused to `prometheus.host.internal` | Check DeepLynx listens on `0.0.0.0:5000` and the host firewall allows the Docker bridge. `host.docker.internal` does not exist on Linux; use `prometheus.host.internal`. | [deeplynx-backend](checks.md#deeplynx-backend) |
| Nothing on :5000 (macOS) | The AirPlay Receiver holds it. Turn it off, or remap the port. | [ports-free](checks.md#ports-free) |
| "<name> exceeds the <n> byte upload limit" | Larger than `PROMETHEUS_MAX_UPLOAD_BYTES` (100 MiB). | - |

## Git and pull requests

See `git-pr.md`. No fork access: ask a mentor for the team `open`. `gh` talks to github.com:
`export GH_HOST=github.inl.gov`. After a rebase, push with `--force-with-lease`, own branch only.

## The reset ladder

From the least to the most destructive (deck 03, A21). Each needs your yes, except a restart of
your own agent. Each step after the first empties the registry.

| step | you lose |
|---|---|
| `docker restart <name>` | the work in progress of that container |
| `make restart` / `make up` | the agent registry (`make up` also builds) |
| `make clear-admin-users` | all users: the setup wizard runs again |
| `make down-v` | all volumes: conversations, sessions, registry, users, signing keys, identity providers, mesh cache |

## Debug commands

Use `docker logs --tail 100 <container> 2>&1` (`make logs` never ends; `litellm` runs in
`litellm-proxy`). Read Valkey only with the container's own password, as in `activity`. The images
have no `curl`: use `python -c "import urllib.request …"`. Deck commands that print secrets: never
pipe `/v1/agents` to `json.tool`, never `export GITHUB_PAT` (use `read -rs`).
