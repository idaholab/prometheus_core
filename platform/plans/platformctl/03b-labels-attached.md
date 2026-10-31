# 3b: Labels, "already running elsewhere", port checks, restarting your agents

> **Status: Not started**

Lands after 3a. Adds new run-time behaviour, so it's a PR of its own and can
be reverted without touching 3a's forwarding or 3c's docs.

## Goal

`up` and `restart` say clearly when something is in the way, and your own
agents register again after a platform restart without you doing anything.

## Work

- **Platform labels** on every platform container (not the network):
  `io.prometheus.platform.root` and `.source`, no version (it would
  recreate every container on every commit), through a generated
  `docker-compose.labels.yml` that is the last entry in the entry file's
  `path`, from `.platform.env` (`design.md`, "Running elsewhere"). The base
  compose files don't change.
- **Before `up` and `restart` start anything:**
  - the platform already running from another folder (by label, or for
    stacks started before the labels, by
    `com.docker.compose.project.working_dir`; folders compared with
    `realpath`, case-insensitively on macOS): stop with where it runs, that
    checkout's version, and `./platformctl down` there;
  - every host port the stack will publish: free (`host.py`: IPv4 and IPv6,
    bind and connect; the platform's own ports count as free), or stop
    naming what holds it (another platform, another container, AirPlay on
    5000, a local Postgres or Redis, the process name) and the lasting fix
    (`design.md`, "Running elsewhere"; for 5000, AirPlay off, never a port
    change).
- **The agent label.** The agent template's compose file gets
  `labels: {io.prometheus.agent: "true"}` (`agent-template/agent_template/
  docker-compose.yml`).
- **Restarting your agents** (`design.md`, "Restarting your agents"): after
  `up`/`restart` is healthy, restart running containers on the platform
  network, outside the platform project, that carry the agent label, then
  wait for them to register and run `agents refresh`, so the client-agent
  offers them at once instead of after its 300 s refresh. Open chats are
  asked about first on a terminal, and only printed without one (moved here
  from step 4, since this is the step that restarts things). Agents without
  the label are listed with `docker restart <name>` and the `labels:`
  snippet to add, with the file path. A failed restart prints the command
  to run in the agent's folder. `--no-restart-agents` (Make:
  `RESTART_AGENTS=false`) and `--foreground` only print them.
- **`agents refresh`** (the client-agent's `/discovery/refresh`) arrives
  here rather than in 3c, since the restart needs it.
- **`down`** names your agents it leaves running; `down --agents` stops
  them after confirming.
- **`down --volumes`** asks for `clobber` like `reset data`
  (`--yes --confirm clobber` for scripts; `make down-v` passes it).
- **`restart --if-idle`** and `open_turns` in `status --json`.
- **`doctor` checks:** `ports-free` and the running-elsewhere check share
  this code.

## Output

- The "already running" and port messages (`design.md`, "Running
  elsewhere").
- `up`/`restart`: "Restarting your agent `<name>` (running outside the
  platform) so it registers again", or the list with `--no-restart-agents`.
- First `up` after this step: "Recreating containers to add platform labels;
  your data is kept."
- `status`: the folder and version, other running platforms, open chat
  turns.

## Replaces

- "Restart your agent after every platform restart": done by the tool for
  labelled agents. The docs keep the caveat for older, unlabelled agents.
- Compose's "port is already allocated" for every port the platform
  publishes.

## Docs and slides

- **User guide:** `troubleshooting.md` ("already running elsewhere", "port
  in use"); `agents.md` started: your agent registers again by itself, the
  agent label, `--no-restart-agents`.
- `agent-template/` README: the agent label, and that older agents can add
  it.
- **Not yet:** the hackathon material (step 3c).

## What changes for you

- **Commands:** none new to learn. `up` and `restart` now restart your
  labelled agents and refresh discovery; `down --volumes` (`make down-v`
  passes the flags) asks you to type `clobber`.
- **Files created:** `docker-compose.labels.yml` (generated, git-ignored).
- **First run:** the first `up` recreates every platform container to add
  the labels; your data is kept. An agent scaffolded earlier is listed with
  `docker restart <name>` and the label to add.
- **Roll back:** revert the PR. The next `up` recreates the containers
  again (data kept).

## Breaking changes

- **C5:** your agents are restarted after `up`/`restart` (labelled ones
  only).
- **C12:** the "already running" and port checks.
- **C13:** the platform labels; the first `up` recreates every container
  (data kept).
- **C14:** `down --volumes` asks first.

## Tests

- **Unit:** the running-elsewhere decisions (same folder, other folder,
  unlabelled stack, symlinked or differently-cased paths); port-holder
  naming from recorded output; which containers count as your agents
  (labelled, running, outside the project, not another platform's); the
  open-turn warning; a same-folder `restart` never trips the
  "elsewhere" stop or the port check; a port held on `::1` only, and on
  `127.0.0.1` only, is reported busy.
- **Live:** a labelled container from a second project is restarted by `up`
  and left running by `down`; an unlabelled one is listed, not touched; the
  network and containers survive a new commit (no recreate) while an agent
  is attached, and the agent registers again and is in the client-agent's
  discovery right after `up` returns; a second checkout of the minimal
  project is
  stopped with the right message; a port held by a plain socket is named.
- **Manual (PR checklist):** WSL with Docker Desktop integration and with
  Engine in the distro, including a Windows process holding a platform port
  (reported busy, with the `Get-NetTCPConnection` hint).

## Review

Before merging, run `/review-panel` on the PR (see `reviews.md`) with these reviewers: all eight.

Ask them to look at:

- **Technical:** the labels file last in the entry file's `path`; folders compared with `realpath`
  (case-insensitive on macOS); stacks started before the labels, found by `working_dir`; that
  "ours" means this checkout, not a project with the same name from another one.
- **CI and tests:** a port clash and a second checkout (with the same folder name) in a live test;
  the restart of your agents against a fake target; open chats asked about only on a terminal.
- **Security:** what `io.prometheus.platform.root` reveals; which containers the tool restarts or
  stops (only labelled ones; `down --agents` after confirming); text from other containers'
  labels printed with control characters.
- **Linux/WSL:** the port check with IPv4 and IPv6 and with `TIME_WAIT` sockets; a port held on
  the Windows side; rootless Docker showing `rootlesskit`; AirPlay on 5000 on macOS only.
- **User:** the "something is in the way" messages: what holds the port and the lasting fix.
- **Agent developer:** the whole edit loop with the agent label; agents without it, with the
  snippet to add; an agent in another repository.
- **Rollout:** `down --volumes` now asking for `clobber`; stacks that have no labels.
- **AI skills:** `restart --if-idle` and `open_turns`; prompts without a terminal.

## Done when

- A second `up` from another folder stops with where the first one runs.
- A labelled agent is back in `agents list --registered` after
  `./platformctl restart`, with no manual step, and the client-agent has
  cached its skills (the `discovery-refresh` check passes).
