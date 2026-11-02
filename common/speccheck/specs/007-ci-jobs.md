# 007 - CI jobs

status: implemented

## Purpose

A CI job can be the evidence for a requirement. Every workflow ends with the same final job, which
checks what its jobs proved.

## Requirements

- SPC-REQ-007-01: `record` MUST write a results file with one `passed` result of kind `ci` for each
  ID in the job's `[ci.<job>] covers`, and MUST fail with exit 2 when the job has no entry.
- SPC-REQ-007-02: A CI job's results MUST count only for the IDs its config entry lists.
- SPC-REQ-007-03: `.github/actions/speccheck-upload` MUST upload a job's results as an artifact
  named `speccheck-results-<name>`, and MUST fail the job when there is nothing to upload.
- SPC-REQ-007-04: `.github/actions/speccheck-verify` MUST download every `speccheck-results-*`
  artifact of the run, run `verify`, put the summary in the step summary, upload the full report as the
  `speccheck-report` artifact, and fail when `verify` fails, with read-only permissions and no
  secrets.
- SPC-REQ-007-05: In `speccheck.yml`, `record` and both composite actions MUST run end to end in a
  real workflow run, and the final `speccheck` job MUST verify speccheck's own specs completely
  from the run's results.
- SPC-REQ-007-06: A results file's run and job links MUST point at the run attempt that wrote it.
  The job link MUST use the job's check run ID when the workflow passes it in.
