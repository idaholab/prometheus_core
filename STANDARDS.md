# Software standards

> [!NOTE]
> **Draft.** This document records the standards the repository follows today
> and proposes a few more. Items marked **Proposed** aren't enforced yet.
> [Open questions](#open-questions) lists the decisions still to be made.

These standards apply to all code in this repository. How work is proposed and
reviewed is covered in [CONTRIBUTING.md](CONTRIBUTING.md) and
[DEVELOPMENT.md](DEVELOPMENT.md). Where a component has its own detailed rules,
this document links to them rather than repeating them.

## Languages and supported versions

| Language | Version | Where it's set |
|----------|---------|----------------|
| Python | 3.12 minimum; CI tests 3.12, 3.13, and 3.14 | `requires-python` in each `pyproject.toml`; the `python` matrix in `.github/workflows/test.yml` |
| Node.js | 22 (pinned to 22.23.3) | `platform/frontend/Dockerfile`, the `node-version` in CI |
| TypeScript | strict mode | `platform/frontend/tsconfig.json` |

Container images build on Python 3.12. Write code that runs on the minimum
version; don't use features from newer releases until the minimum is raised.

## Style and linting

Formatting isn't a review topic. The formatters decide, and CI enforces them.

Python code is linted and formatted with ruff. A file's rules are in the
closest `pyproject.toml` above it, which may extend `platform/ruff.toml`. Each
component pins its own ruff version in its lockfile, so run ruff through
`uv run` or `make` rather than a global install. The frontend uses ESLint and
`tsc`, with zero warnings allowed.

### Naming

- **Python:** `snake_case` for modules, functions, variables, and tests;
  `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants and environment
  variables. Prefix private names with `_`.
- **TypeScript:** `camelCase` for variables and functions, `PascalCase` for
  components, types, and interfaces. A React component's file is named after
  the component (`StatusPill.tsx`).
- **Files and branches:** lowercase with hyphens, except where a language
  convention says otherwise (Python modules use underscores).

Name things for what they mean in the domain, not for how they're implemented.

### Suppressions

Don't silence a linter or type checker to make CI pass. When a suppression is
truly needed, make it narrow and give the reason:

```python
result = legacy_call()  # type: ignore[no-untyped-call]  # vendor stub is missing
```

Use a rule-specific `# noqa: E402`, never a bare `# noqa`. The same goes for
`// eslint-disable-next-line <rule>` in TypeScript.

## Types

- **Python:** annotate the signatures of all public functions and methods.
  mypy runs in CI for `platform/backend/` and `agent-template/`. For the SDK it
  runs only in the local pre-push hook (see [Open questions](#open-questions)).
  Use Pydantic models for data that crosses a boundary (HTTP payloads, A2A
  messages, configuration) instead of untyped `dict`s.
- **TypeScript:** strict mode is on, including `noUnusedLocals` and
  `noUnusedParameters`. Avoid `any`; use `unknown` and narrow it.

## Documentation in code

- **Proposed:** every public module, class, and function in `sdk/` and
  `platform/backend/` has a docstring saying what it does and anything a caller
  must know (side effects, errors raised, units). Private helpers need one only
  when the name doesn't say enough.
- Comments explain *why*, not *what*. Delete comments that restate the code.
- Don't leave commented-out code; it's in the git history.
- A `TODO` comment includes a Jira ticket reference (`# TODO(PPLT-123): ...`)
  so that it's tracked somewhere.
- Behavior, configuration, and API changes update the component's README or
  docs in the same pull request (see [DEVELOPMENT.md](DEVELOPMENT.md)).

## Error handling

- **Fail loudly.** Don't catch an exception just to log it and carry on, unless
  carrying on is correct. Never use a bare `except:` or swallow
  `except Exception: pass`.
- **Catch narrowly.** Catch the specific exceptions you expect, as close as
  possible to where you can do something about them.
- **Keep the cause.** When converting an exception, chain it
  (`raise ConfigError(...) from exc`).
- **Validate at the edges.** Check input where it enters the system (HTTP
  routes, A2A requests, configuration loading), then trust it inside.
- **Handle what can happen,** not what can't. Don't add defensive code for
  states the types already rule out.
- **Backend errors:** route errors use `HTTPException` with a stable `detail`
  string; the frontend and tests depend on those strings. Shared error
  responses are documented in `platform/backend/app/api_responses.py`.

## Logging

- Use the standard `logging` module with a module-level
  `logger = logging.getLogger(__name__)`. Don't use `print` in library or
  service code.
- Choose the level by audience: `debug` for developers, `info` for normal
  operation, `warning` for a problem that was handled, `error` for a failure
  someone should look at.
- **Never log secrets or user content:** tokens, API keys, passwords, session
  IDs, cookies, resolved LLM configurations (they contain provider keys), or
  prompt and document content. The SDK keeps prompt logging off unless
  `LLM_DEBUG_LOG_MESSAGES=true`; follow the same rule elsewhere.
- Log identifiers (conversation, task, artifact IDs) instead of payloads, so a
  log line can be traced without exposing data.

## Configuration and secrets

- Configuration comes from environment variables or config files, never from
  constants in code. Each component documents its variables in its
  `.env.example`.
- Treat an empty variable as unset. Docker Compose passes unset variables
  through as empty strings, so read them with
  `(os.getenv("NAME") or "default").strip()`.
- Never commit secrets. gitleaks scans every commit in CI; see
  [CONTRIBUTING.md](CONTRIBUTING.md#5-run-the-checks).
- LLM credentials come from configuration or the environment, never from A2A
  requests.

## Dependencies

- **Lock everything.** Python components use `uv` with a committed `uv.lock`;
  the frontend uses `package-lock.json`. CI installs with `uv sync --frozen` and
  `npm ci`, so the lockfile must match the manifest.
- **Pin tooling.** GitHub Actions are pinned to commit SHAs, and container base
  images to digests, with the version in a comment. Keep it that way when you
  add or update one.
- **Add dependencies deliberately.** Say in the PR why a new dependency is
  needed and why the standard library or an existing dependency won't do.
  Check its license (it must be compatible with MIT) and that it's maintained.
- **Declare version ranges** for libraries the SDK exposes to downstream agents
  (for example, `a2a-sdk>=1.0.0,<2`), so agents can resolve them alongside their
  own dependencies.
- **Update in their own PRs.** Dependency bumps are separate from feature work.
  There's no automated updater yet (see [Open questions](#open-questions)).

## Container images

**Prioritize build caching.** Images are rebuilt constantly, and most rebuilds
follow a change to one file. A Docker layer is rebuilt when its instruction or
any file it reads changes, and so is every layer after it. Write Dockerfiles so
that one change re-runs as little as possible:

- **Order layers from least to most frequently changed:** system packages,
  users, dependencies, then application code.
- **Install dependencies in their own layer,** from the lockfile only
  (`uv sync --locked` with `pyproject.toml` and `uv.lock` bind-mounted, or
  `npm ci`), so a code change never reinstalls them.
- **Copy only what the image uses.** Avoid `COPY . .`: an edit to a README
  shouldn't rebuild anything.
- **Give every build context a `.dockerignore`,** with patterns starting `**/`
  (`**/__pycache__`); without it a pattern matches only at the context root.
- **Share the uv cache mount** (`--mount=type=cache,id=prometheus-uv-cache,...`)
  across images.
- **Check it:** change one source file and rebuild. Only the layers from that
  file's `COPY` onward should run again.

## Testing

The PR-level rules (patch coverage, coverage floors, regression tests) are in
[DEVELOPMENT.md](DEVELOPMENT.md#tests-and-checks). For writing the tests
themselves:

- **Use pytest** for Python and `node --test` for frontend unit tests (files
  named `*.test.ts`).
- **Test at the narrowest level that proves the behavior:** unit tests for
  logic, route or app tests for HTTP and A2A behavior, integration tests (marked
  `integration`) only for what needs a real external service.
- **Keep unit tests hermetic.** No network, no real credentials, and no reliance
  on test order or the wall clock. Unit tests must pass without a `.env` file.
- **Name tests for the behavior** they check
  (`test_expired_session_returns_401`), not the function they call.
- The SDK traces tests to its specifications; follow
  [sdk/docs/SDD_TESTING_STANDARD.md](sdk/docs/SDD_TESTING_STANDARD.md) and
  [sdk/docs/SDD_SPEC_AUTHORING.md](sdk/docs/SDD_SPEC_AUTHORING.md) there.

## Security

- Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).
- Authenticate every endpoint unless it's deliberately public (health checks,
  agent cards), and say so in the code when it is.
- Agents verify user identity with the public key only; the private signing key
  stays in the backend.
- **Proposed:** containers run as non-root users. The backend image already
  does; the other images are still to follow.
- Don't build shell commands, SQL, or file paths from unchecked input.

## Copyright markings

Every tracked `.py`, `.ts`, `.tsx`, and `.jsx` file carries the project's
copyright marking. CI checks it; `python3 platform/scripts/add_markings.py`
adds any that are missing.

## Component-specific standards

| Component | Further rules |
|-----------|---------------|
| `sdk/` | [sdk/AGENTS.md](sdk/AGENTS.md), [sdk/DEVELOPMENT.md](sdk/DEVELOPMENT.md), [sdk/docs/TESTING.md](sdk/docs/TESTING.md) |
| `platform/` | [platform/CLAUDE.md](platform/CLAUDE.md) (conventions section), [platform/backend/README.md](platform/backend/README.md) |
| `agent-template/` | [agent-template/README.md](agent-template/README.md) |

## Open questions

These need a team decision. Each one would be its own pull request.

1. **One lint configuration?** Line length (100 or 120) and rule sets differ
   between components. Proposal: adopt agent-template's rule set
   (`E F W I UP B SIM`) everywhere, at 120 characters, fixing each component in
   its own PR.
2. **Run mypy on the SDK in CI,** not only in the pre-push hook.
3. **Enforce the backend's complexity limit** by selecting ruff's `C90` rule,
   which `max-complexity = 10` already assumes.
4. **Docstrings:** enforce them (for example with ruff's `D` rules) or keep them
   a review guideline?
5. **Automated dependency updates:** add Dependabot or Renovate, at least for
   GitHub Actions and base images?
