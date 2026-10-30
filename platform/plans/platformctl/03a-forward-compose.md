# 3a: The compose entry file; the Makefile forwards with the same behaviour

> **Status: Not started**

Lands after the hackathon. The first of three PRs for the compose targets, so
each can be reviewed and reverted on its own: 3a forwards with the same
behaviour, 3b adds the new run-time behaviour, 3c adds the new command
groups and switches the docs.

## Goal

Every Docker Compose target in `platform/Makefile` forwards to platformctl,
which runs the generated compose entry file. What runs is the same as
today; CI proves it.

## Work

- **The compose entry file:** every compose command runs
  `docker compose -f docker-compose.platform.yml`, written by the target's
  `generate()` (step 1's generator). Add
  `name: ${COMPOSE_PROJECT_NAME:-prometheus_platform}` to
  `docker-compose.yml`. Add `docker-compose.platform.yml` to
  `platform/.gitignore`. Reword the "The Makefile adds this file" comments
  and the `:?run make init-env` messages in the compose files. No other
  compose file changes; the agent compose files don't change.
- **Lifecycle actions:**
  - `up` (`--no-build`, `--foreground`, `--no-check`, `--frontend`,
    `-- <args>`, hidden `--no-generate`)
  - `down` (`--volumes`)
  - `restart` (the platform without rebuilding; hidden `--no-generate`)
    and `restart <service...>`
    (only those services, with "not rebuilt" in its output)
  - `build` (`--plain`, `--base-only`)
  - `logs [service...]` (`--tail N`, `--since`, `--no-follow`, `--follow`;
    no follow when stdout isn't a terminal unless `--follow`)
  - `status`: add the service states to step 2's check (`--json`, exit 3
    when not running)
  - `agents generate`, `agents clean`; `reset registry|users|data` with the
    behaviour of the Make targets they replace (the `agents` and `reset`
    groups grow in 3c)
- **Target method:** `clear_registry()` in `targets/compose.py`, through
  its `exec` (`design.md`, "Targets").
- **`build --base-only`** runs `make -C ../sdk build-local` with the
  variables it needs passed explicitly (`LOCAL_IMAGE`, `CACHE_FROM`).
  `runner.py` strips `MAKEFLAGS` and the other Make variables from its
  environment, so nothing else leaks in from an outer `make`.
- **Prerequisites:** every command that needs Docker runs the `preflight`
  checks first (today `down`, `logs`, `ps` and `test-integration` depend on
  `check-prerequisites` too); `SKIP_PREREQUISITES=1` skips them.
  `infrastructure/scripts/check-local-prereqs.sh` keeps only `--cluster`.
- **Makefile:**
  - Every current target name stays, with its `##@` help text, and forwards
    as in the "Make targets" table of `commands.md`.
  - Calls the shim as `sh $(CURDIR)/platformctl`, so `make -C` works and a
    lost executable bit doesn't matter.
  - Sets `PLATFORMCTL_VIA_MAKE=1` in each forwarding recipe. The tool reads
    Make's command-line variables from `MAKEFLAGS` and the environment
    (`design.md`, "Settings and precedence"), so `make up LOCAL_SDK=true`
    still beats `.env` and values with spaces or quotes arrive intact. The
    Makefile builds no `--set` arguments.
  - The tool maps `SERVICE=` to `logs` arguments, `TAIL=`/`FOLLOW=` to the
    new options, `AGENT=` to `doctor --agent`, from the same registry.
  - `down-v` passes `--yes --confirm clobber`, `clear-agent-registry` and
    `clear-admin-users` pass `--yes`: no new prompts for Make users or CI.
  - Each forwarded target prints the command it runs on stderr
    (`make up -> ./platformctl up`).
  - Removes the compose-file logic. `-include .env` stays only for
    `test-system`.
  - `test-*`, `check-markings`, `react-*`, `cluster-*` and `help` stay as
    they are.
- **Keep** `tests/infrastructure/test_compose_static.py:96` working: it
  parses the `test-system` recipe.

## Output

- `up` and `restart`: the numbered steps, and the summary at the end (what's
  running, the project and folder, the URLs for the chat UI, backend API,
  client agent and DeepLynx when they're up, the agents, and what to do
  next). See `design.md`, "Output".
- `down`: what it stopped and the volumes it kept (or removed).
- `status`: the same summary as `up`, plus unhealthy or exited services
  with their last log lines and the `doctor` check to run.
- `logs`: a header naming the services shown, unless `--quiet`.
- `reset ...`: what it's about to delete, then what it deleted.

## Replaces

- Every compose target in the Makefile: forwards to the tool, and the
  Makefile's compose-file logic is removed.
- `check-local-prereqs.sh --compose`: replaced by `doctor --tag preflight`
  (the `--cluster` mode stays until step 8).

## Docs and slides

- **User guide:** `everyday.md` (up, down, restart, logs, status, with the
  summary they print), `compose.md` (running Compose yourself, including
  that a hand-run Compose uses `.env` as it is); every `from-make.md` row
  for the targets that now forward.
- `platform/README.md`: "Running Compose yourself" (the command,
  `compose --print` arrives in 3c, what it skips); its command list points
  to the user guide.
- `platform/CLAUDE.md` and `platform/AGENTS.md`: the command block.
- **Not yet:** the hackathon material and agent-template docs (step 3c).

## What changes for you

- **Commands:** every `make` target works as before and prints the
  `./platformctl` command it runs. The docs show `./platformctl up`, `down`,
  `restart`, `logs`, `status`.
- **Files created:** `docker-compose.platform.yml` and `.platform.env` in
  `platform/` (generated, git-ignored).
- **First run:** the output is numbered steps and a summary with the URLs,
  instead of Compose's output. A stack you started with a plain
  `docker compose` in `platform/` (project `platform`) is left behind:
  `docker compose -p platform down`.
- **Roll back:** revert the PR. The two generated files are left behind and
  harmless.

## Breaking changes

- **B3:** Makefile-internal variables are no longer read.
- **C1:** a blank base-image pin falls back to the default (for the tool).
- **C2, C3, C4:** the entry file, the `name:` line (with the cleanup command
  for a stack started under the project `platform`), the generated files.
- **C6:** the new output (and the one-line command hint from Make).
- **C7, C8, C9:** `UP_ARGS` on every variant, `build-plain` fixed, the
  preflight checks through `doctor` on every Docker command.
- **C15:** quoted `.env` values lose their quotes.
- **B5:** `logs` stops following when piped (`--follow` keeps it).
- **C17:** `make ps` maps `status`'s exit 3 to 0.

## Tests

- **Unit:** actions against a fake `Target` (what they ask for); the exact
  Compose argv in table-driven golden tests of `targets/compose.py`; for
  each Make target, its `--dry-run` compared with the `make -n` fixtures
  step 2 recorded (a migration test: the fixtures are deleted once this
  step merges; `design.md`, "Tests"); the
  confirmation flags; Ctrl-C and exit codes; the Makefile forwarding: run
  the real `make -n` against a copy of the Makefile in `tmp_path` with
  values containing spaces, quotes and `$`, and parse what the tool would
  read; `MAKEFLAGS` never reaching a child; the secrets canary for every new
  command. On both the Ubuntu (Make 4.x) and macOS (Make 3.81) legs.
- **Live canary** (`design.md`, "Secrets"): sentinels in a port, an image
  and a label of the minimal project; `up --dry-run`, `build`, `status` and
  `doctor` against real Compose; no sentinel in the captured output.
- **Live:** `up`/`down`/`restart <service>`/`status`/`logs` (including
  `--tail` and `--no-follow`) on the minimal compose project; `reset
  registry` against real Valkey; Ctrl-C in the foreground (pseudo-terminal),
  with Compose and with a Python child, waiting for a ready marker rather
  than sleeping;
  Make forwarding of `make up X=y`, `X=y make up` and `make -C <dir>`.

## CI

- **Compose equivalence** (in the compose-validation job): with a test
  `.env` of fixed placeholders (`config set ...`), compare
  `docker compose -f docker-compose.platform.yml config --format json` with
  the old `-f` list's output, normalised for `name` and paths, for every
  combination the job covers plus `LOCAL_SDK` and `USE_BUILD_CACHE`, with
  both `--profile dev --profile prod`, as the job does today. Keep the job's
  "fail on any Compose warning" rule: `include:` can add warnings of its
  own. Keep the old file-list loop until step 3c merges, so a failure shows
  which side is wrong. Cap the matrix: every combination on `devel`, a
  representative subset on PRs.
- **Which jobs use what:** `platform: up` stays on `make` (the documented
  path; it covers every forward, including `ng-restart` and `down-v`).
  `platform: up deeplynx` switches to `./platformctl`, keeping every `.env`
  and key check. `agent-template: platform` follows `TUTORIAL.md`, which
  switches in 3c.
- The three "Collect logs" steps switch to `./platformctl logs --no-follow`
  and `status --json`, falling back to the old `COMPOSE_FILE` if `up` failed
  before writing the entry file. Failures also upload `doctor --json`.
- The platform jobs depend on `platformctl: unit`.

## Review

Before merging, run the reviewers in `reviews.md` for this step: all eight.
Record each finding in the PR as fixed, deferred or rejected.

## Done when

- Every Make target behaves as before (the `make -n` fixtures, compose
  equivalence).
- `docker compose -f docker-compose.platform.yml --profile dev up -d` starts
  the same stack as `make up` (without the setup steps it skips).
- CI's `platform: up` job (which runs `make up`, `restart`, `ng-restart`,
  `down`, `down-v` and the integration tests) and the compose-validation job
  pass.
