# 005 - Evidence and verify

status: implemented

## Purpose

Every requirement gets one status from the specs, the config and the results files. `check` and
`verify` fail on the statuses that mean something is wrong.

## Requirements

- SPC-REQ-005-01: A requirement MUST be `passed` only when at least one claiming result passed.
  One passing result in any producer or leg is enough.
- SPC-REQ-005-02: A claimed requirement whose claiming results all came out as something other than
  `passed` (failed, error, skipped, xfailed, xpassed, deselected, collected) MUST be `failed` in
  `verify`, and the problem MUST list those results.
- SPC-REQ-005-03: A requirement that is not retired, planned or untested, and that nothing claims,
  MUST be `unclaimed`, and both `check` and `verify` MUST fail on it. The message MUST show the
  marker to add.
- SPC-REQ-005-04: A requirement claimed only by producers that didn't report MUST be `not run`.
  It MUST fail `verify` only with `--complete`.
- SPC-REQ-005-05: With `--complete`, `verify` MUST fail on every expected producer that didn't
  report: every producer, or with `--workflow` the producers that list that workflow.
- SPC-REQ-005-06: A results file from a producer the config doesn't declare MUST be a problem, and
  its results MUST NOT count.
- SPC-REQ-005-07: A requirement that carries the untested or the planned marker and is claimed
  MUST be a problem that says to remove the marker.
- SPC-REQ-005-08: `check` MUST read a collect-only run's results and fail on unclaimed requirements
  and disallowed claims, whatever the outcomes are.
- SPC-BEH-005-01: GIVEN a test that claims a requirement and is skipped WHEN its run's results file
  is verified THEN the requirement is `failed`, while the same test passing makes it `passed`.
