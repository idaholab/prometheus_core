# platformctl: a Python launcher for the platform

Replace the Docker Compose logic in `platform/Makefile` with a small Python
utility that lives in the platform, is modular, has full unit test coverage,
and can diagnose common setup problems. Every current `make` target keeps
working by forwarding to it.

- Design and decisions: [`design.md`](design.md)
- Command reference and the Make mapping: [`commands.md`](commands.md)
- What breaks, and what only behaves differently:
  [`breaking-changes.md`](breaking-changes.md)
- The review panel each step gets before merging, and which reviewers:
  [`reviews.md`](reviews.md)
- One file per step below. Each step is one pull request and leaves `devel`
  working.

Planned on 2026-10-30, and reviewed from eight perspectives (user, agent
developer, technical, CI, security, rollout, Linux/WSL, AI skills) before
any code was written.

## Timing

The hackathon runs on 2026-11-06 (Day 2 follows). Its slides, skills and
knowledge base are frozen from 2026-11-03 until after Day 2, and so are
`platform/Makefile`, the docs and repo-wide files such as `.gitattributes`.
Only step 1 may land before the freeze, and it touches nothing outside
`platform/ctl/` and the `platform/platformctl` shim: no Makefile, docs,
slides, skills or required CI jobs. Steps 2 onward land after Day 2.

**Before the freeze, separately from this plan:** the hackathon skills and
knowledge base still use container names that #310 removed
(`docker exec agent-valkey`, `docker restart client-agent` in the
`diagnose` and `create-agent` skills' `allowed-tools`, `trace-turn.md`).
That fix is a prerequisite for the event and for step 3c, which builds on
it. `setup_agent.py`'s DeepLynx key copying was fixed in #311.

**Open PRs that touch the same files:** #214 (Google ADK: adds the
`ADK_DB_PASSWORD` secret, which the settings registry and step 7's sync
list must include once it merges), #223 (adds `osti-eval` Make targets,
which step 3a must forward), #197 (removes the `clear-litellm-db` and
LiteLLM text that step 6 fixes). Check them again before each step.

## Steps

| # | File | Summary | Depends on | Status |
|---|------|---------|------------|--------|
| 1 | [`01-scaffold.md`](01-scaffold.md) | Shim, package, settings, runner, compose target, output, `doctor` framework, test setup, path-filtered CI | - | Not started |
| 2 | [`02-port-scripts.md`](02-port-scripts.md) | `config init`, `status`, `deeplynx setup`; remove the old scripts; `make doctor`, `.gitattributes`, the user guide, required CI | 1 | Not started |
| 3a | [`03a-forward-compose.md`](03a-forward-compose.md) | The compose entry file; the Makefile forwards every compose target with the same behaviour | 2 | Not started |
| 3b | [`03b-labels-attached.md`](03b-labels-attached.md) | Platform labels, "already running elsewhere", port checks, restarting your agent | 3a | Not started |
| 3c | [`03c-groups-docs.md`](03c-groups-docs.md) | `agents`, `reset`, `compose`, per-service `up`; switch docs, slides and CI to `./platformctl` | 3b | Not started |
| 4 | [`04-doctor.md`](04-doctor.md) | Full platform and agent-folder checks; hints on failure | 3c | Not started |
| 5 | [`05-docs.md`](05-docs.md) | Contributor docs and a final sweep | 4 | Not started |
| 6 | [`06-fix-existing-docs.md`](06-fix-existing-docs.md) | Follow-on: fix doc problems that predate this work | 5 | Not started |
| 7 | [`07-agent-folders.md`](07-agent-folders.md) | Follow-on: agent folders, in this repo and in their own repositories, on platformctl | 4 | Not started |
| 8 | [`08-k3d-target.md`](08-k3d-target.md) | Future: run the platform on k3d | 3c | Not started |
| 9 | [`09-platform-images.md`](09-platform-images.md) | Future: run the platform from pre-built images of a pinned version | 7 | Not started |

When a step is done, set its status here and in its file to `Done (<date>,
#<PR>)`, and note anything that differs from the plan.

## Ground rules

- Standard library only at runtime, so running the platform needs nothing
  but Python 3.10 or newer. The shim finds one (`python3.14` ...
  `python3.10`, `python3`, then uv), so a Mac whose `python3` is 3.9 still
  works. Dev tools (pytest, pytest-cov, ruff) are dev dependencies.
- 100% line and branch coverage from unit tests that mock every external
  tool. Live tests against the real tools are opt-in (`pytest --live`) and
  never count toward coverage.
- Commands are grouped by what they act on, not by Make target names (see
  `commands.md`); Make only forwards.
- **Every function, global and class variable has its own brief docstring**, in the package and
  in the tests (test functions, fixtures, helpers and test constants alike). That includes every
  field of a dataclass and every class attribute. A variable's docstring is a `"""foo"""` string on
  the line after its assignment. `tests/unit/test_docstrings.py` fails on a missing one. A
  docstring says what the thing does or is for, not its name again: "Two problems are counted
  as \"2 problems\"", not "Several problems are plural".
- **Tests mirror the code.** The unit tests for `platformctl/system/compose.py` are in
  `tests/unit/system/test_compose.py`, and `__init__.py` and `__main__.py` map to
  `test_init.py` and `test_main.py`. A test fails when a module that defines code has no test
  file at its mirrored path, or a test file has no module (apart from the few tests of the
  whole tool, such as the secrets canary). Live tests are split by component
  (`tests/live/`).
- One file per top-level command in `actions/` (a group's subcommands share
  it until it grows into a package). Only `system/runner.py` starts
  subprocesses. Actions talk to a deployment target, never to
  `docker compose` directly, so k3d can be added later.
- Keep the compose files simple, and let users run `docker compose`
  themselves: the tool generates one entry file
  (`docker-compose.platform.yml`) and runs the same file.
- Changes must not break callers: renamed commands keep deprecated aliases,
  scripts use the versioned `--json` output, and a test checks that every
  `./platformctl` line in the Makefile, docs, slides and skills parses.
- **Secrets:** every `.env` value is treated as secret unless the settings
  registry marks it safe, and is never printed: not in output, `--verbose`,
  `--dry-run`, `--json`, errors or tracebacks. A canary test enforces it
  (`design.md`, "Secrets").
- Every step updates the docs and hackathon slides it touches, in the same
  PR, and switches them straight to the new commands (`./platformctl ...`).
  Where something gets simpler, the slide gets simpler too. The user guide on
  the docs site (`platform/docs/docs/platformctl/`, set up in step 2) is
  updated in every step. Exception: nothing participants use changes during
  the hackathon freeze (see Timing).
- **Replace as you go:** a step that adds a capability also replaces the old
  way of doing it, where possible (`design.md`, "Replace as you go").
- **Useful output:** each command says what it's doing and ends with what
  the user needs next, e.g. `up` ends with what's running and the URLs
  (`design.md`, "Output"). Each step lists the output it adds.
- **Every step is reviewed before merging** with the `/review-panel` skill,
  using the reviewers listed for it in `reviews.md` (user, agent developer,
  technical, CI and tests, security, rollout, Linux/WSL, AI skills), each with
  fresh context. The CI reviewer looks above all for what would break for a
  user that no test catches, and the simplest test that would.
- Every PR lists its **breaking changes** (`breaking-changes.md`) and has a
  short "What changes for you" block: commands, files created, first-run
  effects, how to roll back.
- Nothing assumes the platform and an agent share a checkout: agents can
  live in other repositories (`design.md`, "Agents in other repositories").
- User-facing messages that docs, slides or CI quote stay word for word.
