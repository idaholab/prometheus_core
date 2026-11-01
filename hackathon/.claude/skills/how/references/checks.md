# Checks

Facts as of `prometheus_core` `devel` 2026-10-31, after #310 and #322 (`prometheus_api` 0.15, LiteLLM removed: the backend is the agent registry and A2A gateway). When the code disagrees with this file, the code is correct.

Each check has a stable id; `/diagnose` runs them by tag or by symptom (`troubleshooting.md`).
Fix kinds: **safe** (applied, then explained), **yes** (asked first), **you** (only you: a secret,
a browser step, an install). Placeholders: `<root>`, `<platform>`, `<agent>`, `<project>`
(the agent folder name), `<service>` (`<slug>-agent`; `conventions.md`, "Find your agent"), `<route-key>`, `<pin>` (`base-image-pin`), `<KEY>`. Default ports 5150,
8600, 6379 (local DeepLynx 3000, 5000). Run bottom up: a low failure often causes the ones above it.

## Secrets in these commands

No command prints a secret (`conventions.md`). Test a key without printing it: `1` is a real
value, `0` is missing, empty, or a placeholder; the last line wins.

```sh
grep '^<KEY>=' <file> | tail -n 1 | grep -cvE '^<KEY>=(""|sk-ant-\.\.\.|sk-change-me|change-me.*|your-.*)?$'
```

Print only `PROMETHEUS_API_BASE_IMAGE_HASH`, `LLM_CONFIG_PROFILE`, `LLM_CONFIG_FILE`,
`USER_IDENTITY_REQUIRED`, `DEBUG_AGENTS`, `DEEPLYNX_BASE_URL`, and `*_PORT` values.

## LLM profile → key

| profile | key (`sdk/prometheus_api/llm_configs/*.yaml`; deck 03, A15) |
|---|---|
| (none) | required: no default. `registry` is rejected by `make init-env` (no LLM proxy on the platform) |
| `ollama` | none (local aliases from `ollama cp <model> default|small|medium|large|vision`) |
| every other profile | `LLM_API_KEY` (+ `EMBEDDING_API_KEY` for embeddings under `anthropic` / `anl_asksage`) |

The template compose forwards `LLM_CONFIG_PROFILE` (`:?`, so compose stops when it is empty),
`LLM_API_KEY` and `EMBEDDING_API_KEY` (`agent-template/agent_template/docker-compose.yml`).

## Laptop

### tools
Tags: preflight. Fix: you. Run: `make --version | head -n 1; git --version; python3 --version; uv --version` Expect four versions (Python 3.12 tested; deck 03, bonus). Failure: `command not found` (`make up` runs `scripts/init_env.py` with `python3`). Fix: install it; uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
### repo-access
Tags: preflight. Fix: you. Run: `gh auth status --hostname github.com; gh repo view idaholab/prometheus_core --json name -q .name` (no `gh`: `ssh -T git@github.com`, which prints "Hi <you>!" and exits 1) Expect "Logged in", then `prometheus_core`. Never add `--show-token`. Failure: "not logged in", "Could not resolve to a Repository", "Permission denied (publickey)". Fix: `gh auth login` in your own terminal, or an SSH key (deck 02, bonus).
### docker
Tags: preflight, diagnose. Fix: you. Run: `docker info --format 'server {{.ServerVersion}}, memory {{.MemTotal}} bytes'; docker compose version --short` Expect a server version and Compose 2.20+ (`include:`, `additional_contexts`). Failure: "Cannot connect to the Docker daemon", old Compose, exit 137 (memory). Fix: start or update Docker Desktop, raise its memory. Podman is not supported.
### siblings
Tags: preflight, diagnose. Fix: you. Run: `cd <root>/.. && test -f prometheus_core/agent-template/setup_agent.py && test -f prometheus_core/platform/Makefile && echo ok` Expect `ok`. `setup_agent.py` reads `../platform/.env` inside the monorepo (`PLATFORM_ENV_PATH` in `setup_agent.py`). Fix: clone `prometheus_core` next to this repository (deck 02).
### personal-skills
Tags: preflight. Fix: you. Run: `d="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"; for s in create-agent how diagnose; do test -e "$d/$s" && echo "$s"; done; echo done` Expect only `done`. A name above it is a personal skill that runs instead of the hackathon skill. Fix: rename it in your own terminal (`mv ~/.claude/skills/diagnose ~/.claude/skills/my-diagnose`), then start a new session.
### base-image-pin
Tags: preflight, diagnose. Fix: yes. Run: `cd <platform> && grep -nE '^(LOCAL_SDK|PROMETHEUS_API_BASE_IMAGE_HASH)=' .env` Expect `LOCAL_SDK=true` (the base image `prometheus_api:local` is built from `../sdk`, `Makefile:19-31`); then `<pin>` is `local`. Without it the build pulls `containers.github.inl.gov/genesis/prometheus_api` (`registry-login`). Failure: an empty `PROMETHEUS_API_BASE_IMAGE_HASH=` line: "invalid reference format". Fix: `LOCAL_SDK=true` in `.env`, remove the empty line, then a platform `make up`.
### registry-login
Tags: preflight, diagnose. Fix: you. Only without `LOCAL_SDK=true` (`base-image-pin`). Run: `docker pull -q containers.github.inl.gov/genesis/prometheus_api:<pin>` Expect the image reference. Failure: `unauthorized`/`denied` (no login, no `read:packages`, no org access); `manifest unknown` (bad pin); `dial tcp`/`no such host` (off the INL network or VPN). Fix, in your own terminal (paste the classic PAT at the first line; it never goes into the chat or a file; deck 03, slide 15):
  ```sh
  read -rs GITHUB_PAT
  echo "$GITHUB_PAT" | docker login containers.github.inl.gov --username <you> --password-stdin; unset GITHUB_PAT
  ```
### platform-env
Tags: preflight, diagnose. Fix: yes. Run: `cd <platform> && test -f .env && for k in AGENT_SECRET REDIS_PASSWORD ADMIN_DB_PASSWORD BACKEND_JWT_SECRET ADMIN_DB_ENCRYPTION_KEY LLM_CONFIG_PROFILE; do printf '%s %s\n' "$k" "$(grep "^$k=" .env | tail -n 1 | grep -cvE "^$k=(\"\"|sk-ant-\.\.\.|sk-change-me|change-me.*|your-.*)?\$")"; done` Expect six lines ending in `1`. `ADMIN_DB_ENCRYPTION_KEY 0`: no signing key is created (`signing-key`); `LLM_CONFIG_PROFILE 0` or `registry`: compose stops (`llm-key`). Failure: no output (no `.env`, `Makefile:130`); `BACKEND_JWT_SECRET 0` stops the backend ("jwt_secret is not configured", `backend/app/main.py:39-41`). Fix: `make init-env` (fills blank secrets, asks for the profile and key), then `agent-env-sync`.
### ports-free
Tags: diagnose. Fix: yes. Run, with the platform stopped: `for p in 5150 8600 6379; do printf '%s ' "$p"; lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1; f=1} END {if (!f) print "free"}'; done` Expect `free` three times. Failure: a process (an old stack, a local Redis; macOS AirPlay holds 5000 for a local DeepLynx). Fix: `make down` in that stack, or change the `*_PORT` value. WSL: use `ss -ltn` (unverified).
### platform-current
Tags: diagnose. Fix: you. Run: `git -C <platform> log -1 --format='%h %cs %s'; git -C <platform> ls-files ../common/certs | head -n 3` Expect a recent commit and files under `common/certs/`; without them, `npm ci` or `pip` gets SSL errors on the INL network. Fix: pull the latest `devel`, then a platform `make up`.

## Stack

### stack-ps
Tags: preflight, diagnose. Fix: yes. Run: `docker ps -a --filter label=com.docker.compose.project=prometheus_platform --format '{{.Names}}\t{{.Status}}'` Expect all `Up (healthy)` (`make up` waits for that, then runs `make check`). Services (containers `prometheus_platform-<service>-1`): `admin-db`, `redis`, `backend`, `client-agent`, `frontend-dev` (`frontend-prod` with `PROFILE=prod`), `form-filler-agent`, `synthesis-agent`; `osti-research-agent` with `OPTIONAL_AGENTS=true`; the debug agents with `DEBUG_AGENTS=true`. No `litellm-*` container. Failure: no lines (stopped); `Exited`/`Restarting` (`docker compose -p prometheus_platform logs --no-log-prefix --tail 100 <service> 2>&1 | grep -iE 'error|exception|traceback|failed' | tail -n 20`); `(unhealthy)` (`backend-logs`). Fix: a platform `make up` (it empties the registry: stop your agent first).

## Store

### store
Tags: diagnose. Fix: yes. Run: `docker compose -p prometheus_platform exec -T redis sh -c 'valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" ping'; docker compose -p prometheus_platform exec -T admin-db pg_isready -U admin` Expect `PONG` and "accepting connections". Fix: `docker compose -p prometheus_platform restart <service>`, or a platform `make restart`.

## Registry

### platform-check
Tags: preflight, diagnose. Fix: yes. Run: `cd <platform> && make check` Expect it to finish without an error: backend `/healthz`, the frontend, and every in-tree agent listed in `/v1/agents` (`scripts/check_platform.py`). It times out after `CHECK_TIMEOUT` (300 s). Failure names what is missing. Fix: the named check below.
### registry-auth
Tags: preflight, diagnose. Fix: yes. Run: `set -a; source <platform>/.env; set +a; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents` Expect `200`. `401`: wrong `AGENT_SECRET`; `503`: the backend has no `AGENT_SECRET` (`backend/app/routers/agent_registry.py:65-75`). Fix: correct the `.env`, then a platform `make restart`.
### registry-agents
Tags: preflight, diagnose. Fix: safe. Run: `set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents | python3 -c 'import json,sys; print(sorted(a["agent_name"] for a in json.load(sys.stdin)))'` (the backend never returns `static_headers`). Expect `form-filler-agent`, `nuclear-analysis-client-agent`, `synthesis-agent` (with `OPTIONAL_AGENTS=true` also `osti-research-agent`; with `DEBUG_AGENTS=true` the debug agents), and `<route-key>`. Failure: a `TypeError` (`registry-auth`); your key missing (`agent-running`, `agent-registered-log`). Fix: `docker compose -p <project> restart <service>`.
### registry-details
Tags: diagnose. Fix: yes.
```sh
set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents | python3 -c 'import json,sys
for a in json.load(sys.stdin): c = a.get("agent_card_params") or {}; print(a["agent_name"], c.get("url"), [s.get("id") for s in c.get("skills", [])])'
python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c["name"].lower().replace(" ", "-"), [s["id"] for s in c["skills"]])' <agent>/agent_card.json
```
- Expect your route key once, and none of your skill ids in another list. A POST replaces the entry of the same name, so a second agent with the same key replaces the first (`sdk/prometheus_api/agent/registry.py`, `AgentRegistryClient.register_once_async`); the same skill id goes to the first tool (`client-agent/orchestrator/skills.py:16-19`). Fix: rename (`/create-agent improve my card`), then `make up` in the agent folder.
### llm-call
Tags: preflight, diagnose. Fix: you. There is no LLM proxy to curl: agents call the provider directly. Ask one chat question, then read the agent or client-agent log for `LLMProviderError` (status code and one-line reason), `LLMEndpointUnavailableError` (endpoint unreachable), or `LLMConfigError` (profile). Fix: `llm-key`, `llm-key-in-agent-env`; no key: the LLM mentor (`mentors.md`).

## Backend

### backend-health
Tags: preflight, diagnose. Fix: yes. Run: `curl -s localhost:8600/healthz` Expect `{"status":"ok"}` (`backend/app/routers/health.py:6-8`). No output: `backend-logs`.
### backend-logs
Tags: diagnose. Fix: yes. Run: `docker compose -p prometheus_platform logs --no-log-prefix --tail 200 backend 2>&1 | grep -iE 'error|exception|traceback|jwt_secret|alembic|password authentication' | tail -n 20` Failure: "jwt_secret is not configured" (`platform-env`); an alembic error (migrations run first, `backend/docker-entrypoint.sh:14-15`); `password authentication failed for user "admin"` (`ADMIN_DB_PASSWORD` changed after the first start: restore it, or `make down-v`); "libGL.so.1" (old image: a platform `make up`).
### chat-ui
Tags: preflight, diagnose. Fix: yes. Run: `curl -s -o /dev/null -w '%{http_code}\n' localhost:5150/` Expect `200` (8080 with `PROFILE=prod`). `000`: the frontend is stopped, or `PROFILE=` is empty (`Makefile:39-42`).
### admin-user
Tags: preflight, diagnose. Fix: you. Run: `curl -s localhost:8600/api/setup/status` Expect `{"needs_setup":false}`. `true`: open http://localhost:5150 and complete the wizard; the first user is admin.
### signing-key
Tags: preflight, diagnose. Fix: yes. Run: `docker compose -p prometheus_platform exec -T admin-db psql -U admin -d admin -tAc "SELECT count(*) FROM signing_keys WHERE is_active"` Expect `1`. `0`: every turn fails with "No 'userToken' found in message metadata and USER_IDENTITY_REQUIRED=true" (`prometheus_api/prometheus_api/agent/base.py:403-406`); The backend creates and activates one on first start (`backend/app/signing_keys.py`), unless `USER_IDENTITY_PRIVATE_KEY` is set or `ADMIN_DB_ENCRYPTION_KEY` is missing or invalid (it then logs a warning: `backend-logs`). Fix: a valid `ADMIN_DB_ENCRYPTION_KEY` (`make init-env` generates one), no `USER_IDENTITY_PRIVATE_KEY`, then a platform `make restart`. Local only, after a yes: `USER_IDENTITY_REQUIRED=false` in both `.env` files, then a platform `make restart`.
### identity-required-match
Tags: preflight, diagnose. Fix: yes. Run: `grep '^USER_IDENTITY_REQUIRED=' <platform>/.env <agent>/.env` Expect the same value, or `true` (default) and no agent line. `false` only in the platform: the agent rejects each call with "No 'userToken' found…" (`client-agent/tool_discovery.py:445-454`). Fix: add the line to the agent `.env`, then `make up` in the agent folder.
### llm-key
Tags: preflight, diagnose. Fix: you. Run: `grep -E '^LLM_CONFIG_(PROFILE|FILE)=' <platform>/.env`, then the key test for the profile's key ("LLM profile → key"). Expect a profile (not empty, not `registry`) and `1`. A set `LLM_CONFIG_FILE` wins: read its `api_key` names. Fix: blank the profile and run `make init-env` for the menu, or set both in your editor; then a platform `make restart`.

## DeepLynx

### deeplynx-env
Tags: preflight, diagnose. Fix: yes. **Required**: every agent writes an execution record and exits at startup without it (deck 03, Local DeepLynx 1-3). Run: `for k in DEEPLYNX_KEY DEEPLYNX_SECRET DEEPLYNX_ORG_ID DEEPLYNX_PROJECT_ID; do printf '%s %s\n' "$k" "$(grep "^$k=" <platform>/.env | tail -n 1 | grep -cvE "^$k=(\"\"|your-.*|change-me.*)?\$")"; done; grep '^DEEPLYNX_BASE_URL=' <platform>/.env | tail -n 1` Expect four `1` lines (or `DEEPLYNX_JWT_TOKEN` instead of key + secret, never both) and the local URL `http://prometheus.host.internal:5000/api/v1/`. Failure: "Invalid required DeepLynx configuration: …" in an agent log (`sdk/prometheus_api/agent/base.py`, `_validate_deeplynx_configuration`); "…but DeepLynx storage is not configured." on uploads. Fix: `artifacts.md` ("Local DeepLynx"), a platform `make restart`, `agent-env-sync`.
### deeplynx-backend
Tags: preflight, diagnose. Fix: you.
```sh
docker compose -p prometheus_platform exec -T backend python - <<'EOF'
from prometheus_api.storage_client import ConnectionConfig, StorageClient
cfg = ConnectionConfig.from_env()
with StorageClient(cfg) as c:
    print("OK", cfg.base_url, len(c.items.list(page_size=5).items), "items")
EOF
```
- Expect `OK <base URL> <n> items`. Failure: `AuthenticationError`/401 (key and secret swapped or cut); connection refused to `prometheus.host.internal` (local DeepLynx stopped; host firewall; AirPlay on :5000); "Invalid required DeepLynx configuration: missing …" (empty ids).
### deeplynx-agent
Tags: diagnose. Fix: yes. Run the `deeplynx-backend` command with `docker compose -p <project> exec -T <service>`. Expect `OK` and the same base URL; a `deeplynx://` URI resolves only with the same org and project. Fix: `agent-env-sync`.

## Your agent

### agent-running
Tags: diagnose. Fix: safe. Run: `docker compose -p <project> ps -a --format '{{.Name}}\t{{.Status}}'` Expect `Up`. No line or `Exited`/`Restarting`: `agent-logs` (often DeepLynx or `LLM_CONFIG_PROFILE`). Fix: `make up` in the agent folder.
### agent-registered-log
Tags: diagnose. Fix: safe. Run: `docker compose -p <project> logs --no-log-prefix <service> 2>&1 | grep -E "Registered '|Registry registration attempt|Failed to register|Continuing without registration|no longer listed|Checking the registry|Registry check" | tail -n 5` Expect `Registered '<route-key>' with LiteLLM at http://backend:8000` within 30 s (the SDK's log wording is old; the URL is the backend). An agent still logging `litellm` in the URL was scaffolded before the template fix: set `REGISTRY_URL=http://backend:8000` and `LITELLM_MASTER_KEY: ${AGENT_SECRET}` in its compose. Failure: "attempt n/11 failed: …401" (`agent-env-sync`); a connection error (backend down, wrong network mode); "Continuing without registration". An INFO line "Checking the registry still lists this agent every 5s" means the agent has the re-registration checks (`AgentRegistryClient.keep_registered_async`); no such line means it registers only at startup (an older base image, such as the pin in `platform/Makefile`, `PROMETHEUS_API_BASE_IMAGE_HASH`). A failing check logs "Registry check failed (<type> <status>)" once at WARNING, then at DEBUG until one succeeds. `Registered` but not in `registry-agents`: the platform restarted. An agent with the checks logs "no longer listed by the registry … re-registering" and is back within about 5 s (then `discovery-refresh`); without them, or if it stays missing: fix the cause, then `docker compose -p <project> restart <service>`.
### agent-logs
Tags: diagnose. Fix: yes. Run: `docker compose -p <project> logs --no-log-prefix --tail 200 <service> 2>&1 | grep -E 'Traceback|Error|Identity verification failed|ModuleNotFoundError|401' | grep -v 'Registry check failed' | tail -n 20` (registry check failures: `agent-registered-log`); traceback: `... | grep -A 25 'Traceback' | tail -n 60` The SDK logs only parameter keys (`base.py:479`); your code can log values: read before you quote. "Invalid required DeepLynx configuration" → `deeplynx-env`, `agent-env-sync`; `ModuleNotFoundError` → `dockerfile-copy`; "AGENT_SECRET_REQUIRED=true but AGENT_SECRET is not set" → `agent-env-sync`; "Identity verification failed" → `signing-key`, `identity-required-match`, `agent-env-sync`; `LLMAliasError` → `llm-flavors`; `LLMConfigError` → `llm-profile-valid`; `LLMProviderError` 401/403 → `llm-key-in-agent-env`; "Error during execution" (`base.py:282`) → your code, `/diagnose trace my last chat`.
### agent-env-sync
Tags: preflight, diagnose. Fix: yes. The keys that `setup_agent.py` copies (`PLATFORM_SECRET_KEYS` and `PLATFORM_DEEPLYNX_KEYS` in `setup_agent.py`); a copy goes stale when the platform `.env` changes. Only the DeepLynx client keys: the other `DEEPLYNX_*` lines in the platform `.env` are the DeepLynx server's own secrets.
```sh
P=<platform>/.env; A=<agent>/.env; for k in AGENT_SECRET REDIS_PASSWORD LLM_API_KEY USER_IDENTITY_PUBLIC_KEY USER_IDENTITY_ISS USER_IDENTITY_AUD LLM_CONFIG_PROFILE DEEPLYNX_BASE_URL DEEPLYNX_KEY DEEPLYNX_SECRET DEEPLYNX_JWT_TOKEN DEEPLYNX_ORG_ID DEEPLYNX_PROJECT_ID DEEPLYNX_DATA_SOURCE_ID; do cmp -s <(grep "^$k=." "$P" | tail -n 1) <(grep "^$k=." "$A" | tail -n 1) && echo "$k same" || echo "$k differs"; done
```
- Expect `same` (`LLM_CONFIG_PROFILE differs` is fine by choice). `AGENT_SECRET` → registration 401s; `LLM_API_KEY` → `LLMProviderError`; `REDIS_PASSWORD` → Valkey errors; `USER_IDENTITY_*` → issuer or audience mismatch; `DEEPLYNX_*` → URIs that do not resolve. Fix: copy the differing lines without printing them, then `make up` in the agent folder:
  ```sh
  P=<platform>/.env; A=<agent>/.env; for k in <KEY> <KEY>; do grep -v "^$k=" "$A" > "$A.tmp" && grep "^$k=" "$P" | tail -n 1 >> "$A.tmp" && mv "$A.tmp" "$A"; done
  ```
### agent-base-image
Tags: preflight, diagnose. Fix: yes. Run: `grep -E '^(LOCAL_SDK|PROMETHEUS_API_BASE_IMAGE_HASH)=' <agent>/.env | tail -n 2` Expect `LOCAL_SDK=true` when the platform has it (`setup_agent.py` copies it). None: the agent pulls `latest` from `containers.github.inl.gov`. Fix: add the line, then `make up` in the agent folder.
### agent-lockfile
Tags: preflight, diagnose. Fix: yes. Run: `cd <agent> && git ls-files --error-unmatch uv.lock >/dev/null && uv lock --check && echo ok` Expect `ok`. Failure: the build stops with "ERROR: uv.lock not found…", or `uv sync --locked` fails (stale lock). Fix: `uv sync` (or `uv add <pkg>`), then commit `pyproject.toml` with `uv.lock` and `make up`.
### llm-client-pattern
Tags: preflight, diagnose. Fix: yes (code). Run: `grep -rnE 'llm_client\(|LLMClient\(|with_api_key|proxy_url|LITELLM_MASTER_KEY' --include='*.py' --exclude-dir=.venv <agent>` Expect `async with self.llm_client(context) as llm:` and no `with_api_key`/`LITELLM_MASTER_KEY` swap (the old `registry` pattern; deck 04). Fix: `llm.md`, then `make up`.
### llm-key-in-agent-env
Tags: preflight, diagnose. Fix: yes. LLM 401, cause 1. Run the key test on `<agent>/.env` for the profile's key. Expect `1`. Fix: copy it with the `agent-env-sync` fix, or add it in your editor; then `make up`.
### llm-key-in-container
Tags: preflight, diagnose. Fix: yes. LLM 401, cause 2. Run: `grep -cE '^[[:space:]]+<KEY>:' <agent>/docker-compose.yml; docker compose -p <project> exec -T <service> sh -c 'case "${<KEY>:-}" in ""|"sk-ant-..."|change-me*|sk-change-me*) echo missing ;; *) echo set ;; esac'` Expect `1`, `set`. `0`: `environment:` does not forward it (an agent scaffolded before `LLM_API_KEY`). `missing`: the `.env` lacks it, or the container is older. Fix: add `      <KEY>: ${<KEY>:-}` under `environment:`, then `make up`.
### llm-flavors
Tags: diagnose. Fix: yes (code). Run: `grep -rnoE '\.(small|medium|large|vision|embed|embedding)\(|model="[a-z_]+"' --include='*.py' --exclude-dir=.venv <agent>` Compare with the profile YAML (`sdk/prometheus_api/llm_configs/<profile>.yaml`, `model_name:`). Failure: `LLMAliasError: LLM alias 'small' is not available. …` Fix: a defined flavor, an own `LLM_CONFIG_FILE`, or another profile (`llm.md`).
### llm-profile-valid
Tags: diagnose. Fix: yes. Run: `docker compose -p <project> exec -T <service> python -c "from prometheus_api.llm_configs import list_llm_config_profiles as p; print(p())"` Expect the agent's profile in the list (`amsc`, `anl_asksage`, `anthropic`, `genesis`, `inl_hpc`, `inl_litellm`, `ollama`, `openai`; `registry` is listed but rejected on the platform). Failure: `LLMConfigError: Invalid LLM_CONFIG_PROFILE: …` (lists the installed ones). Fix: correct the name, then `make up`.
### dockerfile-copy
Tags: diagnose. Fix: yes. Run: `cd <agent> && ls *.py; grep -n '^COPY' Dockerfile; docker compose -p <project> exec -T <service> ls /app` Expect a `COPY` line per own module; the template copies only `agent.py`, `agent_card.json`, `prompts/`, `workflows/` (`agent_template/Dockerfile:46-49`). `ModuleNotFoundError: No module named 'x'`: add `COPY x.py /app/x.py`, or `uv add <package>` (never `prometheus_api`) and commit `uv.lock`; then `make up`.
### card-in-image
Tags: diagnose. Fix: safe. Run: `for f in agent_card.json agent.py; do docker compose -p <project> exec -T <service> cat /app/$f | cmp -s - <agent>/$f && echo "$f same" || echo "$f differs"; done` Expect `same` twice. `differs`: an old image (a restart keeps it). Fix: `make up` in the agent folder, then `discovery-refresh`.
### client-agent-reaches-agent
Tags: diagnose. Fix: yes. Run: `docker compose -p prometheus_platform exec -T client-agent python -c "import urllib.request as u; print(u.urlopen('<url>/healthz', timeout=5).read())"` (`<url>` from `registry-details`) Expect `b'{"ok":true,...}'`. A connection error: the client-agent falls back to the registry copy of the card (`tool_discovery.py:133-145`), but cannot call the agent. Fix: the internal network mode (no `EXTERNAL_AGENT_*` lines), then `make up` (`run-and-register.md`).

## Discovery

### discovery-refresh
Tags: diagnose. Fix: safe.
```sh
docker compose -p prometheus_platform exec -T client-agent python -c "import os, urllib.request as u; r=u.Request('http://localhost:8000/discovery/refresh', method='POST', headers={'Authorization':'Bearer '+os.environ['AGENT_SECRET']}); print(u.urlopen(r).read())"
docker compose -p prometheus_platform logs --no-log-prefix --since 2m client-agent 2>&1 | grep -E "Cached capability: .* from <route-key>|Capability cache refreshed"
```
- Expect `b'{"status":"ok","trigger":"api","tools":N,...}'` (`orchestrator/runtime.py:200-206`) and one `Cached capability` line per skill. No line for your agent: `registry-agents`, `client-agent-reaches-agent`. Refresh fails: `docker compose -p prometheus_platform restart client-agent` (run `activity` first).
### activity
Tags: preflight, diagnose. Fix: none (informs a restart).
```sh
docker compose -p prometheus_platform exec -T redis sh -c 'for k in $(valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "agent:status:*"); do valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" GET "$k"; done' | python3 -c 'import json,sys; [print(d.get("timestamp"), "final" if d.get("final") else "open") for d in map(json.loads, filter(None, sys.stdin.read().splitlines()))]'
```
- Prints times and flags only (kept 15 min, `runtime.py:155`). A recent `open` line: a turn can still run (`/tasks` shows background tasks). Wait, or say what the restart stops and ask.
