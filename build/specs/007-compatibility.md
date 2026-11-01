# 007 - Compatibility

status: draft
sources: platform/Makefile, platform/docker-compose.yml, platform/ctl/platformctl/compose_files.py, platform/plans/platformctl/commands.md, platform/plans/platformctl/breaking-changes.md
tests: platform/ctl/tests, .github/workflows/platformctl.yml, .github/workflows/test.yml
depends-on: 002, 004

## Purpose
People and tools that use the platform the old way keep working: every
`make` target and variable, the old scripts until they are removed, CI, and
running `docker compose` by hand. Also covers the files the tool generates
and the output other material quotes.

## Requirements

## Behavior

## Interfaces
- Every current `platform/Makefile` target and documented variable
  (`SERVICE`, `PROFILE`, `CHECK`, `UP_ARGS`, `SKIP_PREREQUISITES`, ...)
- `platform/scripts/init_env.py`, `check_platform.py`, `deeplynx_setup.py`
  (forwarding stubs until step 3c)
- `./platformctl compose --print`, `./platformctl compose -- <args>`
- Generated files: `docker-compose.platform.yml`, `.platform.env`,
  `docker-compose.agents.yml`, `docker-compose.labels.yml`

## Constraints
- Each breaking change and behaviour change is listed, with its migration,
  in `platform/plans/platformctl/breaking-changes.md` (B1–B5, C1–C17).

## Out of scope / Non-goals
- What each command does once Make has forwarded to it (004).
- The Makefile targets that stay in Make (`test-*`, `react-*`,
  `check-markings`).

## Open questions
