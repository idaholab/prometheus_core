# 003 - Secrets

status: draft
sources: platform/ctl/platformctl/output.py, platform/ctl/platformctl/config.py, platform/ctl/platformctl/system/runner.py, platform/ctl/platformctl/cli.py, platform/plans/platformctl/design.md
tests: platform/ctl/tests, .github/workflows/platformctl.yml
depends-on: 002

## Purpose
platformctl never shows a secret value, by any route: not in its output,
`--verbose`, `--dry-run`, `--json`, errors or tracebacks, not in the output
of the Docker and Compose commands it passes on, not in a file it generates
or a label it sets, and not in a command line another user could see.

## Requirements

## Behavior

## Interfaces
- The settings registry's "safe to print" marking
- `--set` refusing secret keys
- `./platformctl compose -- ...` and its "output is not redacted" notice
- `config show` printing secrets as `set`/`blank`
- Secret prompts in `config init`

## Constraints
- Deny by default: a key the registry doesn't mark safe is secret.
- CI logs and artifacts are public, so `doctor --json` uploads are covered.

## Out of scope / Non-goals
- Permissions on agent `.env` files (005).
- `doctor`'s checks on `.env` mode and git-ignore (006).
- Output of `compose --`, `up --foreground` and following `logs`, which hold
  the terminal and can't be filtered; they are named, not scrubbed.

## Open questions
