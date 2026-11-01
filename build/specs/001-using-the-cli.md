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

Starting the tool

- REQ-001-01: The shim MUST run the tool with the first usable Python 3.10 or
  newer, in this order: `PLATFORMCTL_PYTHON`, `python3.14` down to
  `python3.10`, Homebrew's `python3` on macOS, `python3`, then
  `uv run --no-project --python '>=3.10'`.
- REQ-001-02: When `PLATFORMCTL_PYTHON` is set but is not a usable Python
  3.10 or newer, the shim MUST exit 1 naming the variable, without trying the
  other candidates.
- REQ-001-03: When no usable Python and no `uv` is found, the shim MUST exit
  1 with a single suggestion: uv's one-line installer.
- REQ-001-04: Started with Python older than 3.10, the tool MUST exit 1 with
  a message naming the Python it needs and the one it got, never a
  `SyntaxError` or traceback.
- REQ-001-05: The tool MUST behave the same from any working folder, through
  a symlinked shim, and with `CDPATH` set, finding the platform from the
  shim's own location.
- REQ-001-06: A `.py` file in the working folder (such as `json.py`) MUST NOT
  replace a standard-library module, in the version probe or the tool.
- REQ-001-07: Run under `sudo` (`SUDO_USER` set), the tool MUST exit 1 and
  say that files would end up owned by root.
- REQ-001-08: The shim MUST pass its arguments to the tool unchanged, and
  MUST be a POSIX `sh` script that runs under `sh`, `dash`, `bash --posix`,
  BusyBox `ash` and macOS `/bin/sh`.

Options and help

- REQ-001-09: Every global option MUST work both before and after the
  command; a flag given in either position is on, and `--set` values from
  both positions are all kept.
- REQ-001-10: Arguments after the first `--` MUST go to the command
  untouched, never parsed as services or options.
- REQ-001-11: `--help` MUST list the commands under the headings "Run the
  platform", "Set up" and "Troubleshoot", most used first, and leave out a
  heading with no commands.
- REQ-001-12: Running `./platformctl` with no command MUST print the help
  and exit 0.
- REQ-001-13: A renamed command MUST keep working under its old name and
  print a one-line notice naming the new one.

Exit codes and errors

- REQ-001-14: The tool MUST exit 0 on success, 1 on failure, 2 on a usage
  error, 3 when the platform isn't running, and 130 when interrupted with
  Ctrl-C.
- REQ-001-15: An unexpected error MUST end with "Run again with --debug for
  details." and show a traceback only with `--debug`.
- REQ-001-16: A malformed `.env` MUST stop every command except `doctor`
  (which reports it) and `--version`, with an error naming the line.

`--version` and `--json`

- REQ-001-17: `--version` MUST print the tool's version and the platform's
  version; with `--json`, the object MUST also list `commands` and
  `features`.
- REQ-001-18: With `--json`, every exit path MUST print exactly one JSON
  object on stdout and nothing else, including usage errors and failures;
  progress and notices go to stderr.
- REQ-001-19: Every JSON object MUST have `schema_version`, `command`, `ok`
  and `platform{root, project, version}`; a failure MUST add
  `error{code, message, hint, check}`.
- REQ-001-20: `error.code` MUST be one of `usage`, `needs_terminal`,
  `not_running`, `docker_unavailable`, `port_in_use`, `running_elsewhere`,
  `timeout`, `config_invalid`, `check_failed`, `internal`. Codes are added,
  never renamed.
- REQ-001-21: Within a `schema_version`, fields MUST only be added; removing
  or changing one bumps the version. ⚠ untested

Output

- REQ-001-22: Output MUST have no colour or `\r` progress when stdout isn't
  a terminal, when `NO_COLOR` is set, or with `TERM=dumb`.
- REQ-001-23: `--quiet` MUST print only errors.
- REQ-001-24: A long command MUST print each step as `[n/N] title ... result`
  as it goes, marking a step that fails, and group the steps in CI logs.
- REQ-001-25: `up`, `restart` and `status` MUST end with a summary of what's
  running, where to reach it, and a "Next:" line. (planned: step 3a)
- REQ-001-26: Every failure MUST end with one line naming the likely fix
  and, where one exists, the `doctor` check to run. (planned: step 4)

Without a terminal

- REQ-001-27: A command that asks for confirmation MUST, without a terminal
  and without `--yes`, exit 2 with error code `needs_terminal`, naming the
  flag to pass. (planned: step 3a)

Documentation

- REQ-001-28: Every `./platformctl` command line in the Makefile, the user
  guide, the hackathon slides and skills, and the agent-template docs MUST
  parse with the real parser. (planned: step 2)

## Behavior

- BEH-001-01: GIVEN a Mac whose `python3` is 3.9 and `python3.12` is
  installed WHEN the user runs `./platformctl` THEN the tool runs with 3.12.
- BEH-001-02: GIVEN only uv is available WHEN the user runs `./platformctl`
  THEN the tool runs through `uv run`.
- BEH-001-03: GIVEN the shim has CRLF line endings WHEN it is run THEN it
  fails before Python starts.
- BEH-001-04: GIVEN `./platformctl --set A=1 doctor --set B=2` WHEN it is
  parsed THEN both settings are applied.
- BEH-001-05: GIVEN an unknown option WHEN the user passes `--json` THEN
  stdout is one object with `ok` false and `error.code` `usage`, and the exit
  code is 2.

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
- No test proves REQ-001-21. The golden files catch any change
  to the JSON, but can't tell an added field from a removed one; comparing
  against the previous schema version's goldens would.
