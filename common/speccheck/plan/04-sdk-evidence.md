# 4: Evidence for the sdk requirements

> **Status: Folded into step 3 (2026-11-03)**

With no "untested" state (`design.md`, "Requirement states"), step 3 can't mark the sdk's
unclaimed requirements and leave them for later, so this step's work moved into step 3's "The
rest", split by the same spec areas. What follows is the original plan, kept for the record.

## Goal

Remove the `⚠ untested` markers step 3 added, by claiming each requirement from the tests that
already prove it or by writing the test that does. Split it by spec area so each PR is
reviewable: storage (001 to 004), LLM (005 to 007, 014), agent (008 to 010), contract and Redis
(011, 012), packaging (013).

## Work

- For each requirement: find the test that proves it and add the marker; if none does, write one;
  if it can't be tested cheaply, keep `⚠ untested` and say why under Open questions.
- A requirement that is no longer true is retired, not claimed.
- Don't claim a requirement with a test that only touches it. The CI reviewer checks each claim.
- Coverage (`fail_under` in `sdk/pyproject.toml`) can only go up.

## Done when

- `⚠ untested` is left only where a spec's Open questions say why.
- Each area's PR passes `speccheck-sdk`.

## Reviewers

technical, CI and tests, agent (for 008 to 012), agent developer (for public API wording). See
`reviews.md`.
