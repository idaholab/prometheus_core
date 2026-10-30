# Conventions for the hackathon skills

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

## Find the folders

- The root is `git rev-parse --show-toplevel`. A session can start in a subfolder: start from the root.
- The platform is `<root>/../prometheus_core/platform`, the template `<root>/../prometheus_core/agent-template`.
  When one is missing, ask for its path once, and use it for the session.
- The Bash tool resets the working folder between calls. Put `cd` and its command in one call.
- Ports: read them from the platform `.env`, else the defaults that the KB shows: `FRONTEND_DEV_PORT` 5150
  (the UI), `FRONTEND_PROD_PORT` 8080, `BACKEND_PORT` 8600 (also the agent registry), `REDIS_LOCAL_PORT` 6379.

## Find your agent

1. The candidates hold both `agent_card.json` and `.env`: `<root>/practice/*/`, `<root>/agents/*/`, `<root>/../hello-*/`.
2. With one candidate, use it. With more, ask once, and keep the answer for the session.
3. The Compose project is the folder name in lowercase (`<project>`, e.g. `hello-max`); the service is
   `grep -m1 -E '^  [a-z0-9_-]+:$' docker-compose.yml` (`<slug>-agent`, `<service>`). The container is
   `<project>-<service>-1`. Address it by project and service, from any folder:
   `docker compose -p <project> logs --no-log-prefix <service>`. The platform is the project
   `prometheus_platform` (unless `COMPOSE_PROJECT_NAME` is set in `platform/.env`; participants keep the
   default): `docker compose -p prometheus_platform exec -T redis ...`. Plain `docker compose` in the
   agent folder fails (the network is in the `net_*` overlay files), and `docker exec <slug>-agent` or
   `docker exec agent-valkey` (old docs) fails with "No such container".
4. The route key is the card `name` in lowercase, spaces changed to hyphens: "Hello Max Agent" gives `hello-max-agent`.

## Secrets

A secret is any `.env` value, token, PAT, or password. Never show or ask for one; the user edits the `.env` in
an editor, then you check with `grep -c`. Settings you may print with an exact `grep '^NAME='`:
`PROMETHEUS_API_BASE_IMAGE_HASH`, `LLM_CONFIG_PROFILE`, `LLM_CONFIG_FILE`, `USER_IDENTITY_REQUIRED`, `DEBUG_AGENTS`, `*_PORT`.

- Check a key by a count: `grep -c '^KEY=.' <file>`. A placeholder (`sk-ant-...`, `change-me...`, empty) is missing.
- Never run `cat .env`; `env`, `printenv`, or `docker compose exec <service> env` without a name filter;
  `docker compose config`; `docker inspect`; `curl -v`; `set -x`.
- Load a key and use it in the same Bash call. Never echo it:
  `set -a; source <platform>/.env; set +a; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents`
- `GET /v1/agents` never returns `static_headers`, but the cards are long. Print only the names:
  `set -a; source <platform>/.env; set +a; curl -s -H "Authorization: Bearer $AGENT_SECRET" localhost:8600/v1/agents | python3 -c 'import json,sys; print(sorted(a["agent_name"] for a in json.load(sys.stdin)))'`
- Compare without printing: `cmp -s <(grep '^AGENT_SECRET=' <platform>/.env) <(grep '^AGENT_SECRET=' <agent>/.env) && echo same`
- Never commit a `.env` (the root `.gitignore` ignores `.env*`). A pasted secret must be rotated.

## Before a write

1. For a folder in the repository, run `git status --short <folder>`. With uncommitted changes, offer a commit first.
2. Show the change as a diff.
3. Ask: accept, edit, or skip. Apply only an accepted change.

Write only in the user's agent folder and `<root>/.explainers/` (the rules of `CLAUDE.md`). Read files outside
the repository with read-only Bash (`sed -n`, `grep -n`, `ls`): `Read`, `Grep`, `Glob` ask there.

## Safe fixes

Apply these, then say what you did and why. Before a restart, check for a running turn, an open form,
or a background task (`/tasks`), and say what the restart stops.

- **`make up` in the agent folder** after an edit to `agent.py`, the card, `pyproject.toml`, the
  `Dockerfile`, `docker-compose.yml`, or `.env`. The image holds the code and the card, and the container
  reads `environment:` only when it is created. A plain restart keeps the old ones.
- **`docker compose -p <project> restart <service>`** registers the agent again after a platform restart. Only your own project.
- **The discovery refresh** makes the orchestrator see a change now, not within 60 s. Expect
  `b'{"status":"ok","trigger":"api","tools":N,...}'`:
  `docker compose -p prometheus_platform exec -T client-agent python -c "import os, urllib.request as u; r=u.Request('http://localhost:8000/discovery/refresh', method='POST', headers={'Authorization':'Bearer '+os.environ['AGENT_SECRET']}); print(u.urlopen(r).read())"`
- **`docker compose -p prometheus_platform restart client-agent`** only when the refresh fails. It stops the background tasks.

## Fixes that need a yes

Ask before each one, and say why: an `.env` or `docker-compose.override.yml` edit; `docker login`;
`make clear-admin-users`; a platform target that empties the registry (`make up`, `up-fg`, `restart`,
`restart-fg`, `ng-up`, `ng-up-fg`, `ng-restart`, `ng-restart-fg`, `clear-agent-registry`, `down-v`).
Before one, or a platform `make down`, run `make down` in the agent folder (else "has active
endpoints"); after it, `make up` in the agent folder. Before `make down-v`, state the loss: all
conversations and sessions, the registry, the admin users, the signing keys, the identity-provider
settings, and the mesh cache. Then the setup wizard is necessary (the backend creates a new signing key).

## Open a file in the browser

macOS `open <file>`; Linux `xdg-open <file>`; WSL `wslview <file>`, else `explorer.exe "$(wslpath -w <file>)"`.

## Ask the user

`AskUserQuestion`: 1-4 questions, 2-4 options, a header of at most 12 characters, the recommended option first.
For a free-text value, offer 2-4 candidates; "Other" takes another (`teaching.md`).
A subagent (`Agent`, `general-purpose`) cannot ask the user: give it absolute paths and a return format.
Test each change in a fresh chat conversation (deck 04, slide 18): old results stay visible to the orchestrator.
