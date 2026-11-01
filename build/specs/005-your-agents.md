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

## Behavior

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
