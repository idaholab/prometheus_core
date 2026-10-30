# 7 (follow-on): Agent folders on platformctl, in any repository

> **Status: Not started**

## Goal

Agent folders use the platform's own code for `.env` parsing, precedence and
Docker, instead of their own Makefile logic. This applies to agents scaffolded
from `agent-template/` anywhere: in this repo, next to it, or in a completely
separate repository that pins `prometheus_core` as a git submodule. See
`design.md`, "Agents in other repositories".

## Today

- `agent-template/agent_template/Makefile` reads `LOCAL_SDK` and the
  external-mode settings from `.env` with a `sed` one-liner (`read_dotenv`),
  which doesn't strip quotes.
- It checks for the network `prometheus_platform_agent-network` by its
  hardcoded name (`docker-compose.net_internal.yml` hardcodes it too), so a
  non-default `COMPOSE_PROJECT_NAME` breaks it.
- It checks the `prometheus_api:local` image and supports external mode
  (`EXTERNAL_AGENT_HOST`, `EXTERNAL_AGENT_PORT`).
- `agent-template/setup_agent.py` copies values from `../platform/.env`,
  found relative to the template in this checkout, with its own parser, and
  copies the precedence rule for `LOCAL_SDK`. (Its DeepLynx over-sharing is
  fixed separately, before this plan: it copies an explicit list of client
  keys.)
- `setup_agent.py` defaults the output to `../<slug>`, inside the
  `prometheus_core` checkout.
- Agents in other repositories find the platform only by convention: the
  hackathon clones `prometheus_core` next to the team repo (`siblings`
  check). `agents/requirements_agent` and `agents/bim_agent` are git-ignored
  here because they have their own repos.

## Work

- **Find a `prometheus_core` checkout from an agent folder**, in this order:
  a `prometheus_core` git submodule (from `git rev-parse --show-toplevel`);
  `PROMETHEUS_CORE=<path>` in the agent's `.env` or the environment;
  `../prometheus_core`. An uninitialized submodule stops with
  "run `git submodule update --init`". This gives the tool and the expected
  version.
- **Act on the running platform.** `up/down/logs --agent`, `config sync` and
  the network name use the platform that's running (found by its
  `io.prometheus.platform.root` label), not necessarily the checkout found
  above. When they differ, print both. When none is running, `up --agent`
  stops with the command to start it.
- **A small stub in the template** (`agent_template/platformctl`, stdlib,
  a few lines) does the discovery above and execs the real shim, so the
  agent Makefile calls one command and needs no shell discovery logic.
- **`--agent <dir>`** on the lifecycle commands, matching `doctor --agent`:
  `up --agent <dir>` (with `--foreground`), `down --agent <dir>`,
  `logs --agent <dir>`, with the network, base-image and external-mode
  checks. Lifecycle commands need `--agent` explicitly; only `doctor` infers
  the folder (in-tree agents also have an `agent_card.json`). Run from
  inside an agent folder, `up` without `--agent` says "Acting on the
  platform, not agent `<dir>`; use --agent". No separate `agent` group: it
  would read too close to `agents`.
- **`up --agent` closes the edit loop:** build, start, wait for
  registration, run `agents refresh`, wait for the client-agent to cache its
  skills, then "Start a new chat conversation to test it".
- **Network and project from settings:** the agent joins
  `<COMPOSE_PROJECT_NAME>_agent-network` of the running platform. The tool
  generates the agent's network file instead of the hardcoded
  `docker-compose.net_internal.yml`.
- **`config sync --agent <dir>`:** copy the keys an agent shares with the
  platform into its `.env`, without printing them, updating lines in place
  and keeping the agent's own lines. **One explicit list**, shared with
  `setup_agent.py` and the `agent-env-sync` check: `AGENT_SECRET`,
  `REDIS_PASSWORD`, `USER_IDENTITY_PUBLIC_KEY`, `USER_IDENTITY_ISS`,
  `USER_IDENTITY_AUD`, `LLM_CONFIG_PROFILE` (only with `--force` if the
  agent sets its own), `LLM_API_KEY`, `EMBEDDING_API_KEY`, `LOCAL_SDK`, and
  the DeepLynx client keys the template compose reads (`DEEPLYNX_BASE_URL`,
  `_KEY`, `_SECRET`, `_JWT_TOKEN`, `_ORG_ID`, `_PROJECT_ID`,
  `_DATA_SOURCE_ID`). Never `USER_IDENTITY_PRIVATE_KEY` or the local
  DeepLynx server's secrets. Before writing, it checks the agent's `.env` is
  git-ignored and not tracked, and refuses otherwise. It prints the platform
  path it used, and needs `--yes` when that came from the sibling fallback.
- **Version check:** `doctor --agent` compares the platform version the
  agent pins (its submodule commit) with the running platform's (the
  checkout its `root` label names), and the agent's
  `PROMETHEUS_API_BASE_IMAGE_HASH` with the SDK
  version the platform pins, and warns when they differ.
- **`config init --instance <name>`** (moved here from step 2): set
  `COMPOSE_PROJECT_NAME` and offset every host port, so two stacks run side
  by side. It's safe now that agent folders find the network by project.
- **The agent Makefile forwards** to the stub, keeping its target names
  (`up`, `up-fg`, `down`, `logs`).
- **`setup_agent.py`** uses `system/envfile.py`, the shared key list and the
  same precedence. `--submodule` adds `prometheus_core` as a submodule to a
  new agent repo, refuses a commit that isn't on a remote branch, and
  requires an output folder outside the checkout (default `../../<slug>`).
- **Template `.dockerignore`:** add `prometheus_core/` and `**/.env`, so a
  submodule isn't sent to the Docker builder on every build. Also exclude
  `prometheus_core/` from ruff and pytest in the template's `pyproject.toml`.
  `doctor --agent` flags an existing agent missing these.
- **Old agent folders:** `doctor --agent` recognises the old Makefile and
  prints a one-line migration (`setup_agent.py --upgrade-makefile`).
- **Agent label:** agents scaffolded before step 3b get the
  `io.prometheus.agent` label through `--upgrade-makefile` too. The docs'
  caveat for unlabelled agents (from 3c) goes away here.
- **The template's docs and `success_message.txt`** describe the submodule
  layout as the default for a new repo, and how to upgrade the platform
  version (bump the submodule, then `doctor --agent`).

## Output

- `up --agent`: the steps (platform found at `<path>` via submodule,
  pointer or sibling; the running platform if different; network joined;
  built; registered; discovery refreshed), then the agent's URL, its route
  key, and "start a new chat conversation".
- `doctor --agent`: where the platform was found, the running platform, and
  the version comparison.
- `config sync --agent`: which keys it copied (names only), and from where.

## Replaces

- The agent template's Makefile logic (`read_dotenv`, `validate-network`,
  `check-base-image`): the Makefile forwards to the stub.
- `docker-compose.net_internal.yml`'s hardcoded network name: generated.
- `setup_agent.py --env-only` and the hackathon `.env` copy one-liners:
  `config sync --agent`.
- The manual "then refresh discovery" step after `make up` in the agent
  folder.

## Docs and slides

- **User guide:** `agents.md` becomes the full "your own agent" page:
  starting it with `--agent`, the three ways the tool finds the platform,
  `config sync`, version mismatches, upgrading. `setup.md` gets
  `--instance`.
- `agent-template/README.md`, `TUTORIAL.md`,
  `agent_template/README.md`, `success_message.txt`: the agent commands, the
  submodule layout, `config sync`.
- Hackathon: the knowledge base (`run-and-register.md`, `environment.md`,
  `checks.md` `agent-*` checks, `create-agent` skill and its
  `allowed-tools`) and decks 04 and 05: the agent commands, and
  `config sync --agent` instead of `setup_agent.py --env-only` and the copy
  one-liners. Rebuild the decks in a separate last commit.

## Breaking changes

- **C11:** agent folders use platformctl; their `make` targets keep working.
- An agent folder with a non-default platform `COMPOSE_PROJECT_NAME` now
  joins the right network (today it fails). Not breaking, but a change.
- `up` run inside an agent folder acts on the platform, as today, and says
  so; `--agent` is needed for the agent.
- Existing agent repos keep working with the sibling layout. The submodule
  is opt-in.

## Tests

- **Unit:** platform discovery for each layout and their order, the empty
  submodule; running platform vs found checkout; network name from
  `COMPOSE_PROJECT_NAME`; `config sync` copying exactly the list, keeping
  the agent's lines, refusing an untracked-ignored check failure; the
  version comparison; the stub; the secrets canary.
- **Live:** an agent folder in a separate `tmp_path` git repo with a
  submodule pointing at this checkout: `up --agent`, registration, refresh,
  `down --agent`; the same with `PROMETHEUS_CORE` and as a sibling; a
  platform started with `--instance` and an agent joining it.

## CI

- `agent-template: compose` and `agent-template: platform` switch to the
  new agent commands and `config sync`.
- A leg with a non-default `COMPOSE_PROJECT_NAME` (`config init
  --instance`), with an agent joining it end to end.

## Prepared for in steps 1 to 4

`system/envfile.py`, `config.py`, the `Paths` object (platform root and agent
folder kept separate), agent discovery and the agent checks don't depend on
the agent being inside the platform folder.

## Review

Before merging, run the reviewers in `reviews.md` for this step: all eight.
Record each finding in the PR as fixed, deferred or rejected.
