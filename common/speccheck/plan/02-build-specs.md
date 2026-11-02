# 2: The build and run specs

> **Status: Not started**

## Goal

Bring back the build and run specs from #355 and #361 (both closed 2026-11-01), and check
platformctl against them with speccheck, from real test runs.

## Work

- **Recover the content** from the `speccheck` and `specs-step1` branches on the fork:
  `build/specs/000-index.md`, the eight platformctl specs, the requirements #361 added (step 1's
  and the planned drafts for steps 2 to 9), and the plan edits (each step's Requirements section,
  the README's ground rule, `reviews.md`'s note to the CI reviewer). Leave out
  `common/speccheck/` and `test_specs.py`.
- **Rework them:**
  - drop each spec's `tests:` line and the index's `id-prefix:` line; their content moves into
    `build/specs/speccheck.toml` (prefix `BLD`, producers for `platformctl-unit` and the
    `test.yml` jobs that prove platform requirements);
  - turn every docstring citation in `platform/ctl/tests` into `@pytest.mark.covers(...)`;
  - turn every `# Covers` / `# Implements` workflow comment into a `[ci.<job>]` claim plus a
    `record` step in that job.
- **platformctl:** add `prometheus-speccheck` as a path dev dependency (lock change), set
  `speccheck_config` in its pytest options, set the producer variables in `platformctl.yml`, upload
  results from the `unit` legs, and end the workflow with the `speccheck-verify` job.
  `platformctl.yml`'s path filter gains `build/specs/**` and `common/speccheck/**`.
- **Cross-workflow evidence:** add `speccheck-report.yml` (`design.md`, "Evidence across
  workflows") for the complete check on `devel`, since build and run evidence comes from
  `platformctl.yml`, `test.yml` and `publish-images`.
- **Plan ground rule** (platformctl README): each step removes the planned markers for what it
  delivers and claims those IDs with markers or `[ci.*]` entries.

## Done when

- `platformctl.yml`'s final job passes, and a skipped platformctl test that claims a `BLD-`
  requirement fails it.
- `speccheck-report.yml` produces a complete report for a `devel` commit, linking jobs from more
  than one workflow.
- The platformctl plan says how each later step claims its requirements.

## Reviewers

technical, CI and tests, security, rollout, user. See `reviews.md`.
