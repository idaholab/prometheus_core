# 004 - Results files

status: implemented

## Purpose

A results file is what a test run or a CI job hands to `verify`. It is the only interface between
runners and the checker, so other languages can write one too.

## Requirements

- SPC-REQ-004-01: A results file MUST be JSON Lines: a header with `schema` `speccheck-results/1`,
  the producer, the runner and the CI context, then one line per claiming test. A result's
  `covers` MUST be a list of `{"id": ..., "how": ...}` objects, one per claimed ID.
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
  workflow, job, run ID, attempt, the job's own ID when known, and commit. Outside CI, `ci` MUST be
  null.
- SPC-REQ-004-09: A reader MUST reject a file with a result that claims the same ID twice, or
  whose `how` is empty, longer than 1000 characters, or contains a line break, since a writer in
  another language may not have collapsed it.
- SPC-REQ-004-10: The header MUST give `root`, the folder that its results' `file` paths are
  relative to, as a path from the repository's root, so a report can link each test's file. When
  the repository's root can't be found, `root` MUST be null.
- SPC-REQ-004-11: A JSON Schema for the results format MUST ship with the package, and every file
  the plugin writes MUST match it, so a writer in another language can validate its output.
- SPC-REQ-004-12: When `SPECCHECK_ROOT` is set, the header's `root` MUST be its value, so a run in
  a container can say where it is.
