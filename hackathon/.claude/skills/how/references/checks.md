# Checks

Facts as of `prometheus_api` 95c32b5 (v0.13.0) and `prometheus_platform` `dev` 22fed42, 2026-10-05. When the code disagrees with this file, the code is correct.

Each check has a stable id; `/diagnose` runs them by tag or by symptom (`troubleshooting.md`).
Fix kinds: **safe** (applied, then explained), **yes** (asked first), **you** (only you: a secret,
a browser step, an install). Placeholders: `<root>`, `<platform>`, `<agent>`, `<container>`
(`container_name:`), `<route-key>`, `<pin>` (`base-image-pin`), `<KEY>`. Default ports 5150,
8600, 9977, 6379. Run bottom up: a low failure often causes the ones above it.

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
| `registry` (default) | none in the agent: it attaches `LITELLM_MASTER_KEY` (`llm-master-key-pattern`). The proxy uses the platform `LLM_API_KEY` (`platform/litellm_config.yaml:10`) |
| every other profile | `LLM_API_KEY` (+ `EMBEDDING_API_KEY` for embeddings under `anthropic` / `anl_asksage`) |

The template compose forwards `LLM_API_KEY` and `EMBEDDING_API_KEY`
(`agent-template/agent_template/docker-compose.yml`).

## Laptop

### tools
Tags: preflight. Fix: you. Run: `make --version | head -n 1; git --version; openssl version; python3 --version; uv --version` Expect five versions (Python 3.12 tested; deck 03, slide 14). Failure: `command not found` (`make up` needs `openssl`, `prometheus_platform/Makefile:275`). Fix: install it; uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
### repo-access
Tags: preflight. Fix: you. Run: `gh auth status --hostname github.inl.gov; for r in prometheus_platform prometheus_agent_template hackathon; do GH_HOST=github.inl.gov gh repo view genesis/$r --json name -q .name; done` (no `gh`: `ssh -T git@github.inl.gov`, which prints "Hi <you>!" and exits 1) Expect "Logged in", then three names. Never add `--show-token`. Failure: "not logged in", "Could not resolve to a Repository", "Permission denied (publickey)". Fix: `gh auth login --hostname github.inl.gov` in your own terminal, or an SSH key; read access: a mentor adds you to the team `open` (deck 02, slide 17).
### docker
Tags: preflight, diagnose. Fix: you. Run: `docker info --format 'server {{.ServerVersion}}, memory {{.MemTotal}} bytes'; docker compose version --short` Expect a server version and Compose 2.20+ (`include:`, `additional_contexts`). Failure: "Cannot connect to the Docker daemon", old Compose, exit 137 (memory). Fix: start or update Docker Desktop, raise its memory. Podman is not supported.
### siblings
Tags: preflight, diagnose. Fix: you. Run: `cd <root>/.. && ls -d prometheus_platform prometheus_agent_template && test -f prometheus_agent_template/setup_agent.py && test -f prometheus_platform/Makefile && echo ok` Expect both names and `ok`. `setup_agent.py` reads `../prometheus_platform/.env` (`setup_agent.py:21`). Fix: clone side by side (deck 02, slides 18-19).
### personal-skills
Tags: preflight. Fix: you. Run: `d="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"; for s in create-agent how diagnose; do test -e "$d/$s" && echo "$s"; done; echo done` Expect only `done`. A name above it is a personal skill that runs instead of the hackathon skill. Fix: rename it in your own terminal (`mv ~/.claude/skills/diagnose ~/.claude/skills/my-diagnose`), then start a new session.
### base-image-pin
Tags: preflight, diagnose. Fix: yes. Run: `cd <platform> && grep -n '^PROMETHEUS_API_BASE_IMAGE_HASH' .env; sed -n 's/^PROMETHEUS_API_BASE_IMAGE_HASH[[:space:]]*?=[[:space:]]*//p' Makefile` `<pin>` is the `.env` value when set, else the Makefile `?=` value (`95c32b5`, `Makefile:22`; `environment.md`, "The pin rule"). Failure: an empty `PROMETHEUS_API_BASE_IMAGE_HASH=` line: "invalid reference format" (deck 03, slide 17). Fix: remove the line, then a platform `make up`.
### registry-login
Tags: preflight, diagnose. Fix: you. Run: `docker pull -q containers.github.inl.gov/genesis/prometheus_api:<pin>` Expect the image reference. Failure: `unauthorized`/`denied` (no login, no `read:packages`, no org access); `manifest unknown` (bad pin); `dial tcp`/`no such host` (off the INL network or VPN). Fix, in your own terminal (paste the classic PAT at the first line; it never goes into the chat or a file; deck 03, slide 15):
  ```sh
  read -rs GITHUB_PAT
  echo "$GITHUB_PAT" | docker login containers.github.inl.gov --username <you> --password-stdin; unset GITHUB_PAT
  ```
### platform-env
Tags: preflight, diagnose. Fix: yes. Run: `cd <platform> && test -f .env && for k in AGENT_SECRET REDIS_PASSWORD LITELLM_MASTER_KEY LITELLM_DB_PASSWORD ADMIN_DB_PASSWORD BACKEND_JWT_SECRET LITELLM_LOCAL_PORT; do printf '%s %s\n' "$k" "$(grep "^$k=" .env | tail -n 1 | grep -cvE "^$k=(\"\"|sk-ant-\.\.\.|sk-change-me|change-me.*|your-.*)?\$")"; done` Expect seven lines ending in `1`. Failure: no output (no `.env`, `Makefile:130`); `BACKEND_JWT_SECRET 0` stops the backend ("jwt_secret is not configured", `backend/app/main.py:39-41`). Fix: `cp .env.example .env`, then `environment.md` ("Fill the platform .env"), then `agent-env-sync`.
### ports-free
Tags: diagnose. Fix: yes. Run, with the platform stopped: `for p in 5150 8600 9977 6379; do printf '%s ' "$p"; lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1; f=1} END {if (!f) print "free"}'; done` Expect `free` four times. Failure: a process (an old stack, a local Redis; macOS AirPlay holds 5000 for a local DeepLynx). Fix: `make down` in that stack, or change the `*_PORT` value. WSL: use `ss -ltn` (unverified).
### platform-current
Tags: diagnose. Fix: you. Run: `git -C <platform> log -1 --format='%h %cs %s'; git -C <platform> ls-files certs/INL.pem` Expect a recent commit and `certs/INL.pem`; without it, `npm ci` or `pip` gets SSL errors on the INL network. Fix: pull the latest `dev`, then a platform `make up`.

## Stack

### stack-ps
Tags: preflight, diagnose. Fix: yes. Run: `docker ps -a --filter label=com.docker.compose.project=prometheus_platform --format '{{.Names}}\t{{.Status}}'` Expect all `Up`; `litellm-db`, `admin-db`, `litellm-proxy`, `backend` also `(healthy)`. Containers: those four, `agent-valkey`, `client-agent`, `frontend-dev` (`frontend-prod` with `PROFILE=prod`), `form-filler-agent`, `osti-research-agent`, `synthesis-agent`; with `DEBUG_AGENTS=true` six debug agents. Failure: no lines (stopped); `Exited`/`Restarting` (`docker logs --tail 100 <name> 2>&1 | grep -iE 'error|exception|traceback|failed' | tail -n 20`); `(unhealthy)` (`backend-logs`). Fix: a platform `make up` (it empties the registry: stop your agent first).

## Store

### store
Tags: diagnose. Fix: yes. Run: `docker exec agent-valkey sh -c 'valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" ping'; docker exec litellm-db pg_isready -U litellm; docker exec admin-db pg_isready -U admin` Expect `PONG` and "accepting connections" twice. Fix: `docker restart <name>`, or a platform `make restart`.

## Registry

### litellm-health
Tags: preflight, diagnose. Fix: yes. Run: `curl -s localhost:9977/health/liveliness` Expect `"I'm alive!"`. No output: stopped, or still starting (30 s healthcheck). Fix: wait, then read the `litellm-proxy` log.
### registry-auth
Tags: preflight, diagnose. Fix: yes. Run: `set -a; source <platform>/.env; set +a; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:9977/v1/models` Expect `200`. `401`: the key is empty, or the `.env` changed after LiteLLM started. Fix: correct it, then a platform `make restart`.
### registry-agents
Tags: preflight, diagnose. Fix: safe. Run: `set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:9977/v1/agents | python3 -c 'import json,sys; print(sorted(a["agent_name"] for a in json.load(sys.stdin)))'` Never use `python3 -m json.tool` here: `static_headers` hold `AGENT_SECRET`. Expect `form-filler-agent`, `nuclear-analysis-client-agent`, `osti-research-agent`, `synthesis-agent` (with `DEBUG_AGENTS=true` also `artifact-debug-agent`, `corrosion-analysis-agent`, `material-data-agent`, `radiation-damage-analysis-agent`, `thermal-analysis-agent`, `thread-pattern-debug-agent`), and `<route-key>`. Failure: a `TypeError` (`registry-auth`); your key missing (`agent-running`, `agent-registered-log`). Fix: `docker restart <container>`.
### registry-details
Tags: diagnose. Fix: yes.
```sh
set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:9977/v1/agents | python3 -c 'import json,sys
for a in json.load(sys.stdin): c = a.get("agent_card_params") or {}; print(a["agent_name"], c.get("url"), [s.get("id") for s in c.get("skills", [])])'
python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c["name"].lower().replace(" ", "-"), [s["id"] for s in c["skills"]])' <agent>/agent_card.json
```
- Expect your route key once, and none of your skill ids in another list. The same key deletes the other entry (`prometheus_api/prometheus_api/agent/registry.py:123-130`); the same skill id goes to the first tool (`client-agent/orchestrator/skills.py:16-19`). Fix: rename (`/create-agent improve my card`), then `make up` in the agent folder.
### llm-models
Tags: preflight, diagnose. Fix: yes. Run: `set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:9977/v1/models | python3 -c 'import json,sys; print(sorted(m["id"] for m in json.load(sys.stdin)["data"]))'` Expect `['medium']` at least: the proxy defines only `medium` (`litellm_config.yaml:6-10`). A missing flavor: `llm-flavors`. Never edit `litellm_config.yaml`.
### llm-call
Tags: preflight, diagnose. Fix: you. Profile `registry` only (else ask one chat question). Run: `set -a; source <platform>/.env; set +a; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' localhost:9977/v1/chat/completions -d '{"model":"medium","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'` Expect `200`. `401` with `registry-auth` at `200`: the platform `LLM_API_KEY` is wrong. Fix: a working key in the `.env` (your editor), then a platform `make restart`; no key: the LLM mentor (`mentors.md`).

## Backend

### backend-health
Tags: preflight, diagnose. Fix: yes. Run: `curl -s localhost:8600/healthz` Expect `{"status":"ok"}` (`backend/app/routers/health.py:6-8`). No output: `backend-logs`.
### backend-logs
Tags: diagnose. Fix: yes. Run: `docker logs --tail 200 backend 2>&1 | grep -iE 'error|exception|traceback|jwt_secret|alembic|password authentication' | tail -n 20` Failure: "jwt_secret is not configured" (`platform-env`); an alembic error (migrations run first, `backend/docker-entrypoint.sh:14-15`); `password authentication failed for user "admin"` (`ADMIN_DB_PASSWORD` changed after the first start: restore it, or `make down-v`); "libGL.so.1" (old image: a platform `make up`).
### chat-ui
Tags: preflight, diagnose. Fix: yes. Run: `curl -s -o /dev/null -w '%{http_code}\n' localhost:5150/` Expect `200` (8080 with `PROFILE=prod`). `000`: the frontend is stopped, or `PROFILE=` is empty (`Makefile:39-42`).
### admin-user
Tags: preflight, diagnose. Fix: you. Run: `curl -s localhost:8600/api/setup/status` Expect `{"needs_setup":false}`. `true`: open http://localhost:5150 and complete the wizard; the first user is admin.
### signing-key
Tags: preflight, diagnose. Fix: you. Run: `docker exec admin-db psql -U admin -d admin -tAc "SELECT count(*) FROM signing_keys WHERE is_active"` Expect `1`. `0`: every turn fails with "No 'userToken' found in message metadata and USER_IDENTITY_REQUIRED=true" (`prometheus_api/prometheus_api/agent/base.py:403-406`); `USER_IDENTITY_PRIVATE_KEY` alone does not help (the JWKS lists only `admin-db` keys). Fix: Admin › Signing Keys → generate, then activate (deck 03, slide 5). Local only, after a yes: `USER_IDENTITY_REQUIRED=false` in both `.env` files, then a platform `make restart`.
### identity-required-match
Tags: preflight, diagnose. Fix: yes. Run: `grep '^USER_IDENTITY_REQUIRED=' <platform>/.env <agent>/.env` Expect the same value, or `true` (default) and no agent line. `false` only in the platform: the agent rejects each call with "No 'userToken' found…" (`client-agent/tool_discovery.py:445-454`). Fix: add the line to the agent `.env`, then `make up` in the agent folder.
### llm-key
Tags: preflight, diagnose. Fix: you. Run: `grep -E '^LLM_CONFIG_(PROFILE|FILE)=' <platform>/.env`, then the key test for the profile's key ("LLM profile → key"). Expect `1`. A set `LLM_CONFIG_FILE` wins: read its `api_key` names. Fix: add the key in your editor, then a platform `make restart`.

## DeepLynx

### deeplynx-env
Tags: preflight, diagnose. Fix: yes. Optional on Day 1; uploads and PNGs need it (deck 03, slide 9). Run: `for k in DEEPLYNX_KEY DEEPLYNX_SECRET DEEPLYNX_ORG_ID DEEPLYNX_PROJECT_ID; do printf '%s %s\n' "$k" "$(grep "^$k=" <platform>/.env | tail -n 1 | grep -cvE "^$k=(\"\"|your-.*|change-me.*)?\$")"; done; grep '^DEEPLYNX_BASE_URL=' <platform>/.env | tail -n 1` Expect four `1` lines (no URL line: `https://deeplynx.inl.gov/api/v1`). Failure: "…but DeepLynx storage is not configured." (`client-agent/orchestrator/service.py:461`); "invalid literal for int() with base 10: ''" (empty org or project id). Fix: a shared key or `artifacts.md` ("Local DeepLynx"), a platform `make restart`, `agent-env-sync`.
### deeplynx-backend
Tags: preflight, diagnose. Fix: you.
```sh
docker exec -i backend python - <<'EOF'
from prometheus_api.storage_client import ConnectionConfig, StorageClient
cfg = ConnectionConfig.from_env()
with StorageClient(cfg) as c:
    print("OK", cfg.base_url, len(c.items.list(page_size=5).items), "items")
EOF
```
- Expect `OK <base URL> <n> items`. Failure: `AuthenticationError`/401 (key and secret swapped or cut); connection refused to `prometheus.host.internal` (local DeepLynx stopped; host firewall; AirPlay on :5000); `ValueError` (empty ids).
### deeplynx-agent
Tags: diagnose. Fix: yes. Run the `deeplynx-backend` command with `docker exec -i <container>`. Expect `OK` and the same base URL; a `deeplynx://` URI resolves only with the same org and project. Fix: `agent-env-sync`.

## Your agent

### agent-running
Tags: diagnose. Fix: safe. Run: `docker ps -a --filter "name=^<container>$" --format '{{.Names}}\t{{.Status}}'` Expect `Up`. No line or `Exited`/`Restarting`: `agent-logs`. Fix: `make up` in the agent folder.
### agent-registered-log
Tags: diagnose. Fix: safe. Run: `docker logs <container> 2>&1 | grep -E "Registered '|Registry registration attempt|Failed to register|Continuing without registration" | tail -n 5` Expect `Registered '<route-key>' with LiteLLM at http://litellm-proxy:4000` within 30 s (11 attempts, backoff 2 s to 30 s, `registry.py:200-233`). Failure: "attempt n/11 failed: …401" (`agent-env-sync`); a connection error (LiteLLM down, wrong network mode); "Continuing without registration". `Registered` but not in `registry-agents`: the platform restarted. Fix: the cause, then `docker restart <container>`.
### agent-logs
Tags: diagnose. Fix: yes. Run: `docker logs --tail 200 <container> 2>&1 | grep -E 'Traceback|Error|Identity verification failed|ModuleNotFoundError|401' | tail -n 20`; traceback: `... | grep -A 25 'Traceback' | tail -n 60` The SDK logs only parameter keys (`base.py:479`); your code can log values: read before you quote. `ModuleNotFoundError` → `dockerfile-copy`; "AGENT_SECRET_REQUIRED=true but AGENT_SECRET is not set" → `agent-env-sync`; "Identity verification failed" → `signing-key`, `identity-required-match`, `agent-env-sync`; `LLMAliasError` → `llm-flavors`; LLM 401 → `llm-master-key-pattern`; "Error during execution" (`base.py:282`) → your code, `/diagnose trace my last chat`.
### agent-env-sync
Tags: preflight, diagnose. Fix: yes. The keys that `setup_agent.py` copies (`setup_agent.py:22-36`); a copy goes stale when the platform `.env` changes.
```sh
P=<platform>/.env; A=<agent>/.env; for k in AGENT_SECRET REDIS_PASSWORD LITELLM_MASTER_KEY USER_IDENTITY_PUBLIC_KEY USER_IDENTITY_ISS USER_IDENTITY_AUD LLM_CONFIG_PROFILE $(grep -o '^DEEPLYNX_[A-Z_]*' "$P" | sort -u); do cmp -s <(grep "^$k=." "$P" | tail -n 1) <(grep "^$k=." "$A" | tail -n 1) && echo "$k same" || echo "$k differs"; done
```
- Expect `same` (`LLM_CONFIG_PROFILE differs` is fine by choice). `LITELLM_MASTER_KEY` → 401s; `REDIS_PASSWORD` → Valkey errors; `USER_IDENTITY_*` → issuer or audience mismatch; `DEEPLYNX_*` → URIs that do not resolve. Fix: copy the differing lines without printing them, then `make up` in the agent folder:
  ```sh
  P=<platform>/.env; A=<agent>/.env; for k in <KEY> <KEY>; do grep -v "^$k=" "$A" > "$A.tmp" && grep "^$k=" "$P" | tail -n 1 >> "$A.tmp" && mv "$A.tmp" "$A"; done
  ```
### agent-base-image
Tags: preflight, diagnose. Fix: yes. Run: `grep '^PROMETHEUS_API_BASE_IMAGE_HASH=' <agent>/.env | tail -n 1` Expect `<pin>`. None: the agent builds from `latest` (`agent_template/docker-compose.yml:8`). Fix: add the pin, then `make up` in the agent folder.
### llm-master-key-pattern
Tags: preflight, diagnose. Fix: yes (code). LLM 401, cause 1. Run: `grep '^LLM_CONFIG_PROFILE=' <agent>/.env | tail -n 1; grep -rnE 'llm_client\(|LLMClient\(|with_api_key|proxy_url' --include='*.py' --exclude-dir=.venv <agent>` Expect, under `registry`: `cfg = LLMConfig.from_env()`, `if cfg.proxy_url: cfg = cfg.with_api_key(os.getenv("LITELLM_MASTER_KEY"))`, `async with self.llm_client(context, config=cfg) as llm:` (deck 04, A31). A plain `self.llm_client(context)` gets 401. Fix: `llm.md`, then `make up`.
### llm-key-in-agent-env
Tags: preflight, diagnose. Fix: yes. LLM 401, cause 2. Run the key test on `<agent>/.env` for the profile's key. Expect `1`. Fix: copy it with the `agent-env-sync` fix, or add it in your editor; then `make up`.
### llm-key-in-container
Tags: preflight, diagnose. Fix: yes. LLM 401, cause 3. Run: `grep -cE '^[[:space:]]+<KEY>:' <agent>/docker-compose.yml; docker exec <container> sh -c 'case "${<KEY>:-}" in ""|"sk-ant-..."|change-me*|sk-change-me*) echo missing ;; *) echo set ;; esac'` Expect `1`, `set`. `0`: `environment:` does not forward it (an agent scaffolded before `LLM_API_KEY`). `missing`: the `.env` lacks it, or the container is older. Fix: add `      <KEY>: ${<KEY>:-}` under `environment:`, then `make up`.
### llm-flavors
Tags: diagnose. Fix: yes (code). Run: `grep -rnoE '\.(small|medium|large|vision|embed|embedding)\(|model="[a-z_]+"' --include='*.py' --exclude-dir=.venv <agent>` Compare with `llm-models`. Failure: `LLMAliasError: LLM alias 'small' is not available. Available aliases: medium.` (`llm_client/client.py:36-41`). Fix: `medium` under `registry`, an own `LLM_CONFIG_FILE`, or another profile (`llm.md`).
### llm-profile-valid
Tags: diagnose. Fix: yes. Run: `docker run --rm containers.github.inl.gov/genesis/prometheus_api:<pin> python -c "from prometheus_api.llm_configs import LLM_CONFIG_PROFILES as p; print(p)"` Expect the agent's profile in the list (95c32b5: `registry`, `inl_hpc`, `inl_litellm`, `amsc`, `anthropic`, `openai`). Failure: "Unknown LLM config profile". Fix: correct the name, then `make up`.
### dockerfile-copy
Tags: diagnose. Fix: yes. Run: `cd <agent> && ls *.py; grep -n '^COPY' Dockerfile; docker exec <container> ls /app` Expect a `COPY` line per own module; the template copies only `pyproject.toml`, `agent.py`, `agent_card.json`, `prompts/`, `workflows/` (`agent_template/Dockerfile:34-37`). `ModuleNotFoundError: No module named 'x'`: add `COPY x.py /app/x.py`, or the PyPI package to `pyproject.toml` (never `prometheus_api`); then `make up`.
### card-in-image
Tags: diagnose. Fix: safe. Run: `for f in agent_card.json agent.py; do docker exec <container> cat /app/$f | cmp -s - <agent>/$f && echo "$f same" || echo "$f differs"; done` Expect `same` twice. `differs`: an old image (`docker restart` keeps it). Fix: `make up` in the agent folder, then `discovery-refresh`.
### client-agent-reaches-agent
Tags: diagnose. Fix: yes. Run: `docker exec client-agent python -c "import urllib.request as u; print(u.urlopen('<url>/health', timeout=5).read())"` (`<url>` from `registry-details`) Expect `b'{"ok":true,...}'`. A connection error: the LiteLLM card has no `inputSchema` (`tool_discovery.py:118-143`). Fix: the internal network mode (no `EXTERNAL_AGENT_*` lines), then `make up` (`run-and-register.md`).

## Discovery

### discovery-refresh
Tags: diagnose. Fix: safe.
```sh
docker exec client-agent python -c "import os, urllib.request as u; r=u.Request('http://localhost:8000/discovery/refresh', method='POST', headers={'Authorization':'Bearer '+os.environ['AGENT_SECRET']}); print(u.urlopen(r).read())"
docker logs --since 2m client-agent 2>&1 | grep -E "Cached capability: .* from <route-key>|Capability cache refreshed"
```
- Expect `b'{"status":"ok","trigger":"api","tools":N,...}'` (`orchestrator/runtime.py:200-206`) and one `Cached capability` line per skill. No line for your agent: `registry-agents`, `client-agent-reaches-agent`. Refresh fails: `docker restart client-agent` (run `activity` first).
### activity
Tags: preflight, diagnose. Fix: none (informs a restart).
```sh
docker exec agent-valkey sh -c 'for k in $(valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" --scan --pattern "agent:status:*"); do valkey-cli --no-auth-warning -a "$REDIS_PASSWORD" GET "$k"; done' | python3 -c 'import json,sys; [print(d.get("timestamp"), "final" if d.get("final") else "open") for d in map(json.loads, filter(None, sys.stdin.read().splitlines()))]'
```
- Prints times and flags only (kept 15 min, `runtime.py:155`). A recent `open` line: a turn can still run (`/tasks` shows background tasks). Wait, or say what the restart stops and ask.
