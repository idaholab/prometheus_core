# 004 - Results files

status: implemented

## Purpose

A results file is what a test run or a CI job hands to `verify`. It is the only interface between
runners and the checker, so other languages can write one too.

## Requirements

- SPC-REQ-004-01: A results file MUST be JSON Lines: a header with `schema` `speccheck-results/1`,
  the producer, the runner and the CI context, then one line per claiming test. A JSON Schema for it
  MUST ship with the package, so a writer in another language can validate its output.
- SPC-REQ-004-02: A reader MUST reject a file with any other `schema` value, a wrong type, or an
  unknown outcome, and MUST NOT use any of that file's results. A reader MUST ignore keys it doesn't
  know, so fields can be added without changing `schema`.
- SPC-REQ-004-03: Each result MUST have one outcome: `passed`, `failed`, `error` (it couldn't run),
  `skipped`, `xfailed` (an expected failure), `xpassed` (an unexpected pass), `deselected` or
  `collected` (only collected, not run). Only `passed` is evidence.
- SPC-REQ-004-04: Claiming tests that were skipped or deselected MUST be written too, with that
  outcome.
- SPC-REQ-004-05: The plugin MUST write a file only when `--speccheck-results` or
  `SPECCHECK_RESULTS` asks for one, and MUST write it atomically when the session ends. An
  interrupted session MUST NOT leave a file.
- SPC-REQ-004-06: Under pytest-xdist, the run MUST write one file that holds every worker's results.
- SPC-REQ-004-07: A reader MUST refuse a file over its size limit or with an over-long line, and
  MUST NOT follow symlinks when it searches a folder.
- SPC-REQ-004-08: In CI, the header MUST carry the CI context: the provider, server, repository,
  workflow, job, leg, run ID, attempt and commit. Outside CI, `ci` MUST be null.
