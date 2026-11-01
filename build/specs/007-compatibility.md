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

The old scripts

- REQ-007-01: `scripts/init_env.py`, `scripts/check_platform.py` and
  `scripts/deeplynx_setup.py` MUST keep working, each printing one line
  naming the new command (such as "moved: run `./platformctl config init`")
  and then running it with the same arguments. (planned: step 2)

Make

- REQ-007-02: `make init-env`, `make check` and `make deeplynx-setup` MUST
  forward to `config init`, `status --wait` and `deeplynx setup`, keeping
  their names and help text. (planned: step 2)
- REQ-007-03: Each forwarded `make` target MUST print one line on stderr
  naming the command it runs, such as `make up -> ./platformctl up`.
  (planned: step 2)
- REQ-007-04: `make doctor` MUST run `doctor`, with `AGENT=<dir>` passed as
  `--agent`. (planned: step 2)
- REQ-007-05: `make test-system` MUST keep working, waiting for the platform
  with `status --wait`. (planned: step 2)

CI

- REQ-007-06: CI MUST set its stub DeepLynx credentials with
  `config set --from-env`, not by editing `.env` with `sed`.
  (planned: step 2)

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
