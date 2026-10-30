# platformctl: commands

The commands are grouped by what they act on. They don't mirror the Make
targets one to one: every current `make` target keeps working by forwarding
to one of them (see "Make targets" below).

## Summary

**Run the platform (the everyday commands)**
- `up [service...]`: build and start, wait, check, then restart your agents
  so they register again. With services, build and recreate only those
  (after a code change). Flags: `--no-build`, `--foreground`, `--no-check`,
  `--no-restart-agents`, `--frontend dev|prod|none`, `-- <compose args>`
- `down`: stop everything. `--volumes` also deletes all data (asks first),
  `--agents` also stops your agents
- `restart [service...]`: with no service, restart the platform without
  rebuilding (and restart your agents). With services, restart just those;
  it says "not rebuilt: use `up <service>` after a code change"
- `status`: what's running, URLs, agents, open chat turns, and a one-time
  health and registry check. `--wait [--timeout N]` waits until everything
  passes
- `logs [service...]`: follow the logs. `--tail N` or `--since 2m` prints
  and exits
- `build`: build the images. `--plain` gives verbose output, `--base-only`
  builds just `prometheus_api:local`

**Set up**
- `config init`: create or complete `.env`, ask for the LLM profile and
  key, ask whether to build the SDK locally and run DeepLynx locally (Enter
  accepts the recommended answer), and report keys missing from `.env`.
  `--local-sdk`/`--no-local-sdk` and `--local-deeplynx`/`--no-local-deeplynx`
  answer without asking. `--instance <name>` (step 7) sets up a second
  checkout
- `config set KEY=value`: write a setting into `.env`. `--from-env KEY`
  copies a secret from the environment
- `config show`: the resolved settings and where each came from, secrets
  shown only as `set`/`blank`
- `agents list`: the agents that would start, and why (in tree, debug,
  optional). `--registered` lists what the registry holds, and flags
  duplicate route keys and skill ids
- `agents refresh`: make the client-agent rediscover the agents
- `agents generate`, `agents clean`: write or delete the generated compose
  files
- `deeplynx setup`: start the local DeepLynx and save its key in `.env`

**Troubleshoot**
- `doctor`: diagnose common problems. `--tag`, `--agent <dir>`, `--list`
- `reset registry`: delete the agent registrations
- `reset users`: delete all users, so the setup wizard runs again
- `reset data`: delete the DB and Valkey volumes, after you type `clobber`
- `compose -- <args>`: run raw `docker compose` with the platform's settings.
  `--print` prints the command to run it yourself

**Global options** (before or after the command)
- `--set KEY=VALUE`, `--target compose|k3d`, `--dry-run`, `--verbose`,
  `--quiet`, `--json`, `--version`, `--yes`

**Later**
- `up`, `down`, `logs`, `doctor` with `--agent <dir>` for agent folders,
  including agents in other repositories, `config sync --agent <dir>` and
  `config init --instance` (step 7)
- `cluster up|down|reset` (step 8)
- `--set PLATFORM_SOURCE=image`: run the platform from pre-built images of
  the pinned version (step 9)

**Running Compose yourself:**
`docker compose -f docker-compose.platform.yml --profile dev up -d` (see
"The compose entry file" in `design.md`).

From least to most destructive: `reset registry` < `reset users` <
`reset data` < `down --volumes`, the order of the "reset ladder" in the
hackathon `troubleshooting.md`. The last two both ask you to type `clobber`.

## What the commands print

Every long command prints its steps as it goes and ends with a summary.
`up`, `restart` and `status` end with what's running, the folder it runs
from, the URLs (chat UI, backend API, and the client agent and DeepLynx
when they're up), the agents (yours marked), and what to do next. If a port
is taken, or the platform is already running from another folder, `up` says
what holds it and how to fix it, instead of Compose's "port is already
allocated". See `design.md`, "Output" and "Running elsewhere".

## `--help` order

Commands and options are listed in groups, the most used first (see "Help
layout" in `design.md`):

```
Run the platform:   up, down, restart, status, logs, build
Set up:             config, agents, deeplynx
Troubleshoot:       doctor, reset, compose
Global options:     --set, --target, --dry-run, --verbose, --quiet, --json, --version, --yes
```

## Global options

Accepted before or after the command (`./platformctl --set X=1 up` and
`./platformctl up --set X=1` both work).

| Option | What it does |
|---|---|
| `--set KEY=VALUE` (repeatable) | Overrides one setting, ahead of `.env` and the environment. Refuses keys marked secret: set those in `.env` |
| `--target compose\|k3d` | Chooses where the platform runs (also the `PLATFORM_TARGET` setting). Only `compose` works for now |
| `--dry-run` | Prints the commands it would run (argv only, scrubbed), without running them |
| `--verbose` | Prints the resolved settings, file lists and Docker commands (secrets scrubbed). On by default in CI |
| `--quiet` | Only errors; no steps or summary |
| `--json` | On `status`, `agents list`, `doctor`, `config show` and `--version`: versioned, machine-readable output (`design.md`, "JSON contract") |
| `--version` | The tool and platform version, and what this version supports |
| `--yes` | Answer yes to confirmations, for scripts and CI (`reset data` and `down --volumes` also need `--confirm clobber`) |
| `-h`, `--help` | Help for the tool, a group or a command |

Exit codes: 0 OK, 1 failure, 2 usage error (including "needs a terminal or
`--yes`"), 3 platform not running, 130 interrupted.

## Commands

| Command | What it does |
|---|---|
| `up` | `config init`, generate the compose files, check ports, `reset registry`, start DeepLynx if `LOCAL_DEEPLYNX`, build the base image if `LOCAL_SDK`, build and start detached, wait for healthchecks, `status --wait`, then restart your agents (warning first about open chat turns) |
| `up <service...>` | Build and recreate only those services, then wait for them. For "I changed the backend" |
| `up --no-build` | Start without building (and without the base image) |
| `up --foreground` | Start in the foreground; no wait or check. Prints your agents to restart |
| `up --no-check` | Return as soon as the containers have started |
| `up --no-restart-agents` | Only print your agents instead of restarting them |
| `up --frontend dev\|prod\|none` | Which React frontend to include (default `dev`; the `PROFILE` setting) |
| `up -- <args>` | Extra arguments for `docker compose up` |
| `up --no-generate` (hidden) | Keep the existing agents file; only for the `ng-*` Make targets |
| `down` | Stop all services. Your agents keep running, as today, and are named |
| `down --volumes` | Stop and delete all volumes, after you type `clobber` (`--yes --confirm clobber` for scripts) |
| `down --agents` | Also stop your agents, after confirming |
| `restart` | `up --no-build`. Takes `--foreground`, `--no-check`, `--no-restart-agents`, `--frontend`, `--if-idle`. Asks first when a chat is still answering (on a terminal; without one it only says so) |
| `restart <service...>` | Restart only those services, without rebuilding |
| `restart --if-idle` | Exit 1 instead of restarting when chat turns are open |
| `build` | Generate the compose files and build the images (the base image first if `LOCAL_SDK`) |
| `build --plain` | Same, with plain progress output |
| `build --base-only` | Build only `prometheus_api:local` from `../sdk` |
| `logs [service...]` | Follow the logs of all services, or the named ones |
| `logs --tail N`, `--since 2m`, `--no-follow` | Print and exit. Also exits without following when stdout isn't a terminal |
| `status` | What's running, the folder and version, URLs, agents (yours marked), open chat turns, then a one-time check: host ports answer, every agent is registered. Exit 3 when the platform isn't running |
| `status --wait [--timeout N]` | Repeat the check until it passes or the timeout (`CHECK_TIMEOUT`) passes |
| `config init` | Create `.env` from `.env.example` (mode 0600), generate blank secrets, ask for the LLM profile and key, report keys in `.env.example` that `.env` lacks. Output stays word for word. Without a terminal it asks nothing; it exits 1 only when the LLM profile or key is missing (as today), and the new questions keep their default (off) |
| `config init --local-sdk` / `--no-local-sdk` | Set `LOCAL_SDK=true` (build the `prometheus_api` base image on this laptop, no registry login) or `false`, without asking. Without either flag, asks when `.env` doesn't set it: "Build everything on this laptop (no INL login needed)? (recommended) [Y/n]". The answer is recommended from a quick test pull with a timeout |
| `config init --local-deeplynx` / `--no-local-deeplynx` | Set `LOCAL_DEEPLYNX=true` (run DeepLynx next to the platform and fill `DEEPLYNX_*` with `deeplynx setup`) or `false`, without asking. Asked when `.env` sets neither it nor `DEEPLYNX_KEY`, recommended yes |
| `config set KEY=value ...` | Write values into `.env`, in place (unlike the global `--set`, which overrides for one run). Refuses keys marked secret |
| `config set --from-env KEY ...` | Copy each key's value from the environment into `.env`, so a secret never appears in argv. Replaces CI's `sed` workarounds |
| `config show` | Each setting, its value (secrets as `set`/`blank`) and where it came from |
| `agents list` | Each agent, whether it's included, and why |
| `agents list --registered` | What the registry holds: route key, card URL, skill ids. Flags duplicate route keys and skill ids (two agents replacing each other). Never prints `AGENT_SECRET` |
| `agents refresh` | Make the client-agent rediscover the agents (its `/discovery/refresh`) |
| `agents generate` | Write `docker-compose.agents.yml`, `docker-compose.platform.yml` and `.platform.env` |
| `agents clean` | Delete them |
| `deeplynx setup` | Start the local DeepLynx (`LOCAL_DEEPLYNX=true`) and save a project and API key for it in `.env` |
| `reset registry` | Stop services, start Valkey, delete the agent registrations, and end with "Platform stopped. Run ./platformctl up" |
| `reset users` | Empty admin-db's users table; the setup wizard runs again |
| `reset data` | Stop services and delete the admin-db and Valkey volumes (users, keys, history), after you type `clobber` |
| `doctor [check-id...]` | Run every applicable check: PASS/WARN/FAIL/SKIP with evidence and a fix |
| `doctor --tag preflight\|diagnose` | Only the checks with that tag |
| `doctor --agent <dir>` | Also check an agent folder (automatic when run from inside one) |
| `doctor --list` | List the check ids, their tags and the targets they apply to |
| `compose -- <args>` | `docker compose` with the platform's project, files, profiles and environment, e.g. `./platformctl compose -- exec redis sh`. Its output isn't scrubbed: every run says so on stderr, and it refuses `config`/`convert` unless `--no-interpolate` is given without `--environment` |
| `compose --print` | Print the `docker compose` command to run it yourself (`-f docker-compose.platform.yml` and the profiles, never values) |

`config init` never changes a value `.env` already sets, unless a flag asks
for it. The `reset` commands, `down --volumes` and `restart` warn when chat
turns are still open.

## Make targets

Every current target stays, with its help text, and forwards. Command-line
variables (`make up LOCAL_SDK=true`) are passed as `--set`, so they still
beat `.env`. Each forwarded target prints the command it runs.

| Make | platformctl |
|---|---|
| `up`, `up-fg` | `up`, `up --foreground` |
| `restart`, `restart-fg` | `restart`, `restart --foreground` |
| `ng-up`, `ng-up-fg` | `up --no-generate`, plus `--foreground` |
| `ng-restart`, `ng-restart-fg` | `restart --no-generate`, plus `--foreground` |
| `down`, `down-v` | `down`, `down --volumes --yes --confirm clobber` (no prompt, as today) |
| `build`, `build-plain`, `base-image` | `build`, `build --plain`, `build --base-only` |
| `logs` | `logs` |
| `ps` | `status` |
| `check` | `status --wait` |
| `init-env` | `config init` |
| `generate`, `regenerate` | `agents generate` (it always rewrites the files) |
| `clean-generated` | `agents clean` |
| `deeplynx-setup` | `deeplynx setup` |
| `clear-agent-registry` | `reset registry --yes` |
| `clear-admin-users` | `reset users --yes` |
| `clobber` | `reset data` (still asks) |
| `check-prerequisites` | `doctor --tag preflight` |
| new: `doctor` | `doctor` (`AGENT=<dir>` for `--agent`) |

| Make variable | platformctl |
|---|---|
| `SERVICE=x` | `logs x` |
| `TAIL=N`, `FOLLOW=false` (new) | `logs --tail N`, `logs --no-follow` |
| `CHECK=false` | `--no-check` |
| `RESTART_AGENTS=false` (new) | `--no-restart-agents` |
| `PROFILE=dev\|prod\|` (empty) | `--frontend dev\|prod\|none`. Also accepted by `down`, `build`, `logs` and `status`, so they act on the same services |
| `UP_ARGS=...` | `up -- <args>` (now on every `up` and `restart` variant) |
| `WAIT_TIMEOUT`, `CHECK_TIMEOUT`, `LOCAL_SDK`, `DEBUG_AGENTS`, `OPTIONAL_AGENTS`, `LOCAL_DEEPLYNX`, `PROMETHEUS_SYSTEM_TESTING`, `USE_BUILD_CACHE`, `BUILD_CACHE*`, `PROMETHEUS_API_BASE_IMAGE_*`, `COMPOSE_PROJECT_NAME`, `DEEPLYNX_SERVER_PORT`, `*_PORT` | Settings: from `.env`, the environment or the command line (`--set`). Same names and defaults |

## Staying in the Makefile

`help`, `test-static`, `test-integration`, `test-infra`, `test-system`,
`check-markings`, `react-dev`, `react-build`, `react-check`, `cluster-up`,
`cluster-down`, `cluster-reset`.

`-include .env` stays only for `test-system`, which exports values from it.
