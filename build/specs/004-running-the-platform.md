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

## Behavior

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
