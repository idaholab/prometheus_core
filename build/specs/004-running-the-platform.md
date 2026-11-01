# 004 - Running the platform

status: draft
sources: platform/ctl/platformctl/targets/compose.py, platform/ctl/platformctl/system/host.py, platform/scripts/check_platform.py, platform/Makefile, platform/plans/platformctl/commands.md, platform/plans/platformctl/design.md
tests: platform/ctl/tests, .github/workflows/platformctl.yml, .github/workflows/test.yml
depends-on: 001, 002, 003

## Purpose
The everyday loop: start the platform, see that it works, change something,
restart, stop, and recover when something goes wrong. Covers what each
lifecycle command does and prints, the reset ladder from least to most
destructive, and what happens when the platform is already running from
another folder or a port is taken.

## Requirements

Status and readiness

- REQ-004-01: `status --wait` MUST repeat the platform check until the
  backend and frontend answer on their host ports and every agent is
  registered, or until `--timeout` (default `CHECK_TIMEOUT`) passes, and
  exit 1 on a timeout. (planned: step 2)
- REQ-004-02: While it waits, `status --wait` MUST say what it's waiting for
  and how long is left; on a timeout it MUST name what is missing and the
  `doctor` check for it. (planned: step 2)
- REQ-004-03: The check MUST reach loopback URLs directly, ignoring
  `HTTP_PROXY` without `NO_PROXY`. (planned: step 2)
- REQ-004-04: `status` MUST show each service's state and health, the URLs
  of what started, and the agents, and exit 3 when the platform isn't
  running. (planned: step 3a)
- REQ-004-05: For an unhealthy or exited service, `status` MUST show its last
  log lines and the `doctor` check to run. (planned: step 3a)

Starting and stopping

- REQ-004-06: `up` MUST, in order, run `config init`, write the generated
  compose files, run the preflight checks, clear the agent registry, start
  DeepLynx when `LOCAL_DEEPLYNX` is on, build the base image when
  `LOCAL_SDK` is on, build and start the platform detached, wait for its
  healthchecks, and run `status --wait`. (planned: step 3a)
- REQ-004-07: `up --no-build` MUST start without building anything;
  `up --no-check` MUST return once the containers have started;
  `up --foreground` MUST give Compose the terminal and skip the wait.
  (planned: step 3a)
- REQ-004-08: `up --frontend dev|prod|none` MUST select the React frontend,
  defaulting to the `PROFILE` setting. (planned: step 3a)
- REQ-004-09: Arguments after `--` on every `up` and `restart` variant MUST
  reach `docker compose up` unchanged. (planned: step 3a)
- REQ-004-10: `down` MUST stop every platform service and keep the volumes;
  `down --volumes` MUST also delete them. (planned: step 3a)
- REQ-004-11: `restart` with no service MUST restart the platform without
  rebuilding; `restart <service...>` MUST restart only those and say they
  were not rebuilt. (planned: step 3a)
- REQ-004-31: `up <service...>` MUST build and recreate only the named
  services, then wait for them. (planned: step 3c)
- REQ-004-12: `build` MUST build the platform's images (the base image first
  when `LOCAL_SDK` is on); `--plain` gives plain progress output, and
  `--base-only` builds only `prometheus_api:local`. (planned: step 3a)
- REQ-004-13: `build --base-only` MUST pass the SDK build only the variables
  it needs, and no `make` variable from an outer `make` may reach it.
  (planned: step 3a)
- REQ-004-14: `down` MUST report what it stopped and which volumes it kept
  or removed. (planned: step 3a)

Logs

- REQ-004-15: `logs [service...]` MUST follow the logs of all or the named
  services on a terminal; `--tail N`, `--since` and `--no-follow` print and
  exit, and without a terminal on stdout it prints and exits unless
  `--follow` is given. (planned: step 3a)
- REQ-004-16: Ctrl-C during `up --foreground` or a following `logs` MUST
  reach Compose, and the tool MUST exit with Compose's exit code.
  (planned: step 3a)

The reset ladder

- REQ-004-17: `reset registry` MUST stop the services, start Valkey, delete
  only the agent registrations, print "Cleared N agent registration
  key(s).", and end with "Platform stopped. Run ./platformctl up".
  (planned: step 3a)
- REQ-004-18: `reset users` MUST empty the admin users table, so the setup
  wizard runs again. (planned: step 3a)
- REQ-004-19: `reset data` MUST delete the admin-db and Valkey volumes only
  after the user types `clobber`; `--yes --confirm clobber` does it without
  asking. (planned: step 3a)
- REQ-004-20: Each `reset` MUST say what it is about to delete before it
  deletes it, and what it deleted after. (planned: step 3a)

Running elsewhere and ports

- REQ-004-22: Every platform container MUST carry
  `io.prometheus.platform.root` (the platform folder) and
  `io.prometheus.platform.source`, and no label whose value changes with each
  commit; the network carries none. (planned: step 3b)
- REQ-004-23: When the platform is already running from another folder,
  `up` and `restart` MUST stop before starting anything, with "Prometheus is
  already running from `<folder>` (checkout at `<version>`). Stop it there
  with `./platformctl down`."; a stack started before the labels is found by
  its Compose working folder. (planned: step 3b)
- REQ-004-24: Folders MUST be compared by their real path, and
  case-insensitively on macOS, so a symlink or a different case isn't
  another folder. (planned: step 3b)
- REQ-004-25: Before starting, `up` and `restart` MUST check every host port
  the stack will publish, on IPv4 and IPv6, and stop on a busy one naming
  what holds it and the lasting fix, instead of Compose's "port is already
  allocated"; ports this checkout's own platform holds count as free.
  (planned: step 3b)
- REQ-004-26: For port 5000 held by AirPlay on macOS, the fix MUST be to
  turn off AirPlay Receiver, never a port change; for any other port it MUST
  be `./platformctl config set <X>_PORT=<free port>`. (planned: step 3b)
- REQ-004-27: The first `up` after the labels are added MUST say it is
  recreating the containers and that the data is kept. (planned: step 3b)
- REQ-004-28: `status` MUST show the platform's folder and version, and list
  other platforms running on this Docker context. (planned: step 3b)
- REQ-004-29: `down --volumes` MUST ask the user to type `clobber`, like
  `reset data`. (planned: step 3b)
- REQ-004-30: Names, projects and labels read from other containers MUST
  have their control characters removed before they are printed.
  (planned: step 3b)

Preflight

- REQ-004-21: Every command that needs Docker MUST run the `preflight`
  checks first, stopping only on the checks the old
  `check-local-prereqs.sh --compose` failed on; `SKIP_PREREQUISITES=1` skips
  them. (planned: step 3a)

## Behavior

- BEH-004-01: GIVEN two of three agents registered and 240 s left WHEN
  `status --wait` prints its progress THEN it reads like "backend ok,
  frontend ok, agents 2/3: waiting for synthesis-agent, 240 s left".
  (planned: step 2)
- BEH-004-02: GIVEN `./platformctl logs | grep error` WHEN it runs THEN it
  prints the logs and exits instead of following. (planned: step 3a)
- BEH-004-03: GIVEN `restart backend -- --force-recreate` WHEN it runs THEN
  `backend` is the only service and `--force-recreate` reaches Compose.
  (planned: step 3a)
- BEH-004-04: GIVEN the platform isn't running WHEN `status --json` runs
  THEN it prints one object with `error.code` `not_running` and exits 3.
  (planned: step 3a)
- BEH-004-05: GIVEN the platform running from this folder WHEN the user runs
  `restart` THEN neither the "running elsewhere" check nor the port check
  stops it. (planned: step 3b)
- BEH-004-06: GIVEN a process holding port 8600 on `::1` only WHEN `up` runs
  THEN it stops, naming the process. (planned: step 3b)
- BEH-004-07: GIVEN `down` has just run WHEN `up` checks the ports at once on
  Linux THEN sockets in `TIME_WAIT` don't count as busy. (planned: step 3b)
- BEH-004-08: GIVEN the platform is running WHEN the user runs `up backend`
  THEN only the backend is rebuilt and recreated. (planned: step 3c)

## Interfaces
- `./platformctl up [service...]` (`--no-build`, `--foreground`, `--no-check`,
  `--timeout`, `--frontend dev|prod|none`, `-- <compose args>`)
- `./platformctl down` (`--volumes`, `--confirm clobber`)
- `./platformctl restart [service...]` (`--if-idle`)
- `./platformctl build` (`--plain`, `--base-only`)
- `./platformctl logs [service...]` (`--tail`, `--since`, `--follow`,
  `--no-follow`)
- `./platformctl status` (`--wait`, `--timeout`)
- `./platformctl reset registry|users|data`
- Container labels `io.prometheus.platform.root`, `io.prometheus.platform.source`

## Constraints
- The containers, volumes, networks and images are the same as the old
  Makefile's.
- "Cleared N agent registration key(s)." and the `clobber` confirmation stay
  word for word.

## Out of scope / Non-goals
- Restarting your agents (005).
- Hints after a failed start (006).
- The `make` targets that forward here (007).

## Open questions
