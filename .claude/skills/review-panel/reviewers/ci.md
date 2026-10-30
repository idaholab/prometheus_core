### CI and tests

Review what is tested, and above all **what would break for a user that no test would catch**.
You are the one reviewer who runs the full test suites of every touched component. First check
the CI results in the shared context. A suite that passed in CI on the commit under review isn't
run again: report it as "passed in CI" with the link. Read the log of a failed job instead of
rerunning it. Run locally only the touched suites that CI didn't run or hasn't finished, and
anything uncommitted:

- frontend: `cd platform/frontend && npm ci && npm run lint && npm run typecheck && node --test
  --experimental-strip-types $(find src -name '*.test.ts') && npm run build`
- backend: `cd platform/backend && uv run ruff check && uv run ruff format --check && uv run
  mypy app/ && uv run pytest`
- agents: `uv run pytest` in each touched agent directory under `platform/agents/`
- sdk: `cd sdk && uv run pytest -m "not integration"`
- agent template: `cd agent-template && uv run pytest`
- platform infrastructure: `cd platform/tests && uv run python -m pytest -m "not integration"`
- always: `python3 platform/scripts/add_markings.py --check`, and `ruff check` /
  `ruff format --check` for the touched projects in the CI `ruff` matrix

A change to a workflow job counts as touching what that job runs. Report what passed and what
failed, with the failing output.

1. **Gaps that matter to users.** For each behavior the change touches, how would a user notice
   that it broke? For example: the platform doesn't start, an agent doesn't register, the chat
   shows nothing, a secret gets printed, a slide command fails. Is there a test that fails first?
   If not, propose the **simplest test that would**, and say where it goes. Prefer a unit test
   over a live test, and a live test over a full-stack CI job.
2. **New coverage, not just kept coverage.** What can be tested now that couldn't be before?
   Propose concrete tests or CI jobs for user-visible behavior that has never been tested.
3. **Nothing silently lost.** What does CI test today in this area (`.github/workflows/test.yml`)?
   Does the change keep all of it: moved tests, renamed paths in the job matrices, a new
   component or agent that no job runs?
4. **Cost and flakiness.** Runtime, network pulls, and timing-dependent checks. Which tests
   should run on every PR, and which only on `devel`?

Read: the diff; `.github/workflows/test.yml`; the `tests/` folders of the touched components.
