# Testing

How we test Prometheus: which kind of test a change needs, how much coverage is
enough, and the rules every test follows. [CONTRIBUTING.md](CONTRIBUTING.md#5-run-the-checks)
lists the commands that run them.

## Which test a change needs

Test at the narrowest level that proves the behavior. A test that can run
without a browser, a container or a network should.

| The change | The test | Where it goes | Example |
|---|---|---|---|
| Python logic, a route, an A2A handler | **Unit** (pytest) | The package's `tests/` | `platform/backend/tests/test_sessions.py` |
| Python code that needs a real service: Valkey, Postgres, DeepLynx | **Integration** (pytest, marked `integration`) | `platform/tests/infrastructure/` | `test_integration_*.py` |
| Frontend logic: stores, parsers, formatters | **Unit** (Vitest, `*.test.ts`, runs in Node) | Next to the file it tests | `features/chat/store/chat.test.ts` |
| A shared frontend component in `components/ui` | **Component** (Vitest and Testing Library, `*.dom.test.tsx`, runs in jsdom) | Next to the component | `components/ui/FilterChips/FilterChips.dom.test.tsx` |
| A screen's own behavior: a filter, a form, a dialog | **Component**, of the screen as a whole | Next to the screen's main component | `features/workflows/NodeInspector.dom.test.tsx` |
| A flow that crosses the frontend and backend: sign-in, a chat reply, opening an artifact | **End-to-end** (Playwright, `*.spec.ts`) | `platform/frontend/e2e/` | `e2e/login.spec.ts` |

End-to-end tests are slow and the hardest to debug, so write one only for a flow
that a unit or component test can't prove, because the bug would be in how the
pieces connect. A screen's behavior belongs in a component test, not an
end-to-end test. The frontend README describes how to [write each kind of
frontend test](platform/frontend/README.md#testing) and [where code and tests
go](platform/frontend/README.md#where-code-and-tests-go).

The SDK's [testing guide](sdk/docs/TESTING.md) covers running its suites. It
traces its tests to its specifications; follow
[sdk/docs/SDD_TESTING_STANDARD.md](sdk/docs/SDD_TESTING_STANDARD.md) and
[sdk/docs/SDD_SPEC_AUTHORING.md](sdk/docs/SDD_SPEC_AUTHORING.md) there.

## When a change needs no new test

Some changes have nothing a test could usefully check:

- Layout and styling only: spacing, colors, copy, rearranged markup.
- Wiring that TypeScript or mypy already checks, such as passing a prop through.
- Docs, comments, and configuration that CI already exercises.

Say so in the PR under **Impact**: "No new tests: layout only" is enough. Check
the change by hand, and say how: which screens, which themes, which browser.
A reviewer can still ask for a test.

Everything else gets a test with it. In particular, **a bug fix includes a test
that fails without the fix.**

## How much coverage is enough

Codecov reports coverage on every pull request and annotates uncovered lines in
the diff. "Patch coverage" counts only the lines a PR adds or changes, so code
that was untested before never fails your PR.

### Python

- **100% of new and changed lines** (Codecov patch check). This blocks merging.
- **Total coverage doesn't drop** (Codecov project check). This blocks merging.
- **Each package's floor holds.** `fail_under` in each `pyproject.toml` is the
  lowest total CI accepts. Raise it as coverage improves; never lower it.

### Frontend

- **100% of new and changed lines** in `components/ui/`, feature stores
  (`features/*/store/`) and `lib/`. These are shared by every screen, so a bug in
  them spreads, and they are easy to test.
- **No line target** for screens and layout. Test their behavior with component
  tests and their flows with end-to-end tests, but a line of markup doesn't need
  a test that only renders it.
- **Total coverage doesn't drop.**

For now Codecov only reports the frontend numbers and doesn't block merging.
Reviewers hold PRs to the targets above. Enforcement will be turned on in a later
ticket, once the shared components have tests (PPLT-317).

## Rules for every test

- **Test the behavior, not the implementation.** A refactor should pass the
  existing tests without changing their assertions. If you have to change an
  assertion, the behavior changed; say so in the PR.
- **Name tests for the behavior** they check (`test_expired_session_returns_401`,
  `"wrong credentials show an error"`), not the function they call.
- **Keep unit and component tests hermetic.** No network, no real credentials,
  and no reliance on test order or the wall clock. They must pass without a
  `.env` file.
- **Find elements the way a user does.** Frontend tests query by role and
  accessible name, not by class or test id, so they also check that screen
  readers can find the element.
- **Use only made-up data** in tests and fixtures. The repo is public, and CI
  uploads a failed end-to-end test's screenshots and trace.
- **Don't skip or delete a failing test** to get CI green. Fix it, or explain in
  the PR why the test is wrong.
- **Integration and end-to-end tests that need a running stack** are excluded
  from the default `make test`. Run them when you touch those paths, and say so
  in the PR.
