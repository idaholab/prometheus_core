---
title: Your Local Platform
footer: Day 1 · Your local platform
accent: dep
index:
  time: '1:45'
  heading: Your local platform
  color: var(--sky)
  blurb: What runs where, four commands and the registry-wipe trap, first login, health checks, reference agents, which LLM profile your agents use, a local DeepLynx (required), the likeliest problems.
---

# Your local platform {.title kicker="Day 1 · 1:45 pm" pills="All participants | 45 min | internals in the appendix"}
You started it at home. Now: what it runs for your agent, how to tell it is healthy, which LLM profile it uses, your local DeepLynx, and what to do when something is off.

---

## By the break, your platform is ready for an agent {eyebrow="Goal"}

:::: grid 4
::: card acc
<div class="kpi"><span class="v">1</span></div>

### Healthy

{.small}
All services up, and you know where to look when one isn't.
:::

::: card acc
<div class="kpi"><span class="v">2</span></div>

### Logged in

{.small}
An admin user. The signing key is created for you.
:::

::: card acc
<div class="kpi"><span class="v">3</span></div>

### LLMs answer

{.small}
You have a key for an LLM profile.
:::

::: card acc
<div class="kpi"><span class="v">4</span></div>

### Files work

{.small}
A local DeepLynx: agents won't start without it.
:::
::::

::: callout info
Platform not starting yet? Work through the bonus slides at the end of this deck with a mentor.
:::

---

## Three addresses you need {eyebrow="What runs"}

{widths="330px||"}
| Address | What it is | You use it to… |
|---|---|---|
| `http://localhost:5150` | the chat UI | test your agent like a user {.hl} |
| `http://localhost:8600` | the backend: also the agent registry and gateway | check health (`/healthz`), list registered agents (`/v1/agents`) |
| `http://localhost:3000` | your local DeepLynx | see uploads and result files |

{.body}
Behind them: the orchestrator (`client-agent`), two agents, a state store (Valkey), and the admin database. They talk to each other on the Docker network `prometheus_platform_agent-network`, which your agent joins too.

---

## Once, then four commands {eyebrow="Day to day"}

:::: grid 2 gap=30px
```bash {.sm hl=3-4}
cd ~/prometheus/prometheus_core/platform

make init-env                  # once: creates .env (next slide)
echo "LOCAL_SDK=true" >> .env  # once: base image from ../sdk

make up                        # build, start, wait, make check
make restart                   # restart, no rebuild
make logs SERVICE=client-agent
make down                      # stop
```

|||

::: callout info
**`LOCAL_SDK=true`**: every Python service is built `FROM` the `prometheus_api` base image. With this line, `make up` first builds that image from `../sdk` on your laptop (`prometheus_api:local`): no registry, no token. Without it, `make up` tries to pull from `containers.github.inl.gov` and fails with `unauthorized`. Put it in `.env` after `make init-env`, so every later `make up` sees it.
:::

::: callout bad
**Every `make up` or `make restart` empties the agent registry** (`clear-agent-registry`). The platform's own agents re-register by themselves. **Yours does only on a base image with the SDK keep-alive** (within about 5 s). On the pinned image, restart it afterwards with `docker compose -p <agent-folder> restart`.
:::
::::

---

## No `.env` yet? `make` asks for your LLM {eyebrow="First run"}

```text {.xs hl=5-14}
$ make init-env
Created .env from .env.example.
Generated in .env: AGENT_SECRET, REDIS_PASSWORD, ADMIN_DB_PASSWORD, …

Choose an LLM profile (up/down, Enter):
  amsc         American Science Cloud OpenAI-compatible
  anl_asksage  ANL AskSage
> anthropic    Anthropic
  genesis      American Science Cloud OpenAI-compatible
  inl_hpc      INL HPC OpenAI-compatible
  inl_litellm  INL LiteLLM proxy
  ollama       Inference provider configuration for a locally running ollama  [no key]
  openai       OpenAI
LLM_API_KEY for anthropic (input hidden):
Saved LLM_CONFIG_PROFILE=anthropic in .env.
```

:::: grid 3
::: card acc
### Pick a profile

{.small}
Up/down arrows, then Enter. There is **no default**: you must pick one. `[no key]` (ollama) skips the key prompt.
:::

::: card acc
### Paste the key

{.small}
Nothing is echoed while you type. Profile and key go into `.env`, next to the generated secrets.
:::

::: card
### Change it later

{.small}
Edit `LLM_CONFIG_PROFILE` and the key in `.env`, or blank the key and run `make init-env` again for the menu.
:::
::::

{.small}
`make up` runs the same step, so you get this menu there too if you skipped `make init-env`. It only appears in a terminal and only while the profile or its key is missing; otherwise `make` stops with `[ERROR] … is empty in .env`.

---

## An admin user, and you're in {eyebrow="First login"}

::: steps
#### Open `http://localhost:5150`

{.small}
On first start a setup wizard asks for a username and password. Any local values work (not your INL login); the first user becomes admin.

#### Nothing to do for the signing key

{.small}
The backend creates and activates one on first start. It signs every chat turn, so agents know which user is asking. Admin › Signing Keys is only for rotating it.

#### Type `/agents` in the chat

{.small}
You should see form-filler and synthesis (OSTI research only with `OPTIONAL_AGENTS=true`).
:::

::: callout warn
Every chat turn fails with "No 'userToken' found…"? The backend could not create the key: check `ADMIN_DB_ENCRYPTION_KEY` in `.env` and `make logs SERVICE=backend`.
:::

---

## Is it healthy? {eyebrow="Health checks"}

```bash {.sm}
make ps                                     # all "Up" and "(healthy)"
curl -s localhost:8600/healthz              # {"status":"ok"}
make check                                  # every agent registered?

set -a; source .env; set +a                 # for the secret below
curl -s -H "Authorization: Bearer $AGENT_SECRET" \
     localhost:8600/v1/agents | python3 -m json.tool     # registered agents
```

:::: grid 2
::: callout
Then ask the chat something real, e.g. "Extract the material, temperature and pressure from: SS316 pipe at 320 °C and 15 MPa" (form-filler). Watch it with `make logs SERVICE=client-agent`.
:::

::: callout warn
A 401 from `/v1/agents` means a missing or wrong `AGENT_SECRET` header.
:::
::::

---

## Reference agents for tomorrow {eyebrow="Learn from working code"}

```bash {.sm}
make DEBUG_AGENTS=true up        # adds the reference agents
```

{widths="330px||"}
| Agent | Shows you how to… | Try |
|---|---|---|
| `artifact-debug-agent` | publish an image through DeepLynx | "Make an image with the word Success" {.hl} |
| `corrosion-agent` | ask the user for missing inputs | "Corrosion analysis of SS316" |
| `thread-pattern-agent` | run long work in the background | "Run a background task" |

{.small}
Read them in `prometheus_core/platform/agents/debug-agents/`. Each is a short, complete example of one platform feature.

---

## Which LLMs your agent uses {eyebrow="LLMs"}

::: cols 1.45fr 1fr
{.body}
Your code asks for a **flavor** (`small`, `medium`, `large`, `vision`, `embedding`). One line in `.env` picks a **profile**: a provider plus the model behind each flavor. **It is required**; there is no default.

{.sm .nw}
| Profile | Provider | `LLM_API_KEY` holds |
|---|---|---|
| `inl_litellm` | INL LiteLLM | your INL LiteLLM key |
| `genesis` | Genesis MAG (American Science Cloud) | your Genesis key |
| `anthropic` / `openai` | the vendor directly | your vendor key |
| `ollama` | ollama on your laptop | nothing (see note) |

{.small}
All profiles (also `amsc`, `anl_asksage`, `inl_hpc`) ship with the SDK in `sdk/prometheus_api/llm_configs/`. Agents call the provider **directly**; there is no LLM proxy in the platform. For `ollama`, first name your models after the flavors: `ollama cp <model> default` (and `small`, `medium`, `large`, `vision`).

|||

```text {.sm}
# platform/.env (setup_agent.py copies
# both into your agent's .env)
LLM_CONFIG_PROFILE=inl_litellm
LLM_API_KEY=…

# LLM_CONFIG_PROFILE=genesis
# LLM_CONFIG_PROFILE=ollama
# (every profile reads LLM_API_KEY)
```

{.small}
Keys stay in `.env`, never in code or the repo. A wrong profile name stops with `LLMConfigError` listing the installed ones.
:::

Note: The template compose forwards LLM_CONFIG_PROFILE, LLM_API_KEY and EMBEDDING_API_KEY; LLM_CONFIG_PROFILE has no default (compose stops with "set LLM_CONFIG_PROFILE in .env"). The old `registry` profile is rejected by make init-env.

---

## Where your files live {eyebrow="DeepLynx"}

::: flow
- [gray flex=1] **Chat upload**
- ->  {w=50}
- [teal flex=1.2] **DeepLynx** | stores the file
- ->  {w=50}
- [orange flex=1] **Your agent** | reads it, writes results back
- ->  {w=50}
- [sky flex=1] **Chat UI** | renders the plot
:::

- Every upload and every result file goes through DeepLynx, INL's data store.
- **Every agent call writes an execution record there, so an agent without DeepLynx settings does not even start.**
- Everyone runs a **local DeepLynx** next to the platform (next three slides). The settings are the `DEEPLYNX_*` lines in `.env`.

---

## Clone, build, start {eyebrow="Local DeepLynx · 1"}

:::: grid 2 gap=30px
```bash {.sm}
git clone https://github.com/idaholab/DeepLynx.git
cd DeepLynx
cp .env_sample .env
docker compose build
docker compose up          # add -d to detach
```

{.sm}
| Service | Host port | What |
|---|---|---|
| `ui` | 3000 | admin web UI (auth disabled locally) {.hl} |
| `server` | 5000 | **API** at `/api/v1`, which the platform uses {.hl} |
| `docs` | 3001 | documentation site |
| `nx-postgres` | 5432 | its database |
| `mcp` | 43656 | DeepLynx MCP server |
| `insight-*` | 5009, 5672… | only with `--profile insight` |

|||

::: card
#### It runs next to the platform

{.small}
DeepLynx has its own compose project and network (`nexus-network`). The platform containers reach it through your host at `prometheus.host.internal:5000`.
:::

::: callout warn
**macOS: port 5000** is often taken by the AirPlay Receiver (System Settings › General › AirDrop & Handoff). Turn it off, or remap the `server` port.
:::

::: callout warn
**Port 5432** clashes with any local Postgres. The platform's own databases do not publish ports, so they won't collide.
:::

{.small}
Pulled new DeepLynx changes? `docker compose up --build`.
::::

---

## Create a project at `http://localhost:3000` {eyebrow="Local DeepLynx · 2"}

::: grid 3 gap=20px
<img alt="Selecting the INL default organization" class="fit" src="assets/deeplynx/dl_3.png" style="border:1px solid var(--rule); border-radius:8px"/>

{.small}
**①** Skip or take the quick tour. In the top-left dropdown, select **"INL – default organization"**.

|||

<img alt="Empty organization with + Project button" class="fit" src="assets/deeplynx/dl_4.png" style="border:1px solid var(--rule); border-radius:8px"/>

{.small}
**②** Click **"+ Project"** and give it any name. A project is a fenced-off database for the platform.

|||

<img alt="Project page with project ID in URL" class="fit" src="assets/deeplynx/dl_6.png" style="border:1px solid var(--rule); border-radius:8px"/>

{.small}
**③** The URL now shows `localhost:3000/project/1`. **1 is your project ID**; each new project gets a new one.
:::

---

## Generate an API key and point the platform at it {eyebrow="Local DeepLynx · 3"}

::: cols 0.8fr 0.8fr 1.4fr gap=22px
<img alt="Local Developer menu with Settings" class="fit" src="assets/deeplynx/dl_7.png" style="border:1px solid var(--rule); border-radius:8px"/>

{.small}
**④** Bottom left: person icon → under *Local Developer* click **Settings** (not the organization settings in the far-left bar).

|||

<img alt="API Keys section with Generate New" class="fit" src="assets/deeplynx/dl_8.png" style="border:1px solid var(--rule); border-radius:8px"/>

{.small}
**⑤** API Keys → **"+ Generate New"**. Copy the **key and secret** now: the secret is shown only once.

|||

{.small}
**⑥** In `prometheus_core/platform/.env`:

```text {.sm}
DEEPLYNX_KEY=…
DEEPLYNX_SECRET=…
DEEPLYNX_BASE_URL=http://prometheus.host.internal:5000/api/v1/
DEEPLYNX_ORG_ID=1
DEEPLYNX_PROJECT_ID=1
```

{.small}
Then `make restart`. `setup_agent.py` copies every `DEEPLYNX_*` into your agent's `.env`.

{.small}
Agent running on the host (not in Docker)? Use `http://localhost:5000/api/v1`.
:::

---

## Check that the platform can reach DeepLynx {eyebrow="DeepLynx"}

::: col
```python {.sm}
# from inside the backend container (has DEEPLYNX_* env)
docker compose -p prometheus_platform exec -T backend python - <<'EOF'
from prometheus_api.storage_client import (
    ConnectionConfig, StorageClient)
cfg = ConnectionConfig.from_env()
with StorageClient(cfg) as c:
    page = c.items.list(page_size=5)
    print("OK", cfg.base_url, len(page.items), "items")
EOF
```

{.small}
Then upload a file in the chat. It should appear in the DeepLynx UI under your project, and `/artifacts` lists it.
:::

---

## The problems you are most likely to hit {eyebrow="Something is off"}

{.sm widths="470px|"}
| Symptom | Fix |
|---|---|
| Agent exits: "Invalid required DeepLynx configuration: …" | set `DEEPLYNX_KEY` + `DEEPLYNX_SECRET`, `DEEPLYNX_ORG_ID`, `DEEPLYNX_PROJECT_ID` in its `.env` |
| Your agent disappeared from `/agents` | the platform restarted: `docker compose -p <agent-folder> restart` |
| LLM call gets HTTP 401 | the key for your `LLM_CONFIG_PROFILE` is missing or wrong in the agent's `.env` |
| `LLMConfigError` / "set LLM_CONFIG_PROFILE in .env" | the profile is empty or misspelled; the message lists the installed ones |
| "DeepLynx storage is not configured" | set the `DEEPLYNX_*` lines, `make restart` |
| Backend fails: `password authentication failed for user "admin"` | a second platform checkout reuses the same Docker volumes: restore the old `ADMIN_DB_PASSWORD` and `ADMIN_DB_ENCRYPTION_KEY` in `.env`, or `make clobber` (deletes users, keys, and history) |
| Something else | `make logs SERVICE=<name>`; the appendix has the full troubleshooting tables |

---

## Before the break {eyebrow="Checkpoint"}

:::: grid 2 gap=30px
{.check}
- ☐ `make ps`: all services up
- ☐ `curl localhost:8600/healthz` → `{"status":"ok"}`
- ☐ `make check` passes: every agent registered
- ☐ Logged in through the setup wizard
- ☐ `/agents` in the chat works
- ☐ A question gets an LLM answer
- ☐ Local DeepLynx: an upload appears at `localhost:3000`

|||

::: card acc
### Stuck?

{.body}
Raise your hand now. Mentors fix environment problems during the break, so that at 2:45 pm everyone can follow the agent session with a running stack.
:::

::: card
### Next: Building an agent (2:45 pm)

{.body}
The agent template is already in your clone (`prometheus_core/agent-template/`). Have `uv --version` working.
:::
::::

---

# Bonus: catch-up slides {.section .bonus num="+"}
For participants whose platform does not start yet: prerequisites, clone, `.env` (with the local base image), and startup failures.

---

## Before you clone {eyebrow="Bonus · Prerequisites"}

{widths="280px|"}
| Need | Why / check |
|---|---|
| **Docker + Compose v2** | The Makefile calls `docker compose -p prometheus_platform`. The compose files use `include:` and `additional_contexts`, so Compose ≥ 2.20 with BuildKit is needed. Check: `docker info`, `docker compose version`. |
| **GNU make, git, python3** | `make up` runs `scripts/init_env.py` (standard library only) to create `.env`. |
| **`gh`, the GitHub CLI** | Used for forks and PRs. `brew install gh` (needs admin), or copy the release binary from `github.com/cli/cli/releases` into `~/.local/bin`; then `gh auth login`. |
| **The `prometheus_api` base image** | Nothing to set up: `LOCAL_SDK=true` in `.env` builds it from `sdk/` on your laptop. |
| **An LLM credential** | `LLM_API_KEY` for the profile you pick (INL LiteLLM, Genesis, Anthropic…), or a local ollama. |
| **A local DeepLynx** | Required: agents don't start without it. Set up in this deck (Local DeepLynx · 1–3). |
| **uv + Python 3.12** | Only for running things outside Docker: tests, a host-run agent, `setup_agent.py`. `uv --version` |
| Node.js 22 (optional) | Only to run the frontend dev server on the host (`make react-dev`). |
| Disk space | Several GB for images. No minimum RAM is documented; if builds get killed, raise the Docker Desktop memory limit. |

{.small}
Podman: the template README mentions it, but the platform Makefile only drives `docker compose`. Use Docker Desktop (or Docker Engine) for the hackathon.

---

## Clone, and where the base image comes from {eyebrow="Bonus · Step 1"}

:::: grid 2 gap=30px
```bash {.sm}
# your fork (see previous session), default branch devel
git clone git@github.com:<you>/prometheus_core.git
cd prometheus_core/platform     # the stack lives here
git remote add upstream \
  git@github.com:idaholab/prometheus_core.git
git switch devel

make init-env                 # creates .env, asks for LLM + key
echo "LOCAL_SDK=true" >> .env   # base image from ../sdk
```

|||

::: card
#### Why a base image?

{.small}
Every Python service (backend, client-agent, all agents) is built `FROM` the `prometheus_api` image. With `LOCAL_SDK=true`, `make up` first builds it from `../sdk` as `prometheus_api:local`: no registry, no login, no VPN.
:::

::: callout warn
`LOCAL_SDK=true` builds whatever is in `sdk/` in your clone. After `git pull`, the next `make up` rebuilds it, so the SDK always matches the platform you pulled.
:::
::::

---

## `.env`: `make up` writes it, you add one key {eyebrow="Bonus · Step 2 · in prometheus_core/platform"}

:::: grid 32 gap=28px
{.sm}
| In `.env` | Who sets it |
|---|---|
| `LLM_CONFIG_PROFILE` + `LLM_API_KEY` | **you**: `make up` asks for both {.hl} |
| `LOCAL_SDK=true` | **you**: build the base image from `../sdk` {.hl} |
| `DEEPLYNX_*` (key, secret, org, project, URL) | **you**: from your local DeepLynx {.hl} |
| `AGENT_SECRET`, `REDIS_PASSWORD`, `ADMIN_DB_PASSWORD` | generated |
| `BACKEND_JWT_SECRET` | generated (session-cookie signing key) |
| `ADMIN_DB_ENCRYPTION_KEY` | generated (Fernet key for admin-db) |
| `REDIS_URL`, `BACKEND_PORT=8600`, ports | defaults from `.env.example`; keep them |

|||

#### What `make init-env` does {.acc}

{.small}
`scripts/init_env.py`, run by every `make up`/`restart`:

{.small}
1. copies `.env.example` to `.env` if there is none
2. fills every **blank** secret; values already set are never touched
3. if the profile or its key is empty: shows the profile menu and asks for the key (no terminal: stops with an error)

{.small}
`setup_agent.py` later copies these secrets into your agent's `.env`.

::: callout bad
Never commit `.env`. Never paste it into chat or a PR. Back it up: losing `ADMIN_DB_ENCRYPTION_KEY` makes the admin-db's encrypted rows unreadable.
:::
::::

---

## The stack won't start {eyebrow="Bonus · Troubleshooting · 1"}

{.sm widths="470px|"}
| Symptom | Cause → fix |
|---|---|
| `unauthorized`, `denied` or `invalid reference format` for the base image | `LOCAL_SDK=true` is missing from `.env`, so the build looks for an image registry. Add the line and run `make up` again. |
| `pull access denied for prometheus_api` | `LOCAL_SDK=true` is set, but `docker compose` ran without make, so `prometheus_api:local` was never built. Run `make base-image`, or always go through `make up`. |
| `make up` stops: "`LLM_API_KEY` is empty" or "`LLM_CONFIG_PROFILE=registry` … is not supported" | Set `LLM_CONFIG_PROFILE` and its `LLM_API_KEY` in `.env` (or blank the profile and rerun `make up` for the menu). |
| Port is already allocated (5150, 8600, 6379, 3000) | Another process or an old stack is using it. `make down`, or change `*_PORT` in `.env`. |
| Backend exits: "jwt_secret is not configured" | `BACKEND_JWT_SECRET` is empty: you ran `docker compose` without make. Run `make init-env` (an old `CHAINLIT_AUTH_SECRET` is no longer read). |
| Backend exits during an alembic step | Migrations run in `backend/docker-entrypoint.sh` before uvicorn; `make logs SERVICE=backend`. |
| SSL / certificate errors during `npm ci` or `pip` on the INL network | TLS inspection. The INL bundle is checked in under `common/certs/`; pull the latest `devel`. Extra CAs: drop a `*.pem` there. |
| `network … has active endpoints` on `make up` | An external agent is still attached to `prometheus_platform_agent-network`. Stop it first (`make down` in the agent dir). |
| Build killed / exit 137 | Out of memory. Raise the Docker Desktop memory limit. The heaviest image, the OSTI agent, is only built with `OPTIONAL_AGENTS=true`. |
| Behind a corporate proxy: downloads time out | Set `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`. They are **build** args; add `backend,admin-db` and your agent names to `NO_PROXY`. |

---

# Appendix: reference {.section .appendix num="A"}
Reference material behind the talk. Skipped in the session; use it when you need the details.

---

## You ran the stack at home. By 2:30 pm you also… {eyebrow="Goal"}

:::: grid 2 gap=30px
::: steps
#### Know what is running

{.small}
Every container, its port, and what `make up` really does.

#### Are logged in

{.small}
The setup wizard's admin; the backend has already activated a signing key so agents accept your requests.

#### Get an answer

{.small}
`/agents` lists the agents, and a question reaches the provider of your LLM profile.

#### Can upload a file

{.small}
It lands in DeepLynx and agents can read it.
:::

|||

::: card acc
### This session

{.sm}
1. What is running
2. Configuration and `make up`
3. The base image
4. First login and health checks
5. LLM configuration
6. DeepLynx
7. When things are off
:::

::: callout warn
Platform not starting yet? Use the **bonus slides** at the end of this deck with a mentor.
:::
::::

---

## Ports on your host {eyebrow="What you will run"}

:::: grid 2 gap=30px
| URL | Service | Variable |
|---|---|---|
| `http://localhost:5150` | Frontend (Vite dev) | `FRONTEND_DEV_PORT` {.hl} |
| `http://localhost:8080` | Frontend (nginx; `PROFILE=prod`) | `FRONTEND_PROD_PORT` |
| `http://localhost:8600` | Backend (FastAPI): API, agent registry, A2A gateway | `BACKEND_PORT` |
| `localhost:6379` | Valkey (Redis protocol) | `REDIS_LOCAL_PORT` |
| `http://localhost:8001` | client-agent (system-test mode only) | `CLIENT_AGENT_PORT` |
| `http://localhost:8008` | artifact-debug-agent (`DEBUG_AGENTS=true`) | `ARTIFACT_DEBUG_PORT` |

|||

{.body}
Everything else stays **inside** the Docker network `prometheus_platform_agent-network` and is reached by service name:

```yaml {.sm}
http://backend:8000        # registry (REGISTRY_URL), JWKS
redis://redis:6379
http://client-agent:8000
http://<agent-service>:8000
```

::: callout
A port is already taken, for example by a local Redis on 6379? Change the variable in `.env` and re-run `make up`.
:::
::::

---

## The `.env` knobs worth knowing {eyebrow="Configuration"}

::: grid 2 gap=26px
{.xs}
| Variable | Default | Purpose |
|---|---|---|
| `DEBUG_AGENTS` | `false` | Include `agents/debug-agents/*` |
| `OPTIONAL_AGENTS` | `false` | Include `agents/optional/*` (OSTI research, slow build) |
| `LLM_CONFIG_PROFILE` | **none: required** | Which provider and flavor→model map agents use |
| `LLM_CONFIG_FILE` | empty | Custom YAML inside the container; overrides the profile |
| `LLM_API_KEY` | empty | The key for the chosen profile (every profile reads it) |
| `EMBEDDING_API_KEY` | empty | Embeddings key for `anthropic`, `anl_asksage` |
| `LOCAL_SDK` | `false` | **Set it to `true`**: build the base image from `../sdk` (`prometheus_api:local`) {.hl} |
| `DEEPLYNX_BASE_URL/KEY/SECRET/ORG_ID/PROJECT_ID` | empty | **Required**: uploads, `deeplynx://`, execution records |
| `PROMETHEUS_MAX_UPLOAD_BYTES` | 104857600 | 100 MiB upload cap |
| `HTTP(S)_PROXY`, `NO_PROXY` | commented | Build args for Python images only |

|||

{.xs}
| Variable | Default | Purpose |
|---|---|---|
| `USER_IDENTITY_REQUIRED` | `true` | Agents reject turns without a user JWT |
| `USER_IDENTITY_PRIVATE_KEY` | empty | Static signing key; set → no key is auto-created |
| `USER_IDENTITY_PUBLIC_KEY` | empty | Static key for agents *outside* compose; `JWKS_URL` wins |
| `USER_IDENTITY_ISS` / `_AUD` | prometheus-platform / -agents | JWT claims |
| `USER_IDENTITY_TTL` | 7200 | Token lifetime in seconds |
| `BACKEND_WORKERS` | 1 | uvicorn workers (sessions live in Valkey) |
| `PROMETHEUS_MESH_WORKERS` / `_TIMEOUT_SECONDS` | 2 / 120 | VTK mesh-conversion pool, per-mesh time budget |
| `BACKEND_MEM_LIMIT` | 4g | backend container memory cap |
| `BACKEND_PUBLIC_URL` | empty | Browser origin for OIDC redirects |
| `CREDENTIAL_BROKER` | `env` | `env` = global creds; `vault` = per user |
| `PROMETHEUS_SYSTEM_TESTING` | `false` | Publish the client-agent on :8001 |
:::

{.tiny}
Documented but unused on `devel`: `FRONTEND_URL`, `LOCAL_CERT_FILE`/`CERT_FILE`. OIDC is now configured in Admin › Identity Providers.

---

## `make up`, and what it really does {eyebrow="Under the hood"}

::: flow
- [gray flex=1] **check-prerequisites** | `.env` exists, docker is running
- ->  {w=30}
- [violet dash flex=1] **base-image** | if `LOCAL_SDK`: build the SDK image
- ->  {w=30}
- [sky flex=1] **generate** | writes `docker-compose.agents.yml` (`include:` of `agents/*/docker-compose.yml`)
- ->  {w=30}
- [sky flex=1] **init-env** | `.env` from the example, blank secrets filled, LLM key checked
- ->  {w=30}
- [crimson flex=1] **clear-agent-registry** | `compose down` + delete the registrations in Valkey
- ->  {w=30}
- [green flex=1] **up --build -d --wait**, then **check** | profile `dev`: all services + frontend-dev; waits until all are healthy and registered
:::

:::: grid 2 gap=26px
```bash {.sm}
make up                        # build + start, wait, check
make CHECK=false up            # skip the wait and check
make LOCAL_SDK=true up         # base image from ../sdk
make up-fg                     # same, logs in foreground
make DEBUG_AGENTS=true up      # + mock agents
make OPTIONAL_AGENTS=true up   # + OSTI research (slow build)
make PROFILE=prod up           # nginx frontend on :8080
make PROFILE= up               # no frontend container…
make react-dev                 # …run Vite on the host
make PROMETHEUS_SYSTEM_TESTING=true up  # :8001
make ps ; make logs SERVICE=client-agent
```

|||

::: callout bad
**`make up` and `make restart` wipe all agent registrations.** Every run does a full `down` and deletes the registrations from Valkey. In-tree agents re-register because they restart too. An **external agent** (your template agent) must be restarted afterwards, unless its base image has the SDK keep-alive: then it is back within about 5 s.
:::

{.small}
`restart` = the same without `--build`. `ng-up` / `ng-restart` skip regenerating the agents file. `docker-compose.override.yml` is picked up automatically if present (gitignored).
::::

---

## From `LOCAL_SDK=true` to every `FROM` {eyebrow="How the platform builds the base image"}

::: grid 3 gap=22px
#### ① platform/Makefile {.acc}

```bash {.sm}
ifeq ($(LOCAL_SDK),true)
…_REPO := prometheus_api
…_HASH := local
BASE_IMAGE_DEP := base-image
endif

up: $(BASE_IMAGE_DEP) generate …
base-image:
	$(MAKE) -C ../sdk build-local \
	  LOCAL_IMAGE=prometheus_api:local
```

{.tiny}
`-include .env` comes first, so `LOCAL_SDK=true` in `.env` is enough. `…` = `PROMETHEUS_API_BASE_IMAGE`.

|||

#### ② compose (build arg) {.acc}

```yaml {.sm}
# docker-compose.yml
x-build-args:
  PROMETHEUS_API_BASE_IMAGE_REPO: …
  PROMETHEUS_API_BASE_IMAGE_HASH: …
# agents/<x>/docker-compose.yml
args:
  - PROMETHEUS_API_BASE_IMAGE_REPO=…
  - PROMETHEUS_API_BASE_IMAGE_HASH=…
```

{.tiny}
make exports both variables, so every service gets `prometheus_api:local`.

|||

#### ③ every Dockerfile {.acc}

```docker {.sm}
ARG PROMETHEUS_API_BASE_IMAGE_REPO
ARG PROMETHEUS_API_BASE_IMAGE_HASH
FROM ${PROMETHEUS_API_BASE_IMAGE_REPO}:\
  ${PROMETHEUS_API_BASE_IMAGE_HASH}
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN uv sync --no-dev \
  --no-install-project --inexact
```

{.tiny}
(Each `ARG`/`FROM` is one line in the real file.)
:::

:::: grid 3
::: card
#### Change the SDK

{.small}
Edit `sdk/`, then `make up` (or `make base-image`): every service is rebuilt on your change. Read `sdk/docs/agent/AGENT_MIGRATIONS.md` after a pull that bumps the SDK version.
:::

::: card
#### Your own agent

{.small}
`setup_agent.py` sees `LOCAL_SDK=true` in `../platform/.env` and writes `…_REPO=prometheus_api` and `…_HASH=local` into the agent's `.env`.
:::

::: card
#### Trap: plain `docker compose`

{.small}
Without make, `prometheus_api:local` may not exist yet. Always build through `make`.
:::
::::

---

## Inside `sdk/Dockerfile` {eyebrow="What the base image provides"}

::: grid 2 gap=28px
```docker {.xs}
FROM ghcr.io/astral-sh/uv:0.11.25-python3.12-trixie-slim\
@sha256:1b9ee303…                  # digest-pinned

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.pem \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.pem \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-bundle.pem \
    UV_SYSTEM_PYTHON=1

# system CAs + common/certs (INL bundle), validated
RUN --mount=type=bind,from=certs,target=/tmp/certs \
    sh /tmp/certs/setup.sh

RUN apt-get install -y --no-install-recommends git

# locked runtime deps → system Python
RUN uv export --frozen --no-dev --no-emit-project \
      > requirements.txt && uv pip install -r requirements.txt
# the package itself
RUN uv pip install --no-deps /src
CMD ["python"]
```

|||

{.sm}
| You get | Details |
|---|---|
| Debian 13 slim, Python 3.12, `uv`, `git` | runs as root, no `WORKDIR` (agents set `/app`) |
| Used by | client-agent and every agent; the backend now builds on its own image from `../sdk` |
| `prometheus_api` | PrometheusAgent, LLMClient, StorageClient, identity, credentials, artifacts |
| Server stack | `a2a-sdk[http-server]` 1.x, starlette, uvicorn |
| Clients | litellm, httpx, redis, fsspec (`deeplynx://`), PyJWT, pydantic, pyyaml |
| LLM profiles | `anthropic`, `openai`, `genesis`, `ollama`, `amsc`, `anl_asksage`, `inl_hpc`, `inl_litellm` (`registry` exists but is rejected) |
| INL TLS trust | `common/certs/` via the `certs` build context (INL bundle incl. the root) |
| CLI | `prometheus-identity-keygen` |

{.small}
Your agent image adds only your own dependencies. That is why builds are small, and why `prometheus_api` must not appear in your `pyproject.toml`.
:::

---

## Every Makefile target {eyebrow="Reference"}

::: grid 2 gap=26px
{.xs}
| Target | Does |
|---|---|
| `help` | (default) list targets |
| `up` / `up-fg` | generate + key + wipe registry + `up --build --wait` + `check` |
| `restart` / `restart-fg` | same without `--build` (still a full down) |
| `ng-up`, `ng-restart` (+`-fg`) | without regenerating the agents file |
| `down` | stop everything |
| `down-v` | stop and **delete volumes** (Valkey incl. sessions, admin-db, mesh cache, model caches) |
| `build` | generate + build images |
| `ps`, `logs` \[`SERVICE=`\] | status, follow logs |
| `generate`, `regenerate`, `clean-generated` | manage `docker-compose.agents.yml` |

|||

{.xs}
| Target | Does |
|---|---|
| `clear-agent-registry` | down + delete the agent registrations in Valkey |
| `check` | wait until backend, frontend and every agent's registration answer |
| `clear-admin-users` | truncate users → the setup wizard runs again |
| `clobber` | asks, then down + delete admin-db and Valkey (keeps caches) |
| `init-env` | create `.env`, fill blank secrets, check the LLM key |
| `check-prerequisites` | Docker checks |
| `test-static` | infra tests, no Docker |
| `test-integration`, `test-infra` | against running containers |
| `test-system` | full system (needs `PROMETHEUS_SYSTEM_TESTING=true`) |
| `react-dev`, `react-build`, `react-check` | frontend on the host |
| `build-plain` | **broken** on devel (undefined variable) |
:::

{.small}
Variables: `PROFILE` (dev | prod | empty), `DEBUG_AGENTS`, `OPTIONAL_AGENTS`, `PROMETHEUS_SYSTEM_TESTING`, `LOCAL_SDK`, `SERVICE`, `CHECK=false`, `WAIT_TIMEOUT`, `CHECK_TIMEOUT`, `SKIP_PREREQUISITES=1`. The compose project name is `prometheus_platform`.

---

## Setup wizard; the signing key is automatic {eyebrow="First login"}

:::: grid 2 gap=30px
::: steps
#### Open `http://localhost:5150`

{.small}
On a fresh admin-db the **setup wizard** appears. Create the first user with any local username and password (not your INL login); it becomes `admin`. (The old `prometheus/prometheus` login in the README no longer exists.)

#### Signing key: already there

{.small}
On first start the backend generates and activates an RS256 key (stored encrypted with `ADMIN_DB_ENCRYPTION_KEY`). It mints a `userToken` for every chat turn and publishes the public key at `/.well-known/jwks.json`. Admin › Signing Keys is for rotation.

#### Chat

{.small}
Try `/help`, `/agents`, `/workflows`, then ask a real question.
:::

|||

::: callout bad
**No key, and every turn fails** with "No 'userToken' found in message metadata and USER_IDENTITY_REQUIRED=true". The backend logs a warning when it could not create one, typically a missing or invalid `ADMIN_DB_ENCRYPTION_KEY`.
:::

::: card
#### Alternative to the admin UI

{.xs}
- Local only: `USER_IDENTITY_REQUIRED=false` in `.env`, then `make restart`. Requests run as user `local`.
- Setting `USER_IDENTITY_PRIVATE_KEY` turns off the automatic key, and agents verify through the backend's JWKS (`JWKS_URL`), which lists only keys stored in admin-db. Leave it empty.
:::

{.small}
Redo the wizard with `make clear-admin-users`. Sessions live in Valkey: a backend restart (even `make restart`) keeps you logged in, and a reload reopens the conversation you had open.
::::

---

## Check bottom-up: store → backend → registry → agents {eyebrow="Health checks"}

```bash {.sm}
source .env   # for the variables below

make ps                                                     # everything "Up (healthy)"
docker compose -p prometheus_platform exec -T redis valkey-cli -a "$REDIS_PASSWORD" ping  # → PONG
docker compose -p prometheus_platform exec -T admin-db pg_isready -U admin                     # → accepting connections

curl -s http://localhost:8600/healthz                          # → {"status":"ok"}  (alive)
curl -s http://localhost:8600/readyz                           # → 200 once Valkey + admin-db answer
curl -s http://localhost:8600/.well-known/jwks.json            # → the active signing key
curl -s -H "Authorization: Bearer $AGENT_SECRET" \
     http://localhost:8600/v1/agents | python3 -m json.tool    # → registered agents
make check                                                     # all of the above, for every agent

docker compose -p prometheus_platform exec -T client-agent python -c "import urllib.request as u; \
  print(u.urlopen('http://synthesis-agent:8000/healthz').read())"   # → {"ok": true, "status": "healthy", …}
```

:::: grid 3
::: card
#### 401 from `/v1/agents`?

{.small}
The registry and gateway routes need `Authorization: Bearer $AGENT_SECRET`.
:::

::: card
#### `/healthz` through :5150?

{.small}
It is not under `/api`, so the frontend proxy does not forward it. Use :8600 directly.
:::

::: card
#### Agent healthchecks

{.small}
Every agent has a Docker healthcheck on `/healthz` (`/health` is gone). "healthy" does not mean registered: `make check` tests that.
:::
::::

---

## Ask the platform something {eyebrow="The real test"}

:::: grid 2 gap=30px
::: col
{.sm}
| Type in the chat | Expect |
|---|---|
| `/help` | the slash commands |
| `/agents` | form-filler, synthesis (plus debug / optional agents if enabled) |
| `/workflows` | registered workflow templates |
| `/artifacts` | this conversation's artifacts |
| `/tasks [id]` | background tasks |
| "Find recent OSTI papers on SiC cladding" | with `OPTIONAL_AGENTS=true`: routes to `search_literature`; watch the status stream |
:::

|||

#### Watch it happen {.acc}

```bash {.sm}
make logs SERVICE=client-agent
make logs SERVICE=form-filler-agent
make logs SERVICE=backend
```

{.small}
In the client-agent log you see discovery (`GET backend:8000/v1/agents`), each tool call the loop makes (status "Next step: …"), and the `/a2a/{agent}` call through the backend.

::: callout
A newly registered agent reaches the orchestrator's tool list within about 60 s (the capability-cache TTL), immediately on a skill miss, or right after `docker compose -p prometheus_platform restart client-agent`.
:::
::::

---

## `DEBUG_AGENTS=true`: the reference agents {eyebrow="More to play with"}

:::: grid 2 gap=30px
```bash {.sm}
make DEBUG_AGENTS=true up
# or set DEBUG_AGENTS=true in .env
```

{.sm}
| Agent | Study it for |
|---|---|
| artifact-debug-agent (:8008) | DeepLynx artifacts, SVG→PNG, and an agent-owned workflow |
| corrosion-agent | `send_input_required`; answers come back in `params` |
| thermal-agent | a custom `json_type` with its own viewer |
| material-data-agent | many small skills on one agent |
| radiation-agent | input-required prompts |
| thread-pattern-agent | `PrometheusWorker`, `declare_long_running` |

|||

#### Prompts that exercise them {.acc}

{.sm}
- "Thermal analysis of SS316 at 550 °C" → thermal viewer
- "Comprehensive material analysis of SS347" → the `comprehensive_material_analysis` DAG workflow, which asks for **approval** before it runs
- "Make an image with the word Success" → SVG to DeepLynx (needs DeepLynx)
- `/artifact_debug.patriotic_usa_png` → starts the agent-owned workflow directly

::: callout
These are the best working examples of every pattern in the template tutorial. Read them in `agents/debug-agents/`.
:::
::::

---

## Code picks a flavor; the profile picks the model {eyebrow="LLM configuration for the deployment"}

:::: col
{.body}
Agent code asks for a **flavor** (`llm.medium(…)`). The deployment chooses a **profile** that maps flavors to real models. Resolution order in `LLMConfig.from_env()`:

1. `LLM_CONFIG_FILE`: a YAML path inside the container
2. `LLM_CONFIG_PROFILE`: an installed profile name (`list_llm_config_profiles()`)

{.small}
Each agent calls the provider's `api_base` **directly** with `LLM_API_KEY`. The platform no longer runs an LLM proxy, so the old `registry` profile (calls to `REGISTRY_URL`) is rejected by `make init-env`, and the platform compose stops if `LLM_CONFIG_PROFILE` is empty.

::: callout warn
A flavor with no model behind it raises `LLMAliasError`; an unknown profile raises `LLMConfigError` with the list of installed ones; a provider error (bad key, quota) raises `LLMProviderError` with the status code and a one-line reason.
:::
::::

---

## Switching the whole stack to another profile {eyebrow="Other providers"}

{.sm}
| Profile | Route | `LLM_API_KEY` | default · small · medium · large · vision · embedding |
|---|---|---|---|
| `inl_litellm` | `https://litellm.inl.gov/v1` | INL LiteLLM | claude-sonnet-5-5-awsgov ×3 · opus-5-5-awsgov · … {.hl} |
| `genesis` | `https://mag.genesis.americansciencecloud.org/v1` | Genesis | claude-opus · haiku · sonnet · opus · … |
| `ollama` | `http://host.docker.internal:11434/v1` | none | your `ollama cp` aliases `default`, `small`, `medium`, `large`, `vision` |
| `inl_hpc` | `https://api.hpc.inl.gov/llm/v1` (vLLM) | INL HPC | gemma-4-26B-A4B-it ×3 · gemma-4-31B-reasoning · gemma-4-26B · llama-nemotron-embed |
| `anthropic` | `https://api.anthropic.com/v1` | Anthropic (+ `EMBEDDING_API_KEY`) | opus-5-5 · haiku-5-5 · sonnet-5-5 · opus-5-5 · opus-5-5 · voyage |
| `amsc` | American Science Cloud I2 | AMSC I2 | sonnet · haiku · sonnet · opus · … |
| `anl_asksage` | ANL AskSage | AskSage static key (+ `EMBEDDING_API_KEY`) | gpt-5.6-terra · gpt-5.4-nano · gpt-5.6-terra · gpt-5.6-sol · gpt-5.6-luna · voyage-4-large |
| `openai` | `https://api.openai.com/v1` | OpenAI | gpt-5.6-terra · 6-luna · 5.6-terra · 6.1-sol · 6-luna · … |

:::: grid 2
```bash {.sm}
# platform/.env: all platform agents switch
LLM_CONFIG_PROFILE=inl_litellm
LLM_API_KEY=sk-…
make restart
# your agent: same two lines in its .env
# (python setup_agent.py --env-only <dir>)
```

|||

::: callout
Setting `LLM_API_KEY` alone does **not** change routing; only the profile or file does. Installed profiles are scaffolds: the model IDs are replaceable (columns: default · small · medium · large · vision). The next session covers custom YAML files.
:::
::::

---

# DeepLynx: the data layer {.section num="DL"}
What the platform stores there, and why every agent needs it.

---

## Why the platform needs it {eyebrow="DeepLynx"}

:::: grid 2 gap=30px
{.body}
**DeepLynx** (Nexus) is INL's open-source data warehouse (`github.com/idaholab/DeepLynx`): organizations → projects → records (items), files, tags, relationships, and timeseries, behind a REST API.

{.sm}
| Who | Uses DeepLynx for |
|---|---|
| every agent (SDK ≥ 0.15) | an **execution record** per call (agent, user, task, redacted params); `self.execution_record_id` |
| client-agent | **every user upload** → stored, then registered as an artifact |
| agents | `send_deeplynx_artifact()` → `deeplynx://…/items/N` |
| backend | resolves `deeplynx://` to bytes for the viewers |
| agents consuming files | `get_artifact_file_path()` via fsspec |

|||

```yaml {.sm}
deeplynx://organizations/{org_id}/projects/{proj_id}/items/{item_id}
```

```python {.sm}
# any prometheus_api environment
import fsspec
from prometheus_api.storage_client import ConnectionConfig

fs = fsspec.filesystem("deeplynx",
        config=ConnectionConfig.from_env())
fs.get("deeplynx://organizations/1/projects/1/items/42",
       "/tmp/out/")          # → /tmp/out/42
```

::: callout warn
No DeepLynx configured → agents exit at startup with "Invalid required DeepLynx configuration: …", and uploads show "DeepLynx storage is not configured". Use the local instance from the main talk.
:::
::::

---

## The usual DeepLynx traps {eyebrow="DeepLynx"}

::: col
{.sm .wrap-code}
| Symptom | Fix |
|---|---|
| Connection refused to `prometheus.host.internal` | DeepLynx must listen on `0.0.0.0:5000`, and on Linux the host firewall must allow the Docker bridge. `host.docker.internal` does not exist on Linux; use `prometheus.host.internal`. |
| `AuthenticationError` / 401 | Key and secret swapped, or the secret was not copied completely. Generate a new key. |
| "Invalid required DeepLynx configuration: missing DEEPLYNX_ORG_ID…" | `DEEPLYNX_ORG_ID` / `_PROJECT_ID` are empty. Set them; also set key + secret **or** `DEEPLYNX_JWT_TOKEN`, never both. |
| "Failed to get data source ID…" | The project has no default data source. Set `DEEPLYNX_DATA_SOURCE_ID` (list them with `examples/list_datasources.py` in prometheus_api). |
| `deeplynx://` URI won't resolve in your agent | The agent needs the **same org and project** in its `ConnectionConfig` as the URI. |
| Nothing on :5000 (macOS) | AirPlay Receiver has the port. |

{.tiny}
`DEEPLYNX_TIMEOUT`, `_MAX_RETRIES`, and `_VERIFY_SSL` appear in `sdk/.env.example` but are ignored; pass them as `ConnectionConfig` arguments instead.
:::

---

## It starts, but something is off {eyebrow="Troubleshooting · 1"}

{widths="470px|"}
| Symptom | Cause → fix |
|---|---|
| Every turn fails: "No 'userToken' found… USER_IDENTITY_REQUIRED=true" | The backend has no active signing key: `ADMIN_DB_ENCRYPTION_KEY` missing or invalid (see the backend log). Fix `.env`, `make restart` (or `USER_IDENTITY_REQUIRED=false`). |
| "userToken has expired" | A long turn exceeded `USER_IDENTITY_TTL` (7200 s). Raise it. |
| `LLMAliasError`: alias 'small' not available | The active profile has no model for that flavor. Switch `LLM_CONFIG_PROFILE`, or use a custom `LLM_CONFIG_FILE` (next session). |
| `LLMProviderError` (401/403) from an LLM call | `LLM_API_KEY` is missing or wrong in the agent's `.env`, or it belongs to another profile. |
| The agent is running but not in `/agents` | The registration was wiped by `make up`/`restart`. With the SDK keep-alive it is back within about 5 s; otherwise `docker compose -p <agent-folder> restart` re-registers it. Either way the orchestrator sees it within about 60 s more. |

---

## It starts, but something is off (continued) {eyebrow="Troubleshooting · 2"}

{widths="470px|"}
| Symptom | Cause → fix |
|---|---|
| The orchestrator never calls your skill | A weak skill description or `usage_notes` (tags are not shown to it), a duplicate skill id, or a card URL the client-agent cannot reach (`EXTERNAL_AGENT_URL`). |
| Upload ignored: "DeepLynx storage is not configured" | Set `DEEPLYNX_*` and `make restart`. |
| Agent container restarts, log says "Invalid required DeepLynx configuration" | Its `.env` lacks `DEEPLYNX_*`: `python setup_agent.py --env-only <dir>`, then `make up` in the agent dir. |
| Mesh viewer error "libGL.so.1" | An old backend image. Rebuild with `make up`. |
| "Live updates stopped — the server is unreachable" | The backend or Valkey restarted mid-stream. Reload: the session and the open conversation come back. |

---

## Where to look {eyebrow="Debugging toolkit"}

:::: grid 3 gap=20px
::: card
#### Logs

```bash {.xs}
make logs                    # all
make logs SERVICE=backend
docker compose -p prometheus_platform \
  logs --no-log-prefix -f client-agent
docker compose -p <agent-folder> logs 2>&1 \
  | grep -i "Registered '"
```

{.small}
Everything logs to stdout. The "Registered" line appears only if the agent logs at INFO (the template does); `/v1/agents` is authoritative.
:::

::: card
#### State

```bash {.xs}
docker compose -p prometheus_platform exec redis \
  valkey-cli -a "$REDIS_PASSWORD"
> KEYS artifacts:conv:*
> KEYS conversation:*
> GET prometheus:agent-registry
> KEYS session:*
```

{.small}
Conversation state, artifact catalog, the agent registry, task graph, browser sessions.
:::

::: card
#### Inside a container

```python {.xs}
docker compose -p prometheus_platform \
  exec -T client-agent env \
  | grep -E '^(REGISTRY_URL|LLM_CONFIG_)'
# REGISTRY_URL=http://backend:8000
docker compose -p prometheus_platform \
  exec -T client-agent python -c "
import os, urllib.request as u
r = u.Request(
 'http://localhost:8000'
 '/discovery/refresh',
 method='POST', headers={
 'Authorization': 'Bearer '
 + os.environ['AGENT_SECRET']})
print(u.urlopen(r).read())"
```

{.small}
Force a discovery refresh. The images have Python but no `curl`.
:::
::::

::: callout
Reset ladder, from least to most destructive: `docker compose -p prometheus_platform restart <svc>` → `make restart` → `make up` → `make clear-admin-users` → `make clobber` (deletes users, keys, and history) → `make down-v` (also the caches).
:::
