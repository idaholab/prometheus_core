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

What is secret

- REQ-003-01: Every key read from `.env` or `--set` MUST be treated as
  secret unless the settings registry marks it safe to print; keys the
  registry doesn't know are secret.
- REQ-003-02: An environment value MUST be treated as secret when `.env`
  also sets its key or its name looks like a secret (contains `KEY`,
  `SECRET`, `TOKEN`, `PASS`, `CREDENTIAL`, `PRIVATE` or `AUTH`).
- REQ-003-03: Values shorter than 8 characters, `true`, `false` and plain
  numbers MUST NOT be scrubbed, so ordinary output stays readable.

Where secrets never appear

- REQ-003-04: A secret value MUST NOT appear in anything the tool prints:
  normal output, `--verbose`, `--dry-run`, `--json`, warnings, errors or a
  `--debug` traceback. It is replaced with `***`.
- REQ-003-05: A secret MUST also be hidden in its encoded forms: JSON-escaped,
  in `repr`, line by line for a multi-line value, and inside a longer string
  such as a URL; when one secret contains another, the longer is hidden
  whole.
- REQ-003-06: Output of Docker and Compose that the tool captures or passes
  on MUST be scrubbed before it is printed.
- REQ-003-07: A secret MUST NOT appear in a file the tool generates
  (`docker-compose.platform.yml`, `.platform.env`, `docker-compose.agents.yml`),
  and `.platform.env` MUST hold only keys the registry marks safe.
- REQ-003-08: An error about a `--set` argument MUST NOT echo text that
  isn't shaped like a setting name, since it may be a pasted secret.
- REQ-003-09: `doctor` MUST NOT change `.env`.

Refusals

- REQ-003-10: `--set` MUST refuse a key the registry doesn't mark safe, with
  "set <KEY> in .env instead", so a secret never lands in shell history or
  the process list.
- REQ-003-11: `compose --` MUST print "compose --: output is not redacted" on
  stderr before running, and MUST refuse `config` and `convert` unless
  `--no-interpolate` is given without `--environment`. (planned: step 3c)

Passing secrets on

- REQ-003-12: A secret MUST reach a child process only through its
  environment, never its argv; `exec` forwards environment variable names,
  not values.
- REQ-003-13: The agent registry clear MUST pass the Valkey password as
  `REDISCLI_AUTH`, never as `valkey-cli -a`. (planned: step 3a)
- REQ-003-14: `config init` MUST read keys without echoing them, and stop if
  the prompt would echo. (planned: step 2)
- REQ-003-15: The scrubber MUST also hide a secret's URL-encoded and base64
  forms, and the password inside a URL-shaped environment value such as
  `DOCKER_HOST=tcp://u:pw@h` or `HTTPS_PROXY`. (planned: step 2)
- REQ-003-16: The DeepLynx client MUST NOT print request headers or bodies,
  in any output mode. (planned: step 2)
- REQ-003-17: `LLM_CONFIG_PROFILE` and the other non-secret keys
  `.env.example` documents MUST be marked safe, so they print as
  themselves. (planned: step 2)

## Behavior

- BEH-003-01: GIVEN every secret has a unique sentinel (plain, quoted, with
  `$`, multi-line, in a URL) and a fake `docker` that prints them WHEN every
  command runs with `--verbose`, `--dry-run`, `--json`, `--debug` and forced
  failures THEN no sentinel appears in stdout, stderr or a generated file.
- BEH-003-02: GIVEN the scrubber is turned off WHEN the same commands run
  THEN the sentinels do show, so the canary can fail.
- BEH-003-03: GIVEN `--set LLM_API_KEY=...` WHEN it is parsed THEN it is
  refused and the value isn't printed.
- BEH-003-04: GIVEN distinct sentinels in `.env`, and `CI=1` WHEN `config
  init`, `config set`, `config show`, `status --wait` and `deeplynx setup`
  run with `--verbose`, `--json` and forced failures THEN no sentinel appears
  in stdout, stderr or `.env`'s other lines. (planned: step 2)
- BEH-003-05: GIVEN sentinels in a port, an image and a label of a minimal
  project WHEN `up --dry-run`, `build`, `status` and `doctor` run against
  real Compose THEN no sentinel appears in the captured output.
  (planned: step 3a)

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
