# 002 - Settings and setup

status: draft
sources: platform/ctl/platformctl/config.py, platform/ctl/platformctl/system/envfile.py, platform/scripts/init_env.py, platform/scripts/deeplynx_setup.py, platform/.env.example, platform/plans/platformctl/design.md
tests: platform/ctl/tests
depends-on: 001

## Purpose
How the platform's settings are decided and how a user creates and changes
them, from a first `config init` to a one-run `--set`: the order in which
defaults, the environment, `.env` and the command line win, how `.env` is
read and written, and the setup commands that fill it in.

## Requirements

Precedence

- REQ-002-01: A setting MUST resolve, from lowest to highest, from its
  default, the environment, `.env`, `make` command-line variables, then
  `--set`.
- REQ-002-02: A blank `.env` line MUST win over the environment, except that
  a blank `PROMETHEUS_API_BASE_IMAGE_HASH` or `PROMETHEUS_API_BASE_IMAGE_REPO`
  falls back to the default.
- REQ-002-03: `LOCAL_SDK=true` MUST select the locally built base image
  instead of the pinned one.
- REQ-002-04: A variable given on the `make` command line MUST beat `.env`,
  including values with spaces and quotes, and MUST only be read when the
  tool runs through `make`; a shell variable (`X=y make up`) still loses to
  `.env`.
- REQ-002-05: A Make variable the settings registry doesn't know MUST NOT
  become a setting.
- REQ-002-06: A blank `COMPOSE_PROJECT_NAME` MUST fall back to
  `prometheus_platform`.
- REQ-002-07: A boolean setting MUST count only `true` as on, and a numeric
  setting that is blank or not a number MUST be a `config_invalid` error
  naming the setting.
- REQ-002-08: `PROFILE` MUST select the frontend: `dev` and `prod` are
  frontends, and any other value, including blank, means none.

Reading `.env`

- REQ-002-09: `.env` MUST be read with dotenv rules: quotes are stripped,
  `$` is not expanded, `export`, comments, a BOM and CRLF line endings are
  handled, and double-quoted values may span lines.
- REQ-002-10: A `.env` parse error MUST name the line number, never its
  text; a file that isn't UTF-8 or can't be read MUST be reported as an
  error, not a traceback.

Writing `.env`

- REQ-002-11: A new `.env` MUST be created with mode 0600 from the start, and
  a rewritten one MUST keep its mode.
- REQ-002-12: A write to `.env` MUST be atomic: either the whole new file or
  the old one is in place, and no temporary file is left behind, even when
  the write fails.
- REQ-002-13: Writing a symlinked `.env` MUST update the file the link points
  to, and keep the link.
- REQ-002-14: Updating keys MUST change their lines in place and append keys
  that are missing, keeping every other line; a value is quoted only when it
  needs to be, and reads back unchanged.

The `config` commands

- REQ-002-15: `config init` MUST create `.env` from `.env.example`, fill
  blank secrets, ask for the LLM profile and key, report keys in
  `.env.example` that `.env` lacks, and keep `init_env.py`'s messages word
  for word. (planned: step 2)
- REQ-002-16: `config init` MUST ask whether to build the SDK locally and run
  DeepLynx locally when `.env` doesn't say, with Enter accepting the
  recommended answer; `--local-sdk`, `--no-local-sdk`, `--local-deeplynx` and
  `--no-local-deeplynx` answer without asking. (planned: step 2)
- REQ-002-17: Without a terminal, `config init` MUST ask nothing, keep the
  default for the new questions, and exit 1 only when the LLM profile or key
  is missing. (planned: step 2)
- REQ-002-18: `config init` MUST NOT change a value `.env` already sets
  unless a flag asks for it, and MUST NOT copy an environment value into
  `.env` except the LLM profile and key it saves today. (planned: step 2)
- REQ-002-19: `config set KEY=value` MUST write the value into `.env` in
  place and refuse secret keys; `config set --from-env KEY` MUST copy the
  key's value from the environment, so a secret never appears in argv.
  (planned: step 2)
- REQ-002-20: `config show` MUST print every setting, its value (secrets as
  `set` or `blank`) and where it came from. (planned: step 2)
- REQ-002-21: `deeplynx setup` MUST start the local DeepLynx and save a
  project and API key for it in `.env`. (planned: step 2)
- REQ-002-22: A variable on the `make` command line that the registry
  doesn't know MUST be ignored with a one-line warning naming it.
  (planned: step 2)
- REQ-002-23: Updating a key MUST replace the whole of a quoted multi-line
  value, and for a key that appears twice MUST change the last occurrence,
  the one that is read. (planned: step 2)
- REQ-002-24: `config set --from-env` MUST exit 1 naming each key that isn't
  set in the environment, and write nothing. (planned: step 2)
- REQ-002-25: The local SDK question's recommendation MUST come from a test
  pull of the pinned base image with a short timeout, so it never hangs off
  the VPN. (planned: step 2)
- REQ-002-26: `config init`'s menus MUST work without `termios`, falling
  back to numbered choices. (planned: step 2)
- REQ-002-27: `config init` MUST end with "Next: ./platformctl up", or with
  local DeepLynx "Next: ./platformctl up, then ./platformctl deeplynx
  setup". (planned: step 2)
- REQ-002-28: A child process MUST get the same environment Make gave it:
  for a key in both the environment and `.env`, the `.env` value; the
  derived values added; every other `.env` key left for Compose to read
  itself. (planned: step 3a)

## Behavior

- BEH-002-01: GIVEN `LOCAL_SDK="true"` in `.env` WHEN the setting is read
  THEN it is on (Make read it as `"true"`, with the quotes, and treated it as
  off).
- BEH-002-02: GIVEN `make up BACKEND_PORT=7` and `BACKEND_PORT=2` in `.env`
  WHEN the tool runs through `make` THEN the port is 7, and
  `--set BACKEND_PORT=3` would beat both.
- BEH-002-03: GIVEN a `.env` with an unterminated quote WHEN any command
  reads it THEN the error names the line number and doesn't print the
  value.
- BEH-002-04: GIVEN macOS's Make 3.81, where a plain `make up
  BACKEND_PORT=7` puts no ` -- ` in `MAKEFLAGS`, WHEN the tool runs through
  `make` THEN the port is still 7. (planned: step 2)
- BEH-002-05: GIVEN no terminal and no `LOCAL_SDK` in `.env` WHEN `config
  init` runs THEN it asks nothing, leaves the setting off, and prints one
  line naming `--local-sdk`. (planned: step 2)

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
