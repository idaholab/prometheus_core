# platformctl

A standard-library Python 3.10+ tool that runs and diagnoses the Prometheus platform.
It is run through the `platform/platformctl` shim, which finds a usable Python:

```sh
cd platform
./platformctl --help
./platformctl doctor
```

This is step 1 of the plan in [`../plans/platformctl/`](../plans/platformctl/README.md): the
scaffold and `doctor`. Nothing else calls it yet, and the Makefile is unchanged. Read the plan's
[`design.md`](../plans/platformctl/design.md) for why things are the way they are.

## Run the tests

```sh
cd platform/ctl
uv sync                                                    # once
uv run pytest --cov --cov-branch               # unit tests; 100% line and branch coverage
uv run pytest tests/shim                                   # the shim, against stub interpreters
uv run pytest tests/shim --shim-shell dash                 # ...under another shell
uv run pytest tests/live --live                            # real shim, real Docker; never with --cov
uv run ruff check . && uv run ruff format --check .
```

- **Unit tests** (`tests/unit/`) mock everything external with a `FakeRunner`
  (`tests/unit/conftest.py`). They must keep 100% line and branch coverage. `# pragma: no cover`
  is banned (a test enforces it); the one exclusion, `if __name__ == "__main__":`, is configured
  in `pyproject.toml`.
- **Live tests** (`tests/live/`) run only with `--live`, refuse to run under coverage and never
  count toward it.
- **The secrets canary** (`tests/unit/test_secrets_canary.py`) gives every secret a unique
  sentinel, runs every command with `--verbose`, `--dry-run`, `--json`, `--debug` and forced
  failures against a fake `docker` that prints the sentinels, and fails if one reaches stdout,
  stderr or a generated file. Extend it with every command you add.

## Layout

```
platformctl/            the package
  __main__.py           Python version check, refuses sudo, then cli.main()
  cli.py                parser from the action registry, global options, error handler
  config.py             the one registry of settings, and their precedence
  context.py            Context: config + target + adapters, passed to actions
  output.py             steps, summaries, and the secret scrubber
  jsonout.py            the --json contract
  paths.py              the platform root and, separately, the agent folder
  compose_files.py      agent discovery, the compose file list, the generated files
  actions/              one module per top-level command
  system/               one adapter per external tool; only runner.py starts subprocesses
  targets/              where the platform runs (compose; k3d later)
  diagnostics/          the doctor framework and its checks
tests/{unit,shim,live}/
```

## Add an action

Add a module to `platformctl/actions/`; it is found automatically.

```python
NAME = "status"
HELP = "What is running"
SECTION = "run"  # run | setup | troubleshoot (see actions/__init__.py), listed in --help by SECTION, ORDER
ORDER = 20  # lower is listed first
ALIASES = []  # old names that still work and print a deprecation notice


def add_arguments(parser): ...
def run(ctx, args) -> int: ...  # the exit code
```

Actions talk to `ctx.target`, never to `docker compose` directly. A group (`config`, `reset`)
exports `SUBCOMMANDS` instead of `add_arguments` and `run`. Print through `ctx.output` so
everything is scrubbed, and add the command to the secrets canary.

## Add a check

Add a function `run(ctx) -> Result(status, evidence, fix)` to a module in `diagnostics/`, wrap it in
a `Check(id, area, tags, run, depends_on=..., fix_kind=...)`, and add it to
`diagnostics/__init__.py` after the checks it depends on. Use the id from the hackathon
`checks.md` where one exists. Evidence says whether a value is set, never the value.

## Add a setting

One `_s(...)` entry in `config.py`'s `SETTINGS`. A key that isn't there is treated as a secret and
is never printed; mark a setting safe only if it can be printed.

## Changing platformctl? Update the docs too

A change to a command, an option or its output also updates the places that teach it. Where it
is referenced (each step keeps this list current):

- the user guide, `platform/docs/docs/platformctl/` (and `from-make.md` for anything a Make
  target forwards to)
- `platform/README.md`, `platform/CLAUDE.md`, `platform/AGENTS.md`, the root `README.md` and
  `CONTRIBUTING.md`
- other docs-site pages (getting started, local DeepLynx, adding agents)
- `agent-template/` docs and `success_message.txt`
- the hackathon knowledge base and skills (`hackathon/.claude/skills/`, including the
  `allowed-tools` in each `SKILL.md`) and slides (`hackathon/slides/slides/*.md`, then
  `make build` there)
- CI (`.github/workflows/test.yml`) and the `platform/Makefile` forwards
- messages pinned by tests because docs or slides quote them

Before a PR, search for what you changed: `git grep -n '<command or option>'`. Once step 2
adds it, a test also parses every documented `./platformctl` line.

Not yet created, because step 1 stays out of them for the hackathon freeze (2026-11-03): the
user guide, `platform/README.md` and the Makefile forwards. Step 2 adds them.
