# 004 - Results files

status: implemented

## Purpose

A results file is what a test run or a CI job hands to `verify`. It is the only interface between
runners and the checker, so other languages can write one too.

## Requirements

- SPC-REQ-004-01: A results file MUST be JSON Lines: a header with `schema`
  `speccheck-results/1`, the producer, the runner and the CI context, then one line per claiming
  test. A JSON Schema for it MUST ship in `speccheck/schema/`.
- SPC-REQ-004-02: A reader MUST reject a file with any other `schema` value, an unknown key, a
  wrong type, or an unknown outcome, and MUST NOT use any of that file's results.
- SPC-REQ-004-03: A test's outcome MUST merge its setup, call and teardown: an error in setup or
  teardown makes it `error`, a skip makes it `skipped`, an expected failure makes it `xfailed`,
  and an unexpected pass makes it `xpassed`.
- SPC-REQ-004-04: Claiming tests that were skipped or deselected MUST be written too, with that
  outcome, and a `--collect-only` run MUST write them as `collected`.
- SPC-REQ-004-05: The plugin MUST write a file only when `--speccheck-results` or
  `SPECCHECK_RESULTS` asks for one, and MUST write it atomically when the session ends. An
  interrupted session MUST NOT leave a file.
- SPC-REQ-004-06: Under pytest-xdist, the file MUST be written once, by the controller, with every
  worker's results.
- SPC-REQ-004-07: A reader MUST refuse a file over its size limit or with an over-long line, and
  MUST NOT follow symlinks when it searches a folder.
- SPC-REQ-004-08: In GitHub Actions the header MUST carry the server, repository, workflow, job,
  leg, run ID, attempt and commit. Outside CI, `ci` MUST be null.
