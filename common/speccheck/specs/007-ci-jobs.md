# 007 - CI jobs

status: implemented

## Purpose

A CI job can be the evidence for a requirement. Every workflow ends with the same final job, which
checks what its jobs proved.

## Requirements

- SPC-REQ-007-01: `record` MUST write a results file with one `passed` result of kind `ci` that
  claims each ID in the job's `[ci.<job>] covers` with its explanation. A job with no entry MUST be
  a config error.
- SPC-REQ-007-02: A CI job's results MUST count only for the IDs its config entry lists.
- SPC-REQ-007-03: `.github/actions/speccheck-upload` MUST upload a job's results as an artifact
  named `speccheck-results-<name>`, and MUST fail the job when there is nothing to upload.
- SPC-REQ-007-04: `.github/actions/speccheck-verify` MUST read every `speccheck-results-*` artifact
  of the run, upload the full report as the `speccheck-report` artifact, and write a step summary
  as `verify --summary` does (see SPC-REQ-008-07) that links to that artifact. Both MUST name jobs
  by their display names. The action MUST fail when `verify` fails, and MUST still upload the
  report.
- SPC-REQ-007-05: Each result's link MUST open the job that produced it, in the run attempt that
  produced it, re-runs included. When the job can't be identified, the link MUST open that run
  attempt.
- SPC-REQ-007-06: After one `speccheck-install` step, a job MUST be able to run the `speccheck`
  command without setting up Python itself.
- SPC-REQ-007-07: GitHub Actions MUST be a supported CI provider. Its CI context comes from its
  `GITHUB_*` variables. A run link is `<server>/<owner>/<repo>/actions/runs/<id>`, optionally
  followed by `/attempts/<n>`; a job link is that run link without the attempt, followed by
  `/job/<id>`; and an artifact link is that run link without the attempt, followed by
  `/artifacts/<id>`.
- SPC-REQ-007-08: `speccheck-verify` MUST need only `contents: read` and `actions: read`
  permissions, and no secrets.
- SPC-REQ-007-09: When `speccheck-verify` can't look up the run's job names, it MUST go on without
  them, so each result is named by its producer.
- SPC-REQ-007-10: speccheck MUST write a URL to a CI page, as a link or in the `url` of a result in
  `--json`, only when it runs in CI (on GitHub Actions, `GITHUB_ACTIONS` is `true`), and only to
  the server and repository of that run. A URL to a run, job or artifact MUST also have that
  kind's form for its provider (see SPC-REQ-007-07). A URL that fails either check MUST be left
  out: its text is written plainly, and the `url` is empty.
