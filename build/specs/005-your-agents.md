# 005 - Your agents

status: draft
sources: platform/ctl/platformctl/compose_files.py, platform/ctl/platformctl/paths.py, agent-template/setup_agent.py, agent-template/agent_template/Makefile, agent-template/agent_template/docker-compose.yml, platform/plans/platformctl/design.md, platform/plans/platformctl/07-agent-folders.md
tests: platform/ctl/tests
depends-on: 002, 004

## Purpose
An agent a developer is working on stays registered and reachable through
every platform restart, whether it lives in this repository or in one of its
own. Covers restarting your agents after `up` and `restart`, the `agents`
commands, and (from step 7) acting on an agent folder: finding the platform
from it, `--agent`, syncing its `.env` and checking it pins the version that
is running.

## Requirements

Which containers are "your agents"

- REQ-005-01: Your agents MUST be exactly the running containers outside the
  platform's Compose project that carry the label `io.prometheus.agent=true`
  and are on the platform's network (or, for an external agent, found by the
  label alone); never a stopped container, one with another platform's
  `io.prometheus.platform.root`, or an unlabelled one. (planned: step 3b)
- REQ-005-02: The agent template's compose file MUST set the label
  `io.prometheus.agent: "true"`. (planned: step 3b)

Restarting them

- REQ-005-03: After `up` or `restart` is healthy, the tool MUST restart your
  agents, saying "Restarting your agent `<name>` (running outside the
  platform) so it registers again.", wait for each to register, then refresh
  the client agent's discovery. (planned: step 3b)
- REQ-005-04: An agent on the platform network without the label MUST be
  listed, not restarted, with `docker restart <name>` and the `labels:` lines
  to add to the compose file in its working folder. (planned: step 3b)
- REQ-005-05: When a restart fails, the tool MUST print the command to run in
  the agent's folder. (planned: step 3b)
- REQ-005-06: `--no-restart-agents` (Make: `RESTART_AGENTS=false`) and
  `--foreground` MUST only list your agents; with none found, the tool says
  "none on this Docker context (`<context>`)". (planned: step 3b)
- REQ-005-07: Before a restart that would end a chat that is still
  answering, the tool MUST ask on a terminal ("1 chat is still answering;
  restarting stops it. Continue? [y/N]"), and without one print that line
  and go on. (planned: step 3b)
- REQ-005-08: `restart --if-idle` MUST exit 1 instead of restarting when chat
  turns are open. (planned: step 3b)
- REQ-005-09: `down` MUST leave your agents running and name them;
  `down --agents` MUST stop them too, after confirming. (planned: step 3b)

Discovery

- REQ-005-10: `agents refresh` MUST make the client agent rediscover the
  agents at once, and report how many tools it now has and which are yours.
  (planned: step 3b)
- REQ-005-11: `agents list` MUST show each agent that would start, whether
  it is included, and why (in tree, debug, optional). (planned: step 3c)
- REQ-005-12: `agents list --registered` MUST show what the registry holds
  (route key, card URL, skill ids), mark which agents are yours, and flag
  duplicate route keys and skill ids, which make two agents replace each
  other; it MUST never print `AGENT_SECRET`. (planned: step 3c)
- REQ-005-13: `agents generate` MUST write the generated compose files, and
  `agents clean` MUST delete them. (planned: step 3a)

Agent folders (step 7)

- REQ-005-14: From an agent folder, the tool MUST find a `prometheus_core`
  checkout in this order: a `prometheus_core` git submodule of the agent's
  repository, `PROMETHEUS_CORE` in the agent's `.env` or the environment,
  then `../prometheus_core`. (planned: step 7)
- REQ-005-15: An uninitialised `prometheus_core` submodule MUST stop with
  "run `git submodule update --init`" instead of falling through to the next
  layout. (planned: step 7)
- REQ-005-16: Commands that act on the running platform (`up`, `down` and
  `logs` with `--agent`, `config sync`, the network to join) MUST use the
  platform that is running, found by its platform root label, and print both
  paths when it differs from the checkout found. A root label MUST only be
  trusted when that folder belongs to the current user and has a
  `platformctl`. (planned: step 7)
- REQ-005-17: `up --agent <dir>` MUST build and start the agent, wait for it
  to register, refresh discovery, wait for the client agent to cache its
  skills, then say "Start a new chat conversation to test it"; with no
  platform running it MUST stop with the command to start one.
  (planned: step 7)
- REQ-005-18: `down --agent <dir>` and `logs --agent <dir>` MUST act on that
  agent only. Through the platform's own shim, lifecycle commands act on an
  agent only with `--agent`. (planned: step 7)
- REQ-005-19: An agent MUST join the network of the running platform's
  `COMPOSE_PROJECT_NAME`, so a platform with a non-default project name
  works. (planned: step 7)
- REQ-005-20: The agent template MUST ship a `platformctl` stub that finds
  the checkout as REQ-005-14 says and passes `--agent <its own folder>` to
  `up`, `down`, `logs`, `doctor` and `config sync`; `--platform` acts on the
  platform instead. (planned: step 7)
- REQ-005-21: When the checkout the stub finds has a tool without agent
  folder support (no `agents.folder` in `--version --json` `features`), the
  stub MUST use the running platform's checkout instead and say why in one
  line. (planned: step 7)
- REQ-005-22: An agent folder's `make` targets (`up`, `up-fg`, `down`,
  `logs` with `SERVICE=`) MUST keep working, forwarding to the stub, plus the
  new `doctor` and `sync-env`. (planned: step 7)

Syncing an agent's `.env` (step 7)

- REQ-005-23: `config sync --agent <dir>` MUST copy into the agent's `.env`
  exactly the shared keys: `AGENT_SECRET`, `REDIS_PASSWORD`,
  `USER_IDENTITY_PUBLIC_KEY`, `USER_IDENTITY_ISS`, `USER_IDENTITY_AUD`,
  `LLM_API_KEY`, `EMBEDDING_API_KEY`, `LOCAL_SDK`, the platform's resolved
  `PROMETHEUS_API_BASE_IMAGE_HASH` (unless `LOCAL_SDK`), and the DeepLynx
  client keys; `LLM_CONFIG_PROFILE` only with `--force` if the agent sets
  its own, and `USER_IDENTITY_REQUIRED` only when the agent doesn't set it.
  (planned: step 7)
- REQ-005-24: `config sync` MUST NEVER copy `USER_IDENTITY_PRIVATE_KEY` or
  the local DeepLynx server's own secrets. (planned: step 7)
- REQ-005-25: `config sync` MUST update lines in place, keep the agent's own
  lines, print the names of the keys it copied (never values) and where it
  copied them from, and refuse an agent `.env` that git tracks or doesn't
  ignore. (planned: step 7)
- REQ-005-26: When it falls back to a checkout because no platform is
  running, or uses the sibling layout, `config sync` MUST print the path it
  used and need `--yes`. (planned: step 7)
- REQ-005-27: `setup_agent.py` and the `agent-env-sync` check MUST use the
  same key list as `config sync`. (planned: step 7)

Versions and a second platform (step 7)

- REQ-005-28: `doctor --agent` MUST warn when the platform version the agent
  pins (its submodule commit) differs from the running platform's, or the
  agent's base-image pin differs from the platform's. (planned: step 7)
- REQ-005-29: `config init --instance <name>` MUST set `COMPOSE_PROJECT_NAME`
  and move every host port, so a second platform runs next to the first,
  and an agent can join it. (planned: step 7)

Upgrading old agent folders (step 7)

- REQ-005-30: `setup_agent.py --upgrade-makefile` MUST replace an old agent
  Makefile with the forwarding one, add the stub, the `.dockerignore` lines
  and the agent label, and keep a `.bak`; it MUST refuse a Makefile that
  matches no known template version, showing the difference instead.
  (planned: step 7)
- REQ-005-31: `setup_agent.py --submodule` MUST add `prometheus_core` as a
  submodule, refuse a commit that isn't on a remote branch, and need an
  output folder outside the checkout. (planned: step 7)

## Behavior

- BEH-005-01: GIVEN an agent from another Compose project, labelled and on
  the platform network WHEN the user runs `./platformctl up` THEN the agent
  is restarted, registers again, and is in the client agent's discovery
  when `up` returns. (planned: step 3b)
- BEH-005-02: GIVEN an agent scaffolded before the label WHEN `up` finishes
  THEN it is still running, untouched, and the output says how to restart
  it and add the label. (planned: step 3b)
- BEH-005-03: GIVEN an agent repository with `prometheus_core` as a
  submodule while the platform runs from a sibling clone WHEN the user runs
  `./platformctl up` in the agent folder THEN the agent joins the running
  platform, and the output names both paths. (planned: step 7)
- BEH-005-04: GIVEN a teammate's fresh clone with no platform running WHEN
  they run `./platformctl config sync --yes` in the agent folder THEN the
  agent's `.env` gets the keys from the checkout found, which is printed.
  (planned: step 7)
- BEH-005-05: GIVEN a platform started with `config init --instance second`
  WHEN an agent runs `up --agent` against it THEN it joins
  `second_agent-network` and registers. (planned: step 7)

## Interfaces
- The container label `io.prometheus.agent=true`
- `--no-restart-agents`, `down --agents`, `restart --if-idle`
- `./platformctl agents list` (`--registered`), `agents refresh`,
  `agents generate`, `agents clean`
- `--agent <dir>` on `up`, `down` and `logs`
- `./platformctl config sync --agent <dir>`, `config init --instance <name>`
- `PROMETHEUS_CORE`, `PROMETHEUS_PLATFORM_PROJECT`
- The agent-template stub `agent_template/platformctl`

## Constraints
- Only running containers carrying the agent label are restarted; anything
  else is listed, never touched.
- `config sync` copies one explicit list of keys and never
  `USER_IDENTITY_PRIVATE_KEY`.

## Out of scope / Non-goals
- The agent-folder checks in `doctor` (006).
- How an agent's own code registers (`sdk/specs/008`).

## Open questions
