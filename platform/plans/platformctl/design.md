# platformctl: design

## Goals

- `make` targets keep working and forward to the new utility.
- Modular: one file per top-level command, and an independent adapter for
  each external tool (Docker, Compose, `.env`, HTTP, ...).
- Unit tests with 100% coverage, plus opt-in live tests against the real
  tools.
- Diagnostics (`doctor`) for the platform and for a developer's agent folder,
  built from the common problems in the hackathon knowledge base
  (`hackathon/.claude/skills/how/references/checks.md` and
  `troubleshooting.md`).
- Extendable to run the platform on k3d later, without rewriting the
  commands.

## Location

```
platform/
  platformctl                  # the shim (POSIX sh, executable): ./platformctl up
  ctl/                         # the project
    pyproject.toml             # requires-python >=3.10; dev deps only
    README.md                  # how to add an action, check, adapter or target
    platformctl/               # the package: python3 -m platformctl
      __main__.py              # Python version check, then cli.main()
      cli.py                   # parser from the action registry, global options
      config.py                # PlatformConfig: settings and their precedence
      context.py               # Context: config + target + adapters, passed to actions
      output.py                # [OK]/[WARN]/[ERROR], command echo, secret redaction
      compose_files.py         # agent discovery, compose file list
      actions/                 # one module per top-level command
      system/                  # one adapter per external tool
      targets/                 # where the platform runs
      diagnostics/             # doctor framework and checks
    tests/
      unit/                    # mocked, 100% line and branch coverage
      live/                    # real tools, only with --live, never counted
  Makefile                     # forwards to $(CURDIR)/platformctl
  docker-compose.platform.yml  # generated, git-ignored: the compose entry file
  .platform.env                # generated, git-ignored: values the tool derives
  docs/docs/platformctl/       # the user guide on the docs site
```

Why `platform/ctl/`:

- The tool knows the platform's compose files, `agents/` discovery,
  `.env.example`, ports and services, so it belongs in `platform/`, not in the
  repo-root `infrastructure/` (shared with k3d) or `sdk/` (shipped to agent
  authors).
- It follows `backend/` and `tests/`: its own `pyproject.toml` and tests.
- `platform/platformctl` is the shim, so the project folder can't share that
  name.
- `scripts/` keeps the repo tools CI runs (`add_markings.py`,
  `check_image_pins.py`).

## Runtime

- **Standard library only**, so running the platform needs only Python. No
  `uv sync`, no PyYAML: compose data comes from
  `docker compose config --format json`.
- **Python 3.10 or newer.** CI runs the unit tests on 3.10 to 3.14.
- **The shim finds a usable Python.** On a Mac, `python3` is usually the
  built-in 3.9 even when uv has installed 3.12, because
  `uv python install` adds only `python3.12` (it replaces `python3` only with
  `--default`). Debian 11 and RHEL 9 also ship 3.9. The shim tries, in order:
  `$PLATFORMCTL_PYTHON`, `python3.14` down to `python3.10`, `python3`, then
  `uv run --no-project --python '>=3.10' python`. Each candidate is checked
  with a one-line version test. If none works, it prints one install command
  for the OS. On macOS it tries Homebrew's Python before `/usr/bin/python3`,
  which opens an install dialog without the Command Line Tools.
- **`__main__.py` parses on 3.9**: no 3.10+ syntax, and `cli` is imported
  only after the version check, so even a wrong interpreter gets a clear
  message instead of a `SyntaxError`.
- **The shim** then runs `exec "$python" -I "<platform>/ctl/run.py" "$@"`.
  `run.py` (a few lines, parses on 3.9) puts its own folder first on
  `sys.path` and runs `platformctl`. Not `python -m` with `PYTHONPATH`: that
  puts the current directory first on `sys.path`, so a `json.py` in the
  folder the user is in replaces the stdlib module (verified), and agent
  folders are full of `.py` files. `-I` also ignores `PYTHON*` variables and
  user site-packages, which suits a stdlib-only tool. (`-P` would do the
  first part, but only from 3.11.) All other logic is in Python, so the
  coverage covers it. The tool finds the platform folder from its own
  location, never from the current directory, so `make -C <platform> ...`
  works. The shim finds its folder with
  `CDPATH= cd -P -- "$(dirname -- "$0")" && pwd -P`, so a set `CDPATH` or a
  symlinked shim can't send it elsewhere. The Makefile calls it as
  `sh "$(CURDIR)/platformctl"`, so a lost executable bit or a space in the
  path doesn't matter.
- **The version probe** also imports `json` and `urllib.request`, since
  some minimal distro Pythons lack modules the tool needs.
- **Line endings:** `.gitattributes` (new in step 2) forces LF for
  `platform/platformctl`, `*.sh` and `*.py`, so a Windows-side checkout
  can't give the shim CRLF line endings (`/bin/sh^M: bad interpreter`).
- **Not under `sudo`:** the tool refuses to run as root via `sudo`
  (`SUDO_USER` set), since `.env` and the generated files would end up owned
  by root.

## Structure

### Actions (`actions/`)

The commands are grouped by what they act on (`commands.md`): lifecycle
commands (`up`, `down`, `restart`, `build`, `logs`, `status`), groups with
subcommands (`config`, `agents`, `deeplynx`, `reset`) and tools (`doctor`,
`compose`).

One module per top-level command, found automatically (`pkgutil`), so adding
a command means adding a file. A plain command exports:

```python
NAME = "up"
HELP = "Build and start the platform"
def add_arguments(parser: argparse.ArgumentParser) -> None: ...
def run(ctx: Context, args: argparse.Namespace) -> int: ...  # exit code
```

A group's module holds its subcommands instead of `add_arguments` and `run`:

```python
NAME = "reset"
HELP = "Delete platform state, from least to most destructive"
SUBCOMMANDS = [registry, users, data]  # each: NAME, HELP, add_arguments, run
```

When a group grows large, it becomes a package (`actions/reset/__init__.py`
plus `registry.py`, `users.py`, ...). The registry discovers both forms, so
that change needs no other edits.

```
actions/
  up.py  down.py  restart.py  build.py  logs.py  status.py
  config.py    # init, show, set
  agents.py    # list, generate, clean
  deeplynx.py  # setup
  reset.py     # registry, users, data
  doctor.py  compose.py
```

### Help layout

`./platformctl --help` lists the commands in groups, most used first, not in
alphabetical or discovery order. Each action module declares its section and
an order within it:

```python
SECTION = "lifecycle"   # one of the sections below
ORDER = 10              # lower is listed first
```

| Section | Commands, in order |
|---|---|
| Run the platform | `up`, `down`, `restart`, `status`, `logs`, `build` |
| Set up | `config`, `agents`, `deeplynx` |
| Troubleshoot | `doctor`, `reset`, `compose` |

The same applies inside a command: its options are grouped
(`parser.add_argument_group`), the common ones first. For `up`:

| Group | Options |
|---|---|
| Common | `[service...]`, `--no-build`, `--foreground`, `--frontend` |
| Waiting and checks | `--no-check`, `--timeout` |
| Agents | `--no-restart-agents`, `--agent` (step 7) |
| Advanced | `-- <compose args>`; hidden: `--no-generate` |

Global options (`--set`, `--target`, `--dry-run`, `--verbose`, `--quiet`,
`--json`, `--version`) are listed last.

**What argparse can and can't do here** (checked on 3.10, 3.13, 3.14):

- **Section headings for commands** need custom help. A second
  `add_subparsers` raises an error, and adding subcommands in
  `(SECTION, ORDER)` order only orders them. `cli.py` hides argparse's
  subcommand list (`metavar` plus `help=SUPPRESS`) and prints the sections
  itself in the epilog. A test pins the `--help` output, so a new command
  lands in the right place.
- **Global options after the command** (`up --set X=1`, as people will
  type): each subparser gets the global options through `parents=`, but
  with its own `dest` (`sub_set`, `sub_verbose`, ...). `cli.py` merges the
  two copies after parsing: repeatable options (`--set`) concatenate, flags
  OR. `default=SUPPRESS` alone isn't enough: `--set A=1 up --set B=2` then
  parses to `['B=2']` and `A=1` is lost (verified on 3.10 and 3.14). A test
  covers the mixed case.
- **`-- <args>`:** `nargs="*"` swallows what follows `--`
  (`restart backend -- --force-recreate` parses as two services). `cli.py`
  splits argv at the first `--` before parsing and hands the rest to the
  action.
- **Deprecated aliases:** `aliases=` works on every version; `deprecated=`
  is 3.13+ only, so the notice is the tool's own code (from `dest`).

### Calling actions from each other

Actions call each other as plain functions (`up` calls `agents.generate`,
`config.init`, `reset.registry` and `status.wait`). This replaces Make's
prerequisite chains. Actions never call `docker compose` directly; they go
through `ctx.target`.

### System adapters (`system/`)

| Module | Responsibility |
|---|---|
| `runner.py` | The only module that starts subprocesses: `run(argv, *, env, check, capture, interactive)`. Values go to children through the environment, never as `-e KEY=value` argv. In interactive mode the parent ignores SIGINT while it waits (Ctrl-C reaches the child), a negative return code maps to 128+n, and pure passthroughs (`compose --`, `logs` following) use `os.execvp`. Passes `exec -T` when stdin isn't a terminal |
| `docker.py` | `docker info` (context, OS, architecture, image store), `version`, `volume`, `pull`, `image inspect`, `ps` with published ports |
| `compose.py` | A compose project: `-f` entry file, profiles, `up`/`down`/`exec`/`ps`/`logs`/`config`/`restart` |
| `envfile.py` | Parse `.env` and `.env.example` (dotenv rules, stripping `\r` and a BOM); update keys in place. Writes are atomic: `mkstemp` in the same folder (0600 from the start), `fchmod` to the target's mode, write, `fsync`, then `os.replace`. New files are 0600. A symlinked `.env` is written through to its target, never replaced by a plain file. Parse errors name the line number, never its text |
| `http.py` | `urllib` polling helpers. Loopback URLs bypass any proxy (`ProxyHandler({})`), so `HTTP_PROXY` without `NO_PROXY` can't break health checks. Never prints request headers or bodies |
| `valkey.py` | The agent-registry clear, through the target's `exec` |
| `deeplynx.py` | The DeepLynx API client |
| `host.py` | Whether a port is free: try `socket.bind` (works on every OS), then name the holder from `docker ps` published ports and platform labels; `lsof`/`ss` only as optional extra detail ("held by an unknown process, maybe on the Windows side"). Also OS, WSL, and the checkout being on `/mnt/<drive>` |
| later: `k3d.py`, `kubectl.py` | For the k3d target |

The architecture for the build cache comes from the daemon
(`docker info` `Architecture`, with `aarch64` mapped to `arm64`), not from
`uname -m`, which says x86_64 under Rosetta.

Adapters take a `Runner` and don't import each other's internals. Unit tests
inject a `FakeRunner` that records each argv and returns canned output.

### Targets (`targets/`)

`targets/base.py` defines what actions need from a place the platform runs:

- `generate()`: write the generated files (for compose: the entry file,
  `.platform.env`, the agents file)
- `build_base()`: build the `prometheus_api` base image when needed
- `build(services, plain)`, `start(services, foreground, wait, extra_args)`,
  `stop(volumes)`
- `status()`, `logs(services, tail, follow, since)`
- `exec(service, argv, interactive)`
- `service_url(service)`: the host URL for checks
- `restart(services)`: restart only those services
- `volumes(names)`: for `reset data`
- `passthrough(args)`: for `compose -- ...`
- `your_agents()`: running agent containers outside the platform that use
  its network (see "Restarting your agents")

`targets/compose.py` is the only implementation for now. `PLATFORM_TARGET`
(a setting) or `--target` selects it; `k3d` exits with "not supported yet".
Containers are always found by compose service and labels, never by
container name (no compose file sets `container_name`).

**Capabilities.** A target declares what it supports, as a `frozenset`
(`passthrough`, `your_agents`, `foreground`, ...). An action that needs a
capability the target lacks fails with "`<command>` is not supported on
target `<name>`", so a new target implements only what it can.

### Agent discovery (`compose_files.py`)

Finds `agents/*/docker-compose.yml`, plus `agents/debug-agents/*` with
`DEBUG_AGENTS` and `agents/optional/*` with `OPTIONAL_AGENTS`. Returns agent
records (directory, card, compose file), not bare paths, so the k3d target
can attach its own manifests later. Builds the compose file list: base,
system-test, agents, DeepLynx, build cache, override.

### The compose entry file

Users who want to can run `docker compose` themselves, without the compose
files getting more complicated. The compose target's `generate()` writes two
generated, git-ignored files on every run:

```yaml
# docker-compose.platform.yml
# Generated by platformctl; do not edit. Rerun ./platformctl agents generate
# after changing LOCAL_SDK, the base-image pin or the agents.
name: prometheus_platform            # COMPOSE_PROJECT_NAME
include:
  - path: [docker-compose.yml, docker-compose.agents.yml,
           docker-compose.build-cache.yml, docker-compose.override.yml,
           docker-compose.labels.yml]     # labels: from step 3b, always last
    env_file: [.env, .platform.env]
```

- `path` is exactly the compose file list above (only the files that apply
  and exist). `docker-compose.agents.yml` stays, since CI and docs name it.
- `.platform.env` holds only derived, non-secret values: the base-image repo
  and pin (with `LOCAL_SDK` and the blank-pin fallback applied),
  `BUILD_CACHE`, `BUILD_CACHE_PLATFORM`, `USE_BUILD_CACHE` (turned off when
  the containerd image store is missing), and the platform label values
  (`root`, `source`; see "Running elsewhere"). Its header says "generated;
  settings go in .env". A
  unit test checks it never contains a key the registry marks secret.
  `docker-compose.platform.yml` is added to `platform/.gitignore`;
  `.platform.env` is already covered by `*.env`.
- **`.env` wins over `.platform.env`.** Retested with Compose 5.6: when
  `.env` sets a key, even to a blank value, Compose uses the `.env` value,
  whatever the `env_file` order. Compose always loads the project's `.env`.
  Only an exported shell variable beats it. `.platform.env` only fills keys
  that `.env` doesn't set. So:
  - **The tool** passes every derived value in its child environment, which
    beats `.env`. What the tool runs is always right.
  - **Running Compose yourself** uses your `.env` as it is. If `.env` sets a
    derived key (the base-image pin or repo, `BUILD_CACHE*`), a hand-run
    Compose uses that value instead of the derived one, e.g. with
    `LOCAL_SDK=true` plus an uncommented pin, or a blank pin line.
  - The compose files stay as they are. Instead, `doctor` warns, and `up`
    prints a one-line note, when `.env` sets a derived key, naming the key
    and saying a hand-run Compose will use it. The user guide's
    `compose.md` says the same.
- The tool itself runs `docker compose -f docker-compose.platform.yml`. It
  pins `COMPOSE_FILE` and `COMPOSE_PROFILES` in its child environment, so
  values in `.env` can't change what the tool runs.
- **Running Compose yourself:**
  `docker compose -f docker-compose.platform.yml --profile dev up -d`, or
  put `COMPOSE_FILE=docker-compose.platform.yml` and `COMPOSE_PROFILES=dev`
  in `.env` and run plain `docker compose`. `./platformctl compose --print`
  prints the exact command (only `-f` and `--profile`, never `KEY=value`).
  Done by hand, these are skipped: `config init`, `reset registry`,
  restarting your agents, `deeplynx setup`, `status --wait`.
- **Why not `compose.yaml`?** Compose would pick it up automatically, but
  with `docker-compose.yml` next to it, Compose warns about "multiple config
  files" on every run.
- `include: env_file` needs `.env` to exist, and Compose doesn't accept
  `required: false` there (verified). The tool always runs `config init`
  first; the generated header and `doctor` explain it for people running
  Compose by hand.
- `docker-compose.yml` gains one line,
  `name: ${COMPOSE_PROJECT_NAME:-prometheus_platform}`, so even
  `docker compose -f docker-compose.yml` can't silently create a second
  project with empty volumes. `COMPOSE_PROJECT_NAME` in `.env` overrides the
  entry file's `name:` (verified), so the generated `name:` is a fallback.
  The agent compose files don't change.
- With `--no-generate`, the entry file is still rewritten, but includes
  `docker-compose.agents.yml` only if it exists (today's `COMPOSE_FILES_NG`).
- `doctor` flags a `.platform.env` that's older than the settings it was
  derived from.

### Diagnostics (`diagnostics/`)

- A check has an id, tags (`preflight`, `diagnose`), the targets it applies
  to, the checks it depends on, and `run(ctx) -> Result(status, evidence,
  fix)`. Status is PASS, WARN, FAIL or SKIP.
- A failed dependency skips the checks that depend on it (no Docker: skip
  every container check).
- Checks report whether a value is set, never the value. Comparisons
  report `same`/`differs`/`quoted`, never a hash or the line. Evidence
  from logs is the matched error class and line number, not the line
  (agent code can log values). They never run `docker compose config` or
  `docker inspect` in a way that prints secrets.
- Each check declares its `fix_kind` (`safe`, `yes`, `you`), which the
  hackathon `diagnose` skill uses. `doctor` never applies fixes.
- Agent-folder checks are separate modules, so step 7 can reuse them.
- Check ids match the hackathon `checks.md` ids where one exists.

## Settings and precedence

Every Make variable becomes a setting with the same name and default.

**Order:** defaults < environment < `.env` < `--set`, the same as Make
today.

- **`make X=y` keeps beating `.env`.** The Makefile doesn't build argv from
  its variables: `--set '$(v)'` over `$(MAKEOVERRIDES)` splits a value at
  its spaces and is a shell syntax error on a `'` (verified with GNU Make
  3.81). Instead the forwarding recipes set `PLATFORMCTL_VIA_MAKE=1`, and
  the tool reads the names of Make's command-line variables from the
  `MAKEFLAGS` environment variable (the words after ` -- `, with `\ `
  unescaped) and their values from its own environment, where Make exports
  them (verified: `make t "X=a b 'q'"` gives `MAKEFLAGS=... -- X=a\ b\ 'q'`
  and `X=a b 'q'` in the recipe). `X=env make t` isn't in `MAKEFLAGS`, so a
  shell variable (`X=y make up`) still loses to `.env`, as today. The
  registry alone decides what each name is: a setting (it beats `.env`, like
  `--set`), a Make variable mapped to an option (`SERVICE`, `TAIL`,
  `FOLLOW`, `AGENT`), or unknown (ignored, with a one-line warning naming
  it). A secret key given this way is accepted, as today: it's already on
  the user's command line, and the value never passes through argv. `doctor`
  warns, by key name only, when `.env` hides a value from the environment.
- **`--set` refuses keys the registry marks secret** (they'd land in shell
  history and `ps`): "set `LLM_API_KEY` in .env instead".
- **Child processes don't inherit Make's variables.** `runner.py` drops
  `MAKEFLAGS`, `MFLAGS`, `MAKELEVEL` and `MAKEOVERRIDES` from every child's
  environment, so `make -C ../sdk` (from `build --base-only`) gets only the
  variables the tool passes it.
- **A blank `.env` line wins** over the environment, as with Make today. The
  one exception: a blank `PROMETHEUS_API_BASE_IMAGE_HASH` or
  `PROMETHEUS_API_BASE_IMAGE_REPO` falls back to the default (it currently
  breaks the build with "invalid reference format"). For a hand-run Compose
  the blank line still wins (see "The compose entry file").
- **`.env` is parsed with dotenv rules**: quotes are stripped and `$` is not
  expanded, so `LOCAL_SDK="true"` means true. (Make reads it as `"true"`,
  with the quotes, and treats it as false.)
- **The environment of child processes matches Make's.** For keys set in
  both the environment and `.env`, the `.env` value is passed. The derived
  values (`COMPOSE_PROJECT_NAME`, `PROMETHEUS_API_BASE_IMAGE_*`,
  `BUILD_CACHE`, `BUILD_CACHE_PLATFORM`) are added. Every other `.env` key is
  left for Compose to read itself, so Compose's own interpolation is
  unchanged.
- Each setting declares what a blank value means: kept blank (`PROFILE=`
  means no frontend), or the default (the base-image pin).
- Values from the environment are never copied into `.env` implicitly,
  with the two exceptions `init_env.py` has today and `config init` keeps
  word for word: `LLM_CONFIG_PROFILE` and the LLM key, when `.env` lacks
  them ("Saved ... from the environment in .env."). `config set --from-env`
  copies only the keys it's given.

**One registry of settings.** Each setting is one entry: name, default,
type, what a blank means, whether it's safe to print, and a one-line
description. `config show`, `--set` validation and the settings table in the
docs all come from it, so adding a setting is one entry.

Settings: `COMPOSE_PROJECT_NAME`, `LOCAL_SDK`, `PROMETHEUS_API_BASE_IMAGE_REPO`,
`PROMETHEUS_API_BASE_IMAGE_HASH`, `DEBUG_AGENTS`, `OPTIONAL_AGENTS`,
`LOCAL_DEEPLYNX`, `DEEPLYNX_SERVER_PORT`, `DEEPLYNX_UI_PORT`,
`PROMETHEUS_SYSTEM_TESTING`, `PROMETHEUS_SYSTEM_TEST_URL`,
`CLIENT_AGENT_PORT`, `PROFILE` (`--frontend`), `UP_ARGS`, `CHECK`,
`RESTART_AGENTS`, `WAIT_TIMEOUT`, `CHECK_TIMEOUT`, `BACKEND_PORT`,
`FRONTEND_DEV_PORT`, `FRONTEND_PROD_PORT`, `REDIS_LOCAL_PORT`,
`LITELLM_LOCAL_PORT`, `USE_BUILD_CACHE`, `BUILD_CACHE`,
`BUILD_CACHE_PLATFORM`, `SKIP_PREREQUISITES`, `PLATFORM_TARGET`,
`PLATFORM_SOURCE`.

## Secrets

The plan's rule is "never print a secret". This is how it's enforced:

- **Deny by default.** Every key read from `.env`, the environment or
  `--set` is secret unless the settings registry marks it safe to print
  (ports, profiles, flags, the base-image pin and repo, the project name).
  Keys the registry doesn't know, which Compose reads (`LLM_API_KEY`,
  `DEEPLYNX_SECRET`, `USER_IDENTITY_PRIVATE_KEY`, anything a user adds), are
  secret.
- **One scrubber.** `output.py` replaces the value of every secret key with
  `***` in everything the tool prints: steps, the command echo,
  `--verbose`, `--dry-run`, `--json`, errors and warnings. `config show`
  prints `set`/`blank` for secrets.
  - **Encoded forms too.** Each value is matched as-is and as it appears
    JSON-escaped, in `repr`, and line by line (a multi-line PEM key comes
    out of `config --format json` as `line1\nline2`, verified), and inside
    longer strings (`URL=https://u:${PW}@host` interpolates).
  - **Not short or trivial values.** Values under 8 characters, `true`,
    `false` and plain numbers aren't scrubbed: unknown keys count as secret
    (`USER_IDENTITY_REQUIRED=true`), and scrubbing every `true` and `1`
    would make the output useless. Keys `.env.example` documents as
    non-secret settings are marked safe in the registry.
- **Compose's output goes through the scrubber.** Compose's own errors print
  interpolated `.env` values: with a sentinel in a port, `up --dry-run`
  printed `invalid hostPort: notaport_canary...` (verified on Compose 5.6),
  and a bad image reference prints the whole value. So for `build`, `up`
  (detached) and `restart`, `runner.py` reads Compose's stdout and stderr
  through a pipe and passes each line through the scrubber before printing
  it. Only the true passthroughs keep the terminal: `up --foreground`,
  following `logs`, and `compose --`. Their output can carry what an agent
  logs, and `compose --` says so.
- **Errors and tracebacks.** A top-level handler sends every error message
  through the scrubber. Tracebacks only with `--debug`, also scrubbed.
  `--dry-run` prints argv only, never the child environment.
- **`compose --` can't be scrubbed** (Compose has the terminal), so it
  doesn't pretend to be safe. It refuses only what prints the settings
  directly: `config` and its alias `convert`, unless `--no-interpolate` is
  given without `--environment` (`config --environment` prints every
  value; the review found it prints none with `--no-interpolate`, but the
  combination isn't worth allowing). The refusal points to `config show`.
  Every run prints
  "compose --: output is not redacted" on stderr first, and its `--help`
  says the same. Other ways to print a value (`exec <svc> sh -c 'echo $X'`,
  `run`, `logs`) can't be told apart from normal use, so they're not
  refused; the hackathon rules and skills list `compose -- config` and
  `compose -- exec` among the commands an assistant never runs to read a
  value.
- **Files.** `.env` and agent `.env` files are created 0600 and written
  atomically. `doctor` warns when one is group- or world-readable, or when
  `.env` isn't git-ignored (or is tracked). On a WSL `/mnt/<drive>`
  checkout without the `metadata` mount option, `chmod` has no effect, so
  the mode check is skipped there (the `checkout-path` check already warns
  about that location).
- **Prompts.** `config init` reads keys with `getpass`. If `getpass` would
  echo (`GetPassWarning`), it stops instead.
- **Canary test** (step 1, extended in every step): give every secret key a
  unique sentinel value, run every command with `--verbose`, `--dry-run`,
  `--json`, `--debug` and forced failures, and assert no sentinel appears in
  stdout or stderr, in any generated file (`docker-compose.platform.yml`,
  `.platform.env`, the `doctor --json` CI uploads) or in a label value.
  - **Sentinels of every shape:** multi-line, quoted, containing `$`, and
    embedded in a URL.
  - **Child output too:** the `FakeRunner` returns canned Compose and Docker
    output (`config --format json`, errors on stderr) that contains the
    sentinels, so a path that echoes child output is caught.
  - **`config init` prompts** and the `--debug` traceback are covered.
  - **A live canary** (step 3a): sentinels in a port, an image and a label
    of the minimal project, then `up --dry-run`, `build`, `status` and
    `doctor` against real Compose, with the captured output grepped. CI
    logs and artifacts are public.
- **Exception arguments are scrubbed** as well as messages:
  `CalledProcessError` carries argv.
- **The registry clear** passes the Valkey password as `REDISCLI_AUTH` in
  `exec -e REDISCLI_AUTH` (taken from the tool's environment), never as
  `valkey-cli -a`, which puts it in the container's process list (the
  Makefile does that today, `Makefile:319`).

## Where the platform's code comes from

Today the platform is always built from this checkout: the backend, the
frontend and the client-agent from `platform/`, the agents FROM the
`prometheus_api` base image (pulled at the pinned hash, or built from
`../sdk` with `LOCAL_SDK=true`).

Later the platform can also run from pre-built images, picked to match the
version of `prometheus_core` an agent repo pins as a git submodule (see
"Agents in other repositories"). The design keeps room for that now:

- **A `PLATFORM_SOURCE` setting**, in the settings registry from step 1:
  `build` (the only value for now, today's behaviour) or, later, `image`.
  Like `PLATFORM_TARGET`, an unsupported value fails with "not supported
  yet".
- **One place decides how each service gets its image.** The compose target's
  `generate()` chooses per service: build it, or use an image. Today that's
  "build" for the platform's services and the base-image pin for the agents.
  `image` mode adds a generated `docker-compose.images.yml` to the entry
  file's `include`, setting `image:` and dropping `build:` for each service
  with a published image. The base compose files don't change, and nothing
  outside `generate()` needs to know.
- **The platform version is a value, not an assumption.** `config.py` exposes
  `platform_version()`: today the checkout's commit, formatted like the
  published tags (`<commit date>-<7 char sha>`, as `publish.yml` writes
  them). `image` mode resolves the image tags from it. `status`, `doctor`
  and `config show` print it.
- **Images to look for.** CI already publishes `prometheus_sdk-devel`,
  `prometheus_backend-devel` and `prometheus_frontend-devel` to
  `ghcr.io/idaholab/prometheus_core` per commit on `devel`. `image` mode needs
  the client-agent published too, and release images (without `-devel`)
  later. A `doctor` check reports whether the images for the current version
  exist (`docker manifest inspect`), before `up` tries to pull them.
- **Nothing reads the platform's source files at run time** except
  `platform/` itself: actions use the platform root found from the tool's own
  location (or from the submodule; see below), never paths relative to the
  current directory.

This becomes its own step once the images are published (step 9).

## Agents in other repositories

Agents also live in their own repositories: the hackathon teams' agents,
`agents/requirements_agent` and `agents/bim_agent` (git-ignored here because
they have their own repos), and repos scaffolded from `agent-template/`.
Today they find the platform only by convention:

- `setup_agent.py` reads `../platform/.env`, relative to the template in
  this checkout.
- The agent Makefile joins the network `prometheus_platform_agent-network`
  by its hardcoded name.
- The hackathon setup clones `prometheus_core` next to the team repo
  (`siblings` check).

The plan supports three layouts for finding a `prometheus_core` checkout
from an agent folder, in this order:

1. **Submodule** (the future default): the agent repo has `prometheus_core`
   as a git submodule (searched from `git rev-parse --show-toplevel`, so an
   agent in a subfolder of a team repo works), at the commit of the platform
   it works with.
2. **Pointer**: `PROMETHEUS_CORE=<path>` in the agent's `.env` or the
   environment, for a checkout anywhere else.
3. **Sibling**: `../prometheus_core`, the hackathon layout today.

An empty submodule folder (never initialized) stops with "run
`git submodule update --init`" instead of falling through to the next
layout.

**Two different questions, two answers.** The checkout found above gives
the tool and the version the agent expects. The platform the agent talks to
is the one **running**, found by its `io.prometheus.platform.root` label.
They often differ (a submodule pinned for the version while the stack runs
from a sibling clone). Commands that act on the running stack
(`up/down/logs --agent`, `config sync`, the network name) use the running
platform's folder and `.env`. Only the version check uses the found
checkout. When they differ, the tool prints both paths.

What this needs from the design, from step 1 on:

- **The platform root is a value.** The tool knows two paths: the platform
  it belongs to (its own location), and the agent folder it's acting on.
  Lifecycle commands act on an agent folder only with `--agent <dir>`; only
  `doctor` infers it from the current directory, because in-tree agents
  (`platform/agents/*`) also have an `agent_card.json`. Nothing assumes the
  agent is under `platform/agents/`.
- **The tool is stable to call from outside.** Agent repos call the shim,
  commands and `--json` output, so those follow the rules in "Extending and
  changing commands". An agent repo pinned to an older submodule runs that
  older tool, with the platform version it was written for.
- **The platform's identity comes from settings, not names.** The network
  name and project name come from `COMPOSE_PROJECT_NAME` in the platform's
  `.env`, never `prometheus_platform` hardcoded, so an agent finds a
  platform started with `config init --instance`.
- **Version mismatch is visible.** `doctor --agent` compares the platform
  version the agent pins (its submodule commit) with the running platform's
  (the checkout its `io.prometheus.platform.root` label names; see "Running
  elsewhere"), and warns when they differ.

Step 7 implements these. Step 9 adds running the pinned version from images.

## Restarting your agents

Agents register with the backend only when they start, and every `up` and
`restart` clears the registry. A developer's agent from another compose
project stays running and attached to the platform network through a
platform `down` and `up` (verified), but it never registers again. Today the
docs tell people to restart their agent by hand after every platform
restart.

- **Which containers.** Only running containers on the platform network,
  outside the platform project, **that carry the agent label**
  `io.prometheus.agent=true`. The agent template's compose file sets it
  (step 3b adds it to the template; agents scaffolded earlier are listed as
  "found on the network, not restarted: add the label or restart it
  yourself"). Never a stopped container, never one with another platform's
  `io.prometheus.platform.root`, never anything else (debuggers, DB clients,
  another user's containers).
- **What happens.** After the platform is up and healthy, `up` and `restart`
  restart them, and say so in plain words: "Restarting your agent
  `<name>` (running outside the platform) so it registers again." If chat
  turns are open, they're warned about first (a restart ends them). If the
  restart fails (e.g. "network not found"), the tool prints the command to
  run in the agent's folder, from its `com.docker.compose.project.working_dir`.
- `--no-restart-agents` (Make: `RESTART_AGENTS=false`) only prints them.
  With `--foreground`, the tool can't act once Compose has the terminal, so
  it prints them instead. If none are found, it says "none on this Docker
  context (`<ctx>`)".
- `down` leaves your agents running, as today, and names them.
  `down --agents` stops them too, after confirming.
- **`reset registry`** runs `down --remove-orphans` before clearing. Your
  agents aren't orphans (another project), so they keep running; a live test
  covers "network kept while an agent runs" and "agent registers again after
  the restart".

## Extending and changing commands

- **Aliases.** Every command and subcommand can declare `ALIASES`. A renamed
  command keeps its old name as a deprecated alias that still works and
  prints a one-line notice. Hidden flags (like `--no-generate`) don't show
  in `--help`.
- **Docs can't go stale.** A unit test extracts every `./platformctl ...`
  line from the Makefile, the user guide, the hackathon slides and skills,
  and the agent-template docs, and parses each with the real CLI parser. It
  also checks every check id the skills cite against `doctor --list`.
- **Machine-readable output** (see "JSON contract"). Text output can change
  freely, except for the messages pinned by tests.
- **Exit codes:** 0 OK, 1 failure, 2 usage error, 3 platform not running,
  130 interrupted. `doctor` exits 1 on any FAIL, 0 with only WARN.
- **`./platformctl --version [--json]`** prints the tool and platform
  version and the list of commands it supports, so a script or skill can
  check what a clone can do before using it.
- **Non-interactive use.** Every command can run without a terminal:
  - commands that ask (`reset ...`, `down --volumes`, `down --agents`) take
    `--yes` (and `reset data`/`down --volumes` take `--confirm clobber`);
    without a terminal and without the flag they exit 2 and say which flag;
  - `config init` without a terminal asks nothing, and exits 1 listing what
    it couldn't answer;
  - `logs` follows only on a terminal; `--tail N` or a non-terminal stdout
    prints and exits;
  - `restart --if-idle` exits 1 instead of restarting when chat turns are
    open.

### JSON contract

`--json` is on `status`, `agents list`, `doctor`, `config show` and
`--version`:

- stdout carries only JSON; progress, notices and deprecation warnings go
  to stderr.
- Every object has `schema_version` (1), `command`, `ok`, and
  `platform{root, project, version}`. On failure, `error{code, message,
  hint, check}`, with the same exit codes as above.
- Fields are only added within a version; removing or changing one bumps
  `schema_version`.
- `doctor` per check: `id`, `area`, `tags`, `status`, `evidence` (safe
  values only), `fix`, `fix_kind`, `skipped_because`; plus counts.
- `status`: services (state, health), URLs, agents (registered, yours),
  `open_turns`.
- Golden-file tests pin each command's JSON.
- **Stable check ids.** Docs and skills name check ids, so renames get
  aliases, as for commands.
- **Target capabilities** (see Targets) keep a new target from breaking the
  commands it can't support.
- **Generated files** (`docker-compose.agents.yml`,
  `docker-compose.platform.yml`, `.platform.env`, and from step 3b
  `docker-compose.labels.yml`) have fixed names, a
  "generated" header, and unit tests that pin their content.
- **Growing groups:** a group module can become a package with no other
  edits (see Actions).

## Tests

### Unit (`tests/unit/`)

- `pytest --cov=platformctl --cov-branch`. 100% line and branch coverage of
  the **combined** report across the Python versions in CI (each version
  uploads its data, one job combines and enforces `fail_under = 100`), so a
  branch only one version takes still counts.
- The only allowed `# pragma: no cover` is `if __name__ == "__main__":`. A
  unit test fails if any other appears.
- **Test at the right boundary.** Actions are tested against a fake
  `Target` that records what they asked for (`start(wait=True)`), not the
  exact Docker argv. The exact Compose argv is pinned once, in table-driven
  golden tests of `targets/compose.py`. This keeps action tests from
  restating the implementation.
- Everything external is mocked: `FakeRunner` for subprocesses, a stub HTTP
  server or patched `urllib`, `tmp_path` for files. `host.py` is tested
  against recorded `lsof`/`ss`/`docker info` output from macOS, Ubuntu and
  WSL.
- Messages that docs, slides or CI quote are pinned by tests. So is the
  `--json` output (golden files) and the `--help` layout.
- **Make equivalence, kept permanently.** For each Make target, the
  `--dry-run` command sequence is a golden file, so later refactors can't
  drift from what `make` used to do.
- The secrets canary test (see "Secrets").

### Live (`tests/live/`)

- Marked `live`. Skipped unless `pytest --live` is given (option registered
  in `conftest.py`). `--live` refuses to run with coverage active, and a test
  checks that.
- Each test builds a throwaway platform in `tmp_path`: a minimal
  `docker-compose.yml` (a `redis` service and a fake agent) using the image
  digests from the real `docker-compose.yml`, so nothing new needs pinning
  and `check_image_pins.py` passes.
- A random `COMPOSE_PROJECT_NAME` per test, so it can't touch a real stack.
  Teardown runs `down -v`.
- Interactive paths (`config init` menus, the `clobber` prompt, Ctrl-C) run
  in a pseudo-terminal (`pty.openpty()`), since CI has no terminal.

### CI

- **Repo plumbing (step 1):** `platform/ctl` is added to the `ruff` job's
  project list; `ctl/uv.lock` is committed, listed in
  `.github/dependabot.yml` (`test_dependabot.py` requires it), and the unit
  job uses `uv sync --frozen`.
- `platformctl: unit`: ruff, then unit tests on Python 3.10 to 3.14 on
  Ubuntu, plus one `macos-latest` leg; then the combined coverage check.
- `platformctl: shim`: the shim on Python 3.9 (setup-python) prints the
  version message and exits non-zero; with 3.9 as `python3` and 3.12 as
  `python3.12`, it finds 3.12.
- `platformctl: live`: the live tests on Ubuntu Docker Engine, twice: with
  and without the containerd image store (the build-cache fallback).
- The platform jobs (`platform: up` and the others that start the stack)
  depend on `platformctl: unit`, so a broken tool fails in seconds, not
  after a 15-minute build.
- In CI (`CI` or `GITHUB_ACTIONS` set), the tool turns `--verbose` on and
  wraps each step in `::group::`, so failure logs keep Compose's full output.
- On failure, the platform jobs upload `doctor --json` as an artifact.
- The existing `platform: up` and compose-validation jobs keep running as the
  real-stack check (see step 3a for which jobs stay on `make`).
- WSL can't run in CI: steps 1 and 3b PRs include a manual WSL checklist
  (Docker Desktop integration, Engine in the distro, a `/mnt/c` checkout).

## User guide (zensical site)

The user documentation lives on the docs site (`platform/docs/`, built with
zensical by `pages.yml` and checked by CI's docs job). The site has no
explicit `nav`, so pages appear from the folder layout. platformctl gets its
own section:

```
platform/docs/docs/platformctl/
  index.md          # Start here: what it is, the five commands you need
  everyday.md       # Run, stop, restart, logs, status
  setup.md          # config init, local SDK, local DeepLynx, a second checkout
  agents.md         # Your own agent: registration, refresh, (step 7) agent folders
  troubleshooting.md# doctor, reset, running elsewhere
  compose.md        # Running docker compose yourself
  from-make.md      # Old make command -> new command, and what it now does for you
```

Written for the person using the platform, not for contributors:

- **A workflow, not a list.** `index.md` gets someone from nothing to a
  running platform in a few commands. Each later page is a task ("restart
  after a change", "my agent isn't showing up"), with the commands for it.
  The complete option list stays in `--help`; pages link to it rather than
  copy it.
- **Short.** What to run and what you'll see. No internals (no adapters,
  targets, precedence tables beyond one line).
- **`from-make.md`** is one table: make command, new command, and one line
  on what it now does for you that make didn't (e.g. `make up` →
  `./platformctl up`: "also re-registers your agent and prints the URLs").
- Pages only describe commands that exist. Step 2 creates the section with
  `index.md` (`doctor`) and `from-make.md` (step 1 stays out of the docs for
  the hackathon freeze); each step adds its commands to the pages and rows
  to the table.
- `prometheus-platform.md`'s "Getting started" and "Common commands" link
  to the section instead of repeating it. `index.md` (site home) links to
  it.

## Documentation and slides

Each step updates every doc and hackathon slide its change touches, in the
same PR, and switches them **directly to the new commands** as soon as they
exist (`./platformctl up`, not `make up`). The Make targets keep working, but
the docs stop teaching them. The user guide above is updated in every step.

- **No mixed setup blocks.** A copy-paste block in the slides or the
  knowledge base never mixes `make` and `./platformctl`. The setup and
  everyday blocks in the hackathon material switch together in step 3c,
  when every command they use exists. Steps 2 and 3a update only the pages
  that cover their own commands.
- **The hackathon freeze.** Nothing participants use (slides, skills,
  knowledge base, `platform/Makefile`, the docs) changes from 2026-11-03
  until after Day 2. Steps that touch them wait.
- **Skills and clones can differ.** Participants run the skills against
  their own `prometheus_core` clone at any commit. Skills check
  `./platformctl --version --json` (or that `platformctl` exists) and use
  the old commands when it's missing or too old.
- **Skills' pre-approved commands.** The `allowed-tools` lists in the
  hackathon skills' `SKILL.md` files name exact commands. Each step that
  changes a command they list updates them, and they always `cd <platform>
  &&` (the working folder resets between calls).
- Hackathon deck HTML is rebuilt in a separate last commit of each PR, so a
  rebase over other slide work only needs `make build` again.

- Every step file has a **Docs and slides** section listing what it changes.
- Hackathon decks are edited in `hackathon/slides/slides/*.md`, then rebuilt
  with `make build` in `hackathon/slides`, and the regenerated HTML is
  committed (CI's slides job fails otherwise). Where a command gets simpler,
  the slide gets simpler too (e.g. no "restart your agent" callout once
  your agents restart themselves).
- The hackathon knowledge base (`hackathon/.claude/skills/`) is updated in
  the same PR, including its "Facts as of" lines.
- Before opening a PR, search for the old command in docs, slides, skills,
  CI and agent-template docs (`git grep -n '<old command>'`).

## Replace as you go

When a step adds a capability, it also replaces the old way of doing it in
the same PR, where that's possible: the Make target forwards to the new
command, the old script or one-liner is removed, and docs, slides, skills
and CI switch to it. Nothing is left in two versions "for later".

The exceptions are named in the step that adds the capability, with the
step that removes the old one:

| New | Old, kept until | Why |
|---|---|---|
| `doctor` preflight checks (1) | `check-local-prereqs.sh --compose` until step 3a | The start targets still run in Make until step 3a |
| `doctor` platform checks (1, 4) | The hackathon `checks.md` one-liners: replaced in step 4 | Only the checks `doctor` has can be replaced; `llm-call` and code greps stay manual |
| Commands in the hackathon material (2, 3a, 3b) | Slides and skills until step 3c | No mixed `make`/`./platformctl` blocks, and the hackathon freeze |
| Agent folders (7) | The agent template's Makefile logic: replaced in step 7 | Agent repos copy the template, so it moves in one step |
| `config init --instance` (7) | | Agent folders hardcode the network name until step 7 |
| k3d target (8) | `cluster-up.sh`, `check-local-prereqs.sh --cluster`: replaced in step 8 | |

## Output

Each command says what it's doing while it runs, and ends with what the
user needs next. This is new: today `make` prints its recipe lines and
Compose's own output.

- **Steps.** Long commands print each step as they start it, e.g. for `up`:

  ```
  [1/7] Checking prerequisites ............ ok
  [2/7] Checking .env ..................... ok
  [3/7] Generating compose files .......... 3 agents
  [4/7] Clearing the agent registry ....... cleared 4
  [5/7] Building images ................... (compose output)
  [6/7] Starting and waiting for health ... 9/9 healthy
  [7/7] Checking registration ............. 3/3 agents registered
  ```

  Compose's own output is shown for the slow parts (build, start) and
  hidden for the rest, unless `--verbose`. The commands it runs are printed
  with `--verbose` and `--dry-run`.
- **A summary at the end** of `up`, `restart` and `status`: what's running,
  where to reach it, and what to do next. For example:

  ```
  Prometheus is running (project prometheus_platform, from ~/projects/prometheus_core/platform)

    Chat UI      http://localhost:5150
    Backend API  http://localhost:8600   (docs: /docs)
    Client agent http://localhost:8001   (with PROMETHEUS_SYSTEM_TESTING=true)
    DeepLynx UI  http://localhost:3000   (with LOCAL_DEEPLYNX=true)

    Agents: form-filler-agent, synthesis-agent, hello-alex-agent (yours, restarted)

  Next: open the chat UI. Logs: ./platformctl logs <service>. Stop: ./platformctl down
  ```

  The URLs come from the resolved ports and frontend, and only list what
  actually started. On a first run (no admin user yet) the "Next" line is
  "open the chat UI and create the admin account".
- **Errors say what to do.** Every failure ends with one line on the likely
  fix and, where one exists, the `doctor` check to run. The first step of
  `up` says "Start Docker Desktop" (or the Linux equivalent) in plain words,
  not just FAIL.
- **Plain words.** Output says "your agent `<name>` (running outside the
  platform)", not "attached".
- **Quiet and machine use:** `--quiet` prints only errors; `--json` (where
  supported) prints the result as data. Without a terminal, or with
  `NO_COLOR` or `TERM=dumb`, no colours or `\r` progress, plain lines only.
- **Make prints the new command.** Each forwarded Make target prints one
  line on stderr naming the command it runs (`make up -> ./platformctl up`),
  so people learn the new commands without a deprecation scare.
- Messages that docs, slides or CI quote stay word for word (see
  "Compatibility notes"); new output goes around them, not instead of them.

Each step file lists the output its commands gain.

## Running elsewhere

Only one platform can use a given set of host ports. Today, starting it from
a second checkout fails with Compose's "Bind for 0.0.0.0:8600 failed: port
is already allocated", which doesn't say who holds the port. Starting it with
the same project name from a second folder silently reuses the first
folder's containers (verified).

- **Labels on containers, not the network.** Every platform container
  carries where it came from: `io.prometheus.platform.root` (the platform
  folder) and `io.prometheus.platform.source` (`build`, later `image`).
  Both rarely change.
  - **No version label.** A label is container config, so a value that
    changes every commit would make Compose recreate every container after
    each `git pull`, even on a plain `restart`, and `up backend` would also
    recreate its dependencies (the review verified this in a throwaway
    project). The version is read when needed from the checkout the `root`
    label names (`platform_version()` there), and shown as "the checkout's
    version"; for an `image` source (step 9), from the image tag.
  - **Not on the network** either: Compose recreates a network whose config
    changed, which would disconnect your agents.
  - **How they're applied.** YAML anchors don't cross files, and
    `docker-compose.agents.yml` only has `include:`, so the tool generates
    `docker-compose.labels.yml`: one `labels:` block per service (from
    `config --services --no-interpolate`), with the values from
    `.platform.env`. It's the last entry in the entry file's `path`, so it
    merges into every service, including DeepLynx, the system-test services
    and a user's override (verified: a labels file in `include` `path`
    merges into the service). The base compose files don't change. (Also
    verified: `docker ps --filter label=...` finds them from any folder.)
- **Stacks started before the labels** (by the old Makefile) have none. The
  check falls back to `com.docker.compose.project.working_dir` and treats
  "no label" as an older stack. The first `up` after step 3b recreates every
  platform container (their config changed) and keeps the volumes; it says
  so.
- **Comparing folders** uses `os.path.realpath`, case-insensitively on
  macOS, so `/private/var` vs `/var` or a different case isn't "another
  folder".
- **Before starting**, `up` and `restart` check, in this order:
  - Same project, same folder: normal.
  - Same project, another folder: stop, with "Prometheus is already running
    from `<folder>` (checkout at `<v>`). Stop it there with
    `./platformctl down`." The second-instance option comes last.
  - **Every host port the stack will publish** is free (`host.py`). If not,
    stop before Compose fails, naming what holds it: another platform
    (project, folder, version), a known case (AirPlay on 5000 on macOS, a
    local Postgres or Redis), or "another process". Then the exact fix
    (`./platformctl down` there, turn off AirPlay Receiver, or
    `--set DEEPLYNX_SERVER_PORT=5001`).
- **`status`** prints the folder and version in its summary, and lists other
  running platforms. **`doctor`'s `ports-free`** check is the same code.
- Step 7 uses the `root` label to find the running platform's checkout for
  the agent version check; step 9 uses the source label.

## Breaking changes

See [`breaking-changes.md`](breaking-changes.md). Each step's PR lists the
items it introduces under a **Breaking changes** heading.

## Compatibility notes

From a review of every tracked doc, slide, skill and workflow:

- Output quoted elsewhere stays word for word: `config init` (deck 03 shows
  `make init-env`'s output), the `clobber` confirmation word of
  `reset data`, "Cleared N agent registration key(s).".
- The Docker commands the tool runs are printed with `--verbose` and
  `--dry-run` (scrubbed), and always in CI.
- `up --foreground`, `logs`, `config init` and `reset data` need the
  terminal; Ctrl-C reaches Compose, and the exit code is Compose's.
- CI's three "Collect logs" steps build `COMPOSE_FILE` by hand; they switch
  to `./platformctl logs --no-follow`, falling back to the old list if `up`
  failed before writing the entry file.
- CI sets `SKIP_PREREQUISITES=1`, `BUILD_CACHE` and `BUILD_CACHE_PLATFORM` in
  the environment; they must keep working.
- CI `sed`s the `DEEPLYNX_*` stubs into `.env` after `make init-env` (three
  jobs), because a blank `.env` line wins. Step 2's
  `config set --from-env KEY ...` replaces that.
- The agent template reads `platform/.env` with its own parser
  (`agent_template/Makefile` `read_dotenv`, `setup_agent.py`), which doesn't
  strip quotes, and hardcodes the network `prometheus_platform_agent-network`.
  `doctor` flags quoted values and a non-default `COMPOSE_PROJECT_NAME` until
  step 7 unifies them.
- The build cache needs the containerd image store, which Docker Desktop
  has and Linux Docker Engine doesn't by default (CI turns it on with
  `.github/actions/containerd-image-store`). The tool reads the store from
  `docker info` and, without it, turns the cache off and says how to enable
  it.
- Docker problems on Linux and WSL are told apart: daemon down, no
  permission on the socket (not in the `docker` group), rootless
  `DOCKER_HOST`, the Docker context in use, and Docker Desktop vs an Engine
  inside WSL. Compose has a minimum version (`include` with `env_file`).
