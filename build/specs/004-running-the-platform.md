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

## Behavior

- BEH-004-01: GIVEN two of three agents registered and 240 s left WHEN
  `status --wait` prints its progress THEN it reads like "backend ok,
  frontend ok, agents 2/3: waiting for synthesis-agent, 240 s left".
  (planned: step 2)

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
