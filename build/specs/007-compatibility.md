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

Every compose target

- REQ-007-07: Every compose target in `platform/Makefile` MUST keep its name
  and help text and forward as the "Make targets" table in `commands.md`
  says. (planned: step 3a)
- REQ-007-08: `SERVICE`, `PROFILE`, `CHECK`, `UP_ARGS`, `WAIT_TIMEOUT`,
  `CHECK_TIMEOUT` and the documented settings MUST keep working as `make`
  variables, and the new `TAIL`, `FOLLOW`, `RESTART_AGENTS` and `AGENT` map
  to the matching options. (planned: step 3a)
- REQ-007-09: `make down-v`, `make clear-agent-registry` and
  `make clear-admin-users` MUST NOT prompt, as before. (planned: step 3a)
- REQ-007-10: `make ps` MUST exit 0 when the platform isn't running, though
  `./platformctl status` exits 3. (planned: step 3a)
- REQ-007-11: `make -C <platform> <target>` MUST work, and so MUST a shim
  that lost its executable bit or a checkout path with a space.
  (planned: step 3a)
- REQ-007-12: The containers, volumes, networks and images MUST be the same
  as the old Makefile's: the merged Compose config of the entry file equals
  that of the old `-f` list for every combination CI covers.
  (planned: step 3a)
- REQ-007-13: `make build-plain` MUST work. (planned: step 3a)

Running Compose yourself

- REQ-007-14: The tool MUST run `docker compose -f
  docker-compose.platform.yml`, and that same file MUST start the same
  platform when run by hand with `--profile dev`. (planned: step 3a)
- REQ-007-15: `docker-compose.yml` MUST set
  `name: ${COMPOSE_PROJECT_NAME:-prometheus_platform}`, so a hand-run
  `docker compose` in `platform/` can't create a second project.
  (planned: step 3a)
- REQ-007-16: `docker-compose.platform.yml` and `.platform.env` MUST be
  generated with a "generated; do not edit" header, have fixed names, and be
  git-ignored. (planned: step 3a)
- REQ-007-17: The tool MUST pin `COMPOSE_FILE` and `COMPOSE_PROFILES` in its
  child environment, so values in `.env` can't change what it runs.
  (planned: step 3a)
- REQ-007-18: When `.env` sets a key the tool derives, `up` MUST print a
  one-line note naming the key and saying a hand-run Compose will use it.
  (planned: step 3a)

Old behaviour that changes

- REQ-007-19: The Makefile-internal variables (`COMPOSE`, `COMPOSE_FILES`,
  `PROFILE_FLAGS`, ...) MUST no longer be read; each behaviour and breaking
  change is listed in `breaking-changes.md` (B3, B5, C1–C4, C6–C9, C15,
  C17). (planned: step 3a)

## Behavior

- BEH-007-01: GIVEN `make up LOCAL_SDK=true` WHEN it runs THEN it prints
  `make up -> ./platformctl up` and the local SDK is built. (planned: step 3a)
- BEH-007-02: GIVEN a stack started earlier with a plain `docker compose` in
  `platform/` WHEN the user runs `./platformctl up` THEN the old stack (project
  `platform`) is left as it is, and `docker compose -p platform down`
  removes it. (planned: step 3a)

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
