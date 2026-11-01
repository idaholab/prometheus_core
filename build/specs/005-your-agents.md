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

## Behavior

- BEH-005-01: GIVEN an agent from another Compose project, labelled and on
  the platform network WHEN the user runs `./platformctl up` THEN the agent
  is restarted, registers again, and is in the client agent's discovery
  when `up` returns. (planned: step 3b)
- BEH-005-02: GIVEN an agent scaffolded before the label WHEN `up` finishes
  THEN it is still running, untouched, and the output says how to restart
  it and add the label. (planned: step 3b)

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
