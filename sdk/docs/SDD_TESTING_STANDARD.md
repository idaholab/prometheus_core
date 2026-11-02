# SDD Testing Standard

This document defines how tests should support the specs in `specs/`.
Use it when adding requirements, removing `⚠ untested` markers, or reviewing
whether implementation and specs still match.

## Core Rule

Every implemented requirement should have test evidence or carry `⚠ untested`
in the spec. A requirement that a later, named step of a plan delivers carries
`(planned: <step>)` instead, and that step's change removes the marker and cites
the ID from a test. Behavior scenarios should map to at least one test whenever
they describe a regression-prone or user-visible edge case.

## Test Traceability

Tests should cite spec IDs when the relationship is not obvious from the test
name. Use the lightest form that remains clear:

```python
def test_registry_retries_default_url_on_failure():
    """Covers REQ-008-13 and BEH-008-02."""
```

For dense parameterized tests, cite IDs in the parameter name, nearby comment,
or assertion message. Avoid large traceability tables unless a future workflow
needs them.

A spec folder checked by [`common/speccheck`](../../common/speccheck/README.md)
is stricter: there an ID counts only in the docstring of a `test_*` function or
in a `# Covers REQ-...` comment, so cite it in one of those.

## Test Levels

Use the narrowest test that proves the requirement:

- Unit tests for validation, payload shaping, parsing, retry decisions, error
  mapping, redaction, and helper functions.
- Sync/async parity tests when a requirement applies to both storage client
  resource trees or both LLM clients.
- Route or app tests for middleware, Starlette routes, A2A executor behavior,
  request/response payloads, and artifact/event emission.
- Integration tests for behavior that requires DeepLynx or another external
  service. Mark these with `integration` and keep credentials in `.env`.
- Packaging or command tests for Makefile, Dockerfile, wheel, and import smoke
  behavior. Prefer `make test-install` for installability.

Do not use integration tests as the only evidence for behavior that can be
proven quickly with unit tests.

## New Feature Flow

1. Add or update the spec before implementation.
2. Assign stable REQ and BEH IDs using the relevant `NNN`.
3. Mark inferred requirements `⚠ untested` until tests exist.
4. Write focused tests that cite the IDs they cover.
5. Implement the behavior.
6. Remove `⚠ untested` only for IDs covered by passing tests.
7. Update docs, examples, `AGENTS.md`, and migration notes when public behavior
   changes.

## Removing `⚠ untested`

Remove the marker only when:

- A committed test exercises the requirement directly, or
- Existing test coverage is identified and the mapping is obvious or cited.

Do not remove the marker because the code appears correct. If the behavior is
too expensive or unsafe to test locally, keep `⚠ untested` and explain the gap
in the spec's Open questions.

## Pytest Standards

- Test files use `tests/test_*.py`.
- Test classes use `Test*`.
- Test functions use `test_*`.
- Async tests use the configured `asyncio_mode = "auto"`.
- Unit tests should run with `uv run pytest -m "not integration"`.
- Full test runs should use `make test`, `make check`, or the specific Makefile
  target that matches the change.
- Integration tests require `.env` values based on `.env.example`, including
  valid `DEEPLYNX_*` credentials.

## What To Test

For each changed requirement, consider:

- Happy path behavior.
- Validation failures and exception types.
- Empty, missing, duplicate, malformed, or boundary inputs.
- Environment-variable defaults and invalid values.
- Credential and secret redaction behavior.
- Sync and async parity.
- External-service degradation and fallback behavior.
- Backward-compatible public APIs and imports.
- Event ordering and terminal-state behavior for agents.
- Local filesystem and artifact access controls.

## Behavior Scenario Tests

Behavior scenarios should be especially useful as regression tests. A BEH test
does not need to repeat the full GIVEN/WHEN/THEN sentence, but it should make
the same observable claim.

Example:

```python
def test_heartbeat_does_not_overwrite_stream_status():
    """Covers BEH-011-03."""
```

If a BEH scenario is intentionally not tested, keep the related REQ marker as
`⚠ untested` or document the reason in Open questions.

## Review Checklist

Before merging a spec-impacting change:

- New or changed tests cite the relevant REQ or BEH IDs when useful.
- Each new implemented REQ has coverage or `⚠ untested`.
- Behavior scenarios have at least planned or existing regression coverage.
- Sync/async parity requirements are tested on both paths or documented as
  untested.
- Integration-only coverage is marked and does not block normal unit runs.
- The final response or pull request lists the test commands run.
