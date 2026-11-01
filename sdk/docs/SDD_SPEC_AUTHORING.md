# SDD Spec Authoring Standard

This document defines how to write and update specs in `specs/` for
spec-driven development in `prometheus_api`. Use it when adding a capability,
changing public behavior, or asking an AI assistant to draft a spec.

## Goals

- Keep specs compact enough for coding agents to load and act on.
- Make every durable behavior traceable through stable REQ and BEH IDs.
- Separate required behavior from examples, implementation notes, and open questions.
- Preserve history by retiring IDs instead of reusing or renumbering them.

## File Model

Specs live in `specs/` with `specs/000-index.md` as the entry point. Each
capability spec uses a three-digit number:

```text
specs/NNN-short-capability-name.md
```

Choose the next free `NNN` unless the change clearly belongs to an existing
capability. Update `specs/000-index.md` whenever a spec file is added, renamed,
retired, or materially re-scoped.

## Required Structure

Every numbered spec should use this shape:

```markdown
# NNN - Capability name

status: draft | implemented | retired
sources: path/to/code.py, tests/test_feature.py, docs/example.md
tests: tests, .github/workflows   (only for specs checked by speccheck; see below)
depends-on: none | 001, 004

## Purpose
One short paragraph describing the capability boundary.

## Requirements
- REQ-NNN-01: The system MUST ...
- REQ-NNN-02: The system SHOULD ...

## Behavior
- BEH-NNN-01: GIVEN ... WHEN ... THEN ...
- BEH-NNN-02: GIVEN ... WHEN ... THEN ...

## Interfaces
- `public.symbol(...)`
- `ENV_VAR`
- `make target`

## Constraints
- Security, compatibility, parity, or operational constraints.

## Out of scope / Non-goals
- Explicit exclusions that prevent scope creep.

## Open questions
- Known gaps, ambiguities, or weak test coverage.
```

Use front-loaded IDs for both requirement and behavior bullets. Do not use
trailing ID syntax for behavior scenarios.

## ID Rules

- Requirement IDs use `REQ-NNN-XX`.
- Behavior IDs use `BEH-NNN-XX`.
- IDs are stable once committed.
- Use the next free two-digit suffix within the spec.
- Do not renumber existing IDs to make a list look tidy.
- Do not reuse deleted IDs. Mark removed requirements as retired in place, or
  keep a short note that the ID is retired.
- If a requirement is inferred from code but not covered by tests, append
  `⚠ untested` to the requirement line.
- Remove `⚠ untested` only when test evidence exists and the test cites or
  clearly maps to the ID.
- If a requirement is agreed but delivered by a later, named step of a plan,
  append `(planned: <step>)`, for example `(planned: step 3b)`, instead of
  `⚠ untested`. The PR that delivers it removes the marker and cites the ID
  from a test. A requirement is never both planned and untested.

## Requirement Writing

Requirements describe durable obligations, not implementation steps.

- Use MUST for required behavior.
- Use SHOULD for expected behavior with documented exceptions.
- Use MAY for optional behavior.
- Keep one obligation per requirement when practical.
- Include security, error handling, environment-variable, sync/async parity,
  and compatibility behavior when those are part of the public contract.
- Prefer precise names for public functions, models, routes, files, commands,
  and environment variables.
- Avoid vague language such as "properly", "robustly", or "as needed" unless
  the condition is defined in the same requirement.

Good:

```markdown
- REQ-008-13: Registry retry counts MUST resolve from explicit args or
  `REGISTRY_MAX_RETRIES`, ignore invalid values without blocking startup,
  clamp negative values to zero, and use exponential backoff up to `max_delay`.
```

Weak:

```markdown
- REQ-008-13: Registry retries MUST work properly.
```

## Behavior Writing

Behavior scenarios are concrete examples that help humans and agents understand
the requirement. Use one scenario per bullet in GIVEN/WHEN/THEN form:

```markdown
- BEH-NNN-01: GIVEN a starting state WHEN an action occurs THEN an observable
  result happens.
```

Behavior scenarios should:

- Use the same `NNN` as their spec.
- Focus on externally visible effects, not private implementation details.
- Cover edge cases that are easy to regress.
- Map naturally to tests, even when the test does not use the exact wording.
- Stay short enough that a coding agent can scan them quickly.

## Source Mining Checklist

When extracting a spec from implemented code, inspect:

- Public package exports and constructors.
- Pydantic models and validators.
- HTTP routes, request/response models, and middleware.
- Environment variable reads and documented defaults.
- Error handling and exception mapping.
- Sync and async resource pairs.
- Tests, especially regression tests that encode edge cases.
- Docs, examples, Makefile targets, Dockerfile behavior, and packaging metadata.
- Security-sensitive logging, credential handling, and local file access.

Record inspected files in the `sources:` line. The list does not need every
transitive import, but it should include the files that justify the requirements.

## Checked Specs

A spec folder can be checked mechanically with
[`common/speccheck`](../../common/speccheck/README.md). Such specs add a
`tests:` line naming the test folders, files and workflows that may cite their
IDs (paths relative to the repository root, comma-separated, or `none`). The
checker fails when a requirement is neither cited, `⚠ untested` nor
`(planned: ...)`, when a test cites an unknown, retired or out-of-scope ID,
or when a marker is left on a cited requirement. In a workflow, an ID is cited
by a `# Covers REQ-...` (the job checks it) or `# Implements REQ-...` (the job
is the behavior) comment inside a job. This folder's specs are not checked
yet.

## Status Values

- `draft`: proposed or partially extracted behavior that is not fully accepted.
- `implemented`: behavior is expected to match the current codebase.
- `retired`: the capability or spec no longer applies, but the file or IDs are
  retained for history.

When intentional behavior changes, update the spec in the same change as the
code. If code has drifted unintentionally, fix the code or mark the spec issue
explicitly during review.

## Web Chat Prompt

Use this prompt when asking ChatGPT, Claude, or another assistant to draft a
Prometheus API SDD spec:

```text
Use the following Prometheus API SDD standards to create an SDD spec for
<feature name>.

Standards:
- Specs live in specs/ with specs/000-index.md as the entry point.
- Each capability spec is named specs/NNN-short-capability-name.md.
- Use this structure: title, status, sources, depends-on, Purpose,
  Requirements, Behavior, Interfaces, Constraints, Out of scope / Non-goals,
  Open questions.
- Requirement IDs must be front-loaded as REQ-NNN-XX.
- Behavior IDs must be front-loaded as BEH-NNN-XX.
- Do not use trailing behavior ID syntax.
- IDs are stable. Do not reuse retired IDs or renumber existing IDs.
- Requirements use MUST, SHOULD, or MAY and describe durable obligations.
- Behavior bullets use GIVEN/WHEN/THEN and describe observable examples.
- Append "⚠ untested" to inferred requirements that do not have test evidence.
- Include public APIs, routes, commands, environment variables, security
  constraints, sync/async parity, and compatibility behavior when relevant.
- Update specs/000-index.md if a new spec is added or an existing spec changes
  scope.
- Do not invent behavior that is not supported by the provided context. Put
  uncertainty in Open questions.

Context to use:
- Existing related specs:
  <paste related specs>
- Code and tests:
  <paste relevant files or summaries>
- Desired feature/change:
  <describe new feature>

Return:
1. The proposed spec markdown.
2. Any index row changes.
3. A short list of tests needed to satisfy or remove "⚠ untested" markers.
```

## Final Review Checklist

Before committing spec changes:

- The spec number and filename match the capability.
- All REQ and BEH bullets have front-loaded IDs.
- New IDs use the next free suffix and do not reuse retired IDs.
- Requirements are testable or marked `⚠ untested`.
- Behavior scenarios are concrete GIVEN/WHEN/THEN examples.
- Interfaces list the public surface future agents should preserve.
- Open questions capture uncertainty instead of hiding it in vague requirements.
- `specs/000-index.md`, relevant docs, and `AGENTS.md` are updated when needed.
