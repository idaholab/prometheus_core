# 001 - Using the CLI

status: draft
sources: platform/platformctl, platform/ctl/run.py, platform/ctl/platformctl/__main__.py, platform/ctl/platformctl/cli.py, platform/ctl/platformctl/output.py, platform/ctl/platformctl/jsonout.py, platform/plans/platformctl/design.md, platform/plans/platformctl/commands.md
tests: platform/ctl/tests, .github/workflows/platformctl.yml
depends-on: none

## Purpose
How a user starts `./platformctl` and how it talks back, for every command:
finding a usable Python, the global options, `--help` and `--version`, exit
codes, progress and summary output, errors that say what to do, the `--json`
contract, and running without a terminal. This spec owns the rules every
command shares, so the command specs don't repeat them.

## Requirements

## Behavior

## Interfaces
- `platform/platformctl` (the shim) and `PLATFORMCTL_PYTHON`
- Global options: `--set`, `--target`, `--dry-run`, `--verbose`, `--quiet`,
  `--json`, `--yes`, `--debug`, `--version`, `-h`/`--help`
- Exit codes 0, 1, 2, 3, 130
- The `--json` envelope: `schema_version`, `command`, `ok`, `platform`,
  `error{code, message, hint, check}`, and its error codes
- `--version --json` `commands` and `features`
- `NO_COLOR`, `TERM=dumb`

## Constraints
- Running the tool needs only Python 3.10 or newer; nothing is installed.
- Messages that docs, slides or CI quote stay word for word.

## Out of scope / Non-goals
- What each command prints in its own summary (the command's spec).
- Hiding secrets in output (003).
- How the package is organised internally (`platform/ctl/README.md`).

## Open questions
