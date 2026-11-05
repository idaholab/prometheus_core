# Contributing to Prometheus

Prometheus is a collaborative effort and we welcome contributions: bug reports,
fixes, new agents, documentation, and ideas. This guide covers how to propose a
change and what we look for before merging it.

[DEVELOPMENT.md](DEVELOPMENT.md) goes further: how to scope and split work,
stacked pull requests, writing the description, review, and interface changes.

Everyone taking part in this project is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

> [!TIP]
> **Start a discussion first.** Before investing time in a larger change, open a
> [GitHub Discussion](https://github.com/idaholab/prometheus_core/discussions) or an
> issue. That can settle the best approach early, and sometimes shows that what you
> need is already possible.

> [!IMPORTANT]
> **Security vulnerabilities must not be reported in public issues.** See
> [SECURITY.md](SECURITY.md).

## Repository layout

This is a monorepo. Each top-level directory has its own `Makefile`, dependencies,
and tests, so run commands from inside the directory you are changing:

| Directory | Developer docs |
|-----------|----------------|
| [`platform/`](platform/) | [platform/README.md](platform/README.md), [platform/backend/README.md](platform/backend/README.md), [platform/frontend/README.md](platform/frontend/README.md) |
| [`sdk/`](sdk/) | [sdk/DEVELOPMENT.md](sdk/DEVELOPMENT.md), [sdk/INSTALL.md](sdk/INSTALL.md) |
| [`agent-template/`](agent-template/) | [agent-template/README.md](agent-template/README.md), [agent-template/TUTORIAL.md](agent-template/TUTORIAL.md) |

Run `make help` in any of them to list its targets.

## Issues

Search [existing issues](https://github.com/idaholab/prometheus_core/issues) before
filing a new one. Then use the **Bug report** or **Feature request** form, and say
which component (`platform`, `sdk`, `agent-template`) is involved.

An issue isn't required for every pull request. For anything beyond a small fix,
though, please open or reference one so the motivation is on record. A
`closes #123` line in the PR description or a commit message closes the issue on
merge; `refs #123` links it without closing it.

## Workflow

External contributors work in a fork. Core maintainers with write access may push
branches to this repository directly; everything else below still applies.

### 1. Fork and clone

Fork [idaholab/prometheus_core](https://github.com/idaholab/prometheus_core) on GitHub,
then clone your fork and add the main repository as `upstream`:

```bash
git clone git@github.com:<username>/prometheus_core.git
cd prometheus_core
git remote add upstream git@github.com:idaholab/prometheus_core.git
```

### 2. Branch from `devel`

`devel` is the integration branch, and all pull requests target it.

```bash
git fetch upstream
git checkout -b <branch-name> upstream/devel
```

In `sdk/`, install the local git hooks once per clone. They run ruff on commit, and
mypy plus the unit tests on push:

```bash
cd sdk && make hooks
```

### 3. Keep changes small

Make each pull request a single logical change. A bug fix, a refactor, and a new
feature are three PRs, not one. Small PRs get reviewed sooner and are easier to
revert. Avoid drive-by reformatting or unrelated cleanups; if you spot something
worth fixing, open a separate PR or issue.

### 4. Write good commit messages

```
Short summary in the imperative (about 50 characters)

More detail if needed: what changed and why, not how.
 - Bulleted lists are fine

closes #123
```

Before opening the PR, rebase onto the latest `devel`:

```bash
git fetch upstream
git rebase upstream/devel
```

### 5. Run the checks

CI runs these checks on every pull request. Run the ones for the components you
touched locally first:

| Component | Commands |
|-----------|----------|
| `sdk/` | `make check` (ruff lint, ruff format, mypy) and `make test` |
| `agent-template/` | `make check` and `make test` |
| `platform/backend/` | `uv run ruff check . && uv run ruff format --check .` and `uv run pytest` |
| `platform/frontend/` | `make check` (ESLint, TypeScript and the Vitest tests) and `make test-e2e` (the Playwright end-to-end tests) |
| `platform/` | `make test-static` and `make check-markings` |

`make fix` (in `sdk/` and `agent-template/`) applies ruff's automatic fixes and
formatting.

A few rules apply repository-wide:

- **Copyright markings.** Every tracked `.py`, `.ts`, `.tsx`, and `.jsx` file needs
  the project's copyright marking. Run `git add` on new files first, then
  `python3 platform/scripts/add_markings.py` to add the marking wherever it's
  missing (`--check` only reports the files that lack it).
- **Lockfiles.** After changing a `pyproject.toml`, run `uv lock` in its
  directory and commit the updated `uv.lock`. CI runs `uv lock --check` in
  every directory with a tracked `uv.lock`, so a new uv project is checked as
  soon as its lockfile is committed. Also add its directory to the uv entry in
  `.github/dependabot.yml`; a test fails until you do.
- **Coverage floors.** `sdk/` enforces a minimum coverage (`fail_under` in
  `pyproject.toml`). Add tests with your change, and don't lower the floor.
- **No secrets.** CI scans every commit with gitleaks. Never commit `.env` files,
  API keys, tokens, or credentials, even in tests or examples.

### 6. Update the documentation

If your change affects behavior, configuration, or an API, update the README or
docs of the component you touched in the same pull request.

### 7. Open a pull request

Push your branch to your fork and open a pull request against `devel`. The PR
template asks for:

- **Reason**: why the change is needed
- **Design**: a short description of the approach
- **Impact**: whether it changes existing APIs or behavior

## Review

Reviewers are requested automatically from [CODEOWNERS](CODEOWNERS), based on the
paths you changed. Maintainers use the `pr: ready for review` and
`pr: ready for merge` labels to track progress. Expect questions and requested
changes; they're part of the process, not a judgment of the work. A pull request
is merged once CI passes and a code owner approves it.

## AI-assisted contributions

You may use AI coding assistants (Claude Code, Copilot, ChatGPT, and the like) to
help write code, tests, or docs. You remain the author and are responsible for
the result:

- **Disclose it.** Tick the AI-assistance box in the PR template and say briefly
  what the tool was used for.
- **Understand every line.** Read, run, and test what you submit, and be able to
  explain and defend it in review. "The AI wrote it" doesn't answer a review
  question.
- **Respect licensing.** Make sure the output doesn't reproduce code under a
  license incompatible with this project's MIT license.
- **Keep the bar the same.** Generated changes follow the small-PR, testing, and
  documentation rules above. Large, unreviewed, or speculative AI-generated pull
  requests or issues will be closed.

The repository contains `AGENTS.md` and `CLAUDE.md` files (for example
[platform/AGENTS.md](platform/AGENTS.md) and [sdk/AGENTS.md](sdk/AGENTS.md)) that
give coding agents project-specific instructions. Point your tool at them.

## Licensing

Prometheus is released under the [MIT License](LICENSE); see also
[NOTICE.txt](NOTICE.txt). By submitting a contribution you agree that it is
licensed under the same MIT License, and that you have the right to submit it
under that license.
