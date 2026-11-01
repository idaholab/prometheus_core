# 002 - Settings and setup

status: draft
sources: platform/ctl/platformctl/config.py, platform/ctl/platformctl/system/envfile.py, platform/scripts/init_env.py, platform/scripts/deeplynx_setup.py, platform/.env.example, platform/plans/platformctl/design.md
tests: platform/ctl/tests, .github/workflows/platformctl.yml
depends-on: 001

## Purpose
How the platform's settings are decided and how a user creates and changes
them, from a first `config init` to a one-run `--set`: the order in which
defaults, the environment, `.env` and the command line win, how `.env` is
read and written, and the setup commands that fill it in.

## Requirements

## Behavior

## Interfaces
- `./platformctl config init` (`--local-sdk`, `--no-local-sdk`,
  `--local-deeplynx`, `--no-local-deeplynx`)
- `./platformctl config set KEY=value ...`, `config set --from-env KEY ...`
- `./platformctl config show`
- `./platformctl deeplynx setup`
- `--set KEY=VALUE`
- `platform/.env`, `platform/.env.example`
- The documented settings (`LOCAL_SDK`, `COMPOSE_PROJECT_NAME`, `*_PORT`,
  `WAIT_TIMEOUT`, `CHECK_TIMEOUT`, ...)

## Constraints
- `make <target> KEY=value` keeps beating `.env`, as before platformctl.
- `config init` never changes a value `.env` already sets unless a flag asks
  for it.

## Out of scope / Non-goals
- Which keys are secret and how they are hidden (003).
- `config sync` and `config init --instance` (005).

## Open questions
