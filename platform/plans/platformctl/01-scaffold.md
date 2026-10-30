# 1: Scaffold

> **Status: Not started**

## Goal

Add the shim, the package and its test setup, with the core pieces every
later step builds on, and a first `doctor`. No existing behaviour changes:
the change stays inside `platform/ctl/` and the `platform/platformctl` shim.
No Makefile, docs, slides, skills or repo-wide files change, and the new CI
jobs run only when those paths change and aren't required. This is the one
step that may land before the hackathon freeze (2026-11-03).

## Work

- **Shim** `platform/platformctl` (POSIX `sh`, executable, copyright
  marking). Finds a usable Python 3.10+: `$PLATFORMCTL_PYTHON`, `python3.14`
  down to `python3.10`, `python3` (Homebrew's before `/usr/bin` on macOS),
  then `uv run --no-project --python '>=3.10' python`. If none works, prints
  one install command for the OS. Then
  `exec "$python" -I "<platform>/ctl/run.py" "$@"`, so a `.py` file in the
  current folder can't shadow the stdlib (`design.md`, "Runtime").
- **Project** `platform/ctl/`: `pyproject.toml` (`requires-python >=3.10`,
  dev deps pytest, pytest-cov, ruff; branch coverage; the `live` marker),
  a committed `uv.lock`, `README.md`, `.gitignore`.
- **`ctl/README.md`** includes a section **"Changing platformctl? Update the
  docs too"**: a change to a command, an option or its output also updates
  the places that teach it. A short list of where it's referenced, kept
  current by each step:
  - the user guide: `platform/docs/docs/platformctl/` (and `from-make.md`
    for anything a Make target forwards to)
  - `platform/README.md`, `platform/CLAUDE.md`, `platform/AGENTS.md`, the
    root `README.md` and `CONTRIBUTING.md`
  - other docs-site pages (getting started, local DeepLynx, adding agents)
  - `agent-template/` docs and `success_message.txt`
  - the hackathon knowledge base and skills (`hackathon/.claude/skills/`,
    including the `allowed-tools` in each `SKILL.md`) and slides
    (`hackathon/slides/slides/*.md`, then `make build` there)
  - CI (`.github/workflows/test.yml`) and the `platform/Makefile` forwards
  - messages pinned by tests because docs or slides quote them

  Plus the search to run before a PR: `git grep -n '<command or option>'`,
  and the test that parses every documented `./platformctl` line.
- **Core:**
  - `__main__.py`: parses on Python 3.9 (no 3.10+ syntax); checks the
    version, then imports `cli` and runs it. Refuses to run under `sudo`.
  - `cli.py`: parser from the action registry (plain commands, groups,
    `ALIASES` with the tool's own deprecation notice, hidden flags); the
    sectioned `--help` (custom listing) and option groups, most used first;
    global options accepted before or after the command (`parents=` with a
    separate `dest` per position, merged in `cli.py`); argv split at the
    first `--`; `--version [--json]`;
    the exit codes (0, 1, 2, 3, 130); a top-level error handler that scrubs
    messages and shows tracebacks only with `--debug` (`design.md`, "Help
    layout", "Extending and changing commands").
  - `output.py`: steps (`[n/N] ... ok`), the end-of-command summary block,
    the one-line "what to do" after an error, `--quiet`, plain lines without
    a terminal or with `NO_COLOR`/`TERM=dumb`, `::group::` and verbose in
    CI, and **the secret scrubber** (`design.md`, "Output", "Secrets").
  - `jsonout.py`: the JSON contract (`schema_version`, `command`, `ok`,
    `platform`, `error`; JSON only on stdout).
  - `context.py`.
- **Settings:** `system/envfile.py` (dotenv parsing; atomic, mode-keeping
  writes; new files 0600; errors name the line number, not its text) and
  `config.py` (the one registry of settings with "safe to print" flags, deny
  by default; precedence; blank handling; `--set` refusing secret keys; the
  child-process environment). Include `PLATFORM_SOURCE` (only `build`) and
  `platform_version()` now, so step 9 adds a value instead of a concept.
- **Paths:** a `Paths` object with the platform root (from the tool's own
  location) and, separately, the agent folder being acted on. Nothing
  computes a path from the current directory or assumes an agent is under
  `platform/agents/` (`design.md`, "Agents in other repositories").
- **Adapters:** `system/runner.py` (interactive mode, SIGINT, 128+n,
  `execvp` passthrough, values by environment only), `system/docker.py`,
  `system/compose.py`, `system/host.py` (port check by `socket.bind`, holder
  from `docker ps`, `lsof`/`ss` optional; WSL and `/mnt/<drive>` detection;
  architecture from `docker info`), `system/http.py` (loopback bypasses the
  proxy).
- **Targets:** `targets/base.py` (with capabilities as a frozenset) and
  `targets/compose.py`. `k3d` exits with "not supported yet".
- **Discovery:** `compose_files.py` returning agent records and the compose
  file list, and the writer of the generated files (`design.md`, "The
  compose entry file"). Nothing runs it yet; step 3a switches the compose
  commands to it.
- **Diagnostics:** the framework (ids matching `checks.md`, tags, targets,
  dependencies, statuses, `fix_kind`) and the first checks:
  - `docker`: daemon down vs no socket permission vs rootless
    `DOCKER_HOST` vs the context in use, Docker Desktop vs Engine, Compose
    minimum version; each with its own fix
  - `build-cache-store`: the containerd image store (from `docker info`);
    without it, the build cache is turned off with the `daemon.json` fix
  - `platform-env`, `base-image-pin`, `ports-free`
  - `.env` hiding an environment value, `.env` setting a derived key (a
    hand-run Compose will use it), `.env` file mode and git-ignore
  - `checkout-path`: CRLF in the shim, a checkout on `/mnt/<drive>` (WSL)
- **Actions:** `doctor` (with `--json`, `--list`, `--tag`).
- **Not in this step** (moved to step 2, after the freeze): `make doctor`,
  `.gitattributes`, the user guide and `platform/README.md`.

## Tests

- **Unit:** `FakeRunner`; the precedence table (each pair of sources, blank
  values, the base-image fallback, quoted values, `--set` refusing secrets);
  the compose file list for every combination of `DEBUG_AGENTS`,
  `OPTIONAL_AGENTS`, `LOCAL_DEEPLYNX`, `PROMETHEUS_SYSTEM_TESTING`,
  `USE_BUILD_CACHE` and the override file; the content of the generated
  entry file and `.platform.env` for each (and that `.platform.env` never
  has a secret key); each check passing, failing and skipped, against
  recorded output from macOS, Ubuntu and WSL; aliases and hidden flags;
  global options in both positions, including mixed
  (`--set A=1 up --set B=2` keeps both); the `--` split; the `--help` layout;
  the JSON contract (golden files); the version check; the `# pragma: no
  cover` ban.
- **Secrets canary:** every secret key gets a unique sentinel value; every
  command runs with `--verbose`, `--dry-run`, `--json` and forced failures;
  no sentinel may appear in stdout or stderr. Extended in every later step.
- **Live:** the `--live` option and its refusal under coverage; the shim
  from another directory, including one that holds a `json.py` and an
  `argparse.py`; `doctor` against the real daemon.

## CI

- **Path filter:** the new jobs run only when `platform/ctl/**` or
  `platform/platformctl` changes, and aren't required checks until step 2.
- **Plumbing:** add `platform/ctl` to the `ruff` job's project list; list
  `platform/ctl` in `.github/dependabot.yml` (`test_dependabot.py` requires
  it for the committed `uv.lock`).
- New job `platformctl: unit`: `uv sync --frozen`, ruff check and format,
  then the unit tests on Python 3.10 to 3.14 on Ubuntu, plus one
  `macos-latest` leg; a final step combines the coverage data and enforces
  100% (lines and branches).
- New job `platformctl: shim`: on Python 3.9 the shim prints the version
  message and exits non-zero; with 3.9 as `python3` and 3.12 as
  `python3.12`, it finds 3.12.
- New job `platformctl: live` on Ubuntu Docker Engine, with and without the
  containerd image store.
- PR checklist: a manual WSL run (Docker Desktop integration, Engine in the
  distro, a `/mnt/c` checkout).

## Output

- `doctor`: one line per check (`PASS`/`WARN`/`FAIL`/`SKIP`, the check, the
  evidence), the fix under each FAIL and WARN, and a closing count
  ("2 problems: run the fixes above, then ./platformctl doctor again").
- `--help`: the sectioned layout. `--version`: tool and platform version.

## Replaces

- Nothing yet. `make check-prerequisites` keeps running the shell script
  until step 3a moves the start targets (`design.md`, "Replace as you go").

## Docs and slides

- `ctl/README.md`: what platformctl is, how to run it and its tests, how to
  add an action or a check, and the "Update the docs too" section (first
  version; step 5 completes it).
- **Nothing else.** The user guide and `platform/README.md` follow in step 2;
  the hackathon material is frozen for the event, and `doctor` reaches it in
  step 4.

## Breaking changes

- None: nothing outside `platform/ctl/` and the shim changes, and `make`
  doesn't call the tool until step 2. `./platformctl doctor` needs Python
  3.10+, found by the shim.

## Review

Before merging, run the reviewers in `reviews.md` for this step: technical, CI, security, Linux/WSL, AI skills.
Record each finding in the PR as fixed, deferred or rejected.

## Done when

- `./platformctl --help` and `./platformctl doctor` work from any directory,
  on a Mac whose `python3` is 3.9 but has uv or a `python3.1x`.
- Combined unit coverage is 100% (lines and branches).
- The secrets canary test passes.
- `make test-static` and the existing CI jobs pass unchanged.
