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
- SPC-REQ-007-04: `.github/actions/speccheck-verify` MUST download every `speccheck-results-*`
  artifact of the run, look up the display name of every job of the run, write the full report
  with those names and upload it as the `speccheck-report` artifact, then run `verify` with
  `--summary` (see SPC-REQ-008-07), the artifact's URL and the same names, and fail when `verify`
  fails.
- SPC-REQ-007-05: Each result's link MUST open the job that produced it, in the run attempt that
  produced it, re-runs included. When the job can't be identified, the link MUST open that run
  attempt.
- SPC-REQ-007-06: After one `speccheck-install` step, a job MUST be able to run the `speccheck`
  command without setting up Python itself, and `speccheck-verify` MUST use that command.
- SPC-REQ-007-07: GitHub Actions MUST be a supported CI provider: the CI context comes from its
  `GITHUB_*` variables, and its run and job links have the form
  `<server>/<owner>/<repo>/actions/runs/<id>`, optionally followed by `/attempts/<n>` or
  `/job/<id>`, and its artifact links add `/artifacts/<id>` to the run link.
- SPC-REQ-007-08: `speccheck-verify` MUST need only `contents: read` and `actions: read`
  permissions, and no secrets.
- SPC-REQ-007-09: When `speccheck-verify` can't look up the run's job names, it MUST go on without
  them, so each result is named by its producer.
- SPC-REQ-007-10: speccheck MUST write a link to a CI page only when it runs in CI, and only to the
  server and repository of that run. A link to a run, job or artifact MUST also have that kind's
  form for its provider (see SPC-REQ-007-07). A link that fails either check MUST be left out and
  its text written plainly.
