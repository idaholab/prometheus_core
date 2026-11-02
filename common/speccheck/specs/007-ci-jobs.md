# 007 - CI jobs

status: implemented

## Purpose

A CI job can be the evidence for a requirement. Every workflow ends with the same final job, which
checks what its jobs proved.

## Requirements

- SPC-REQ-007-01: `record` MUST write a results file with one `passed` result of kind `ci` that
  claims each ID in the job's `[ci.<job>] covers` with its explanation, and MUST fail with exit 2
  when the job has no entry.
- SPC-REQ-007-02: A CI job's results MUST count only for the IDs its config entry lists.
- SPC-REQ-007-03: `.github/actions/speccheck-upload` MUST upload a job's results as an artifact
  named `speccheck-results-<name>`, and MUST fail the job when there is nothing to upload.
- SPC-REQ-007-04: `.github/actions/speccheck-verify` MUST download every `speccheck-results-*`
  artifact of the run, write the full report and upload it as the `speccheck-report` artifact,
  then run `verify` with `--summary` (see SPC-REQ-008-07) and the artifact's URL, and fail when
  `verify` fails, with read-only permissions and no secrets.
- SPC-REQ-007-05: Each result's link MUST open the job that produced it, in the run attempt that
  produced it, re-runs included. When the job can't be identified, the link MUST open that run
  attempt.
- SPC-REQ-007-06: After one `speccheck-install` step, a job MUST be able to run the `speccheck`
  command without setting up Python itself, and `speccheck-verify` MUST use that command.
- SPC-REQ-007-07: GitHub Actions MUST be a supported CI provider: the CI context comes from its
  `GITHUB_*` variables, and its run and job links have the form
  `<server>/<owner>/<repo>/actions/runs/<id>`, optionally followed by `/attempts/<n>` or
  `/job/<id>`, and its artifact links add `/artifacts/<id>` to the run link.
