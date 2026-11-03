# 005 - Evidence and verify

status: implemented

## Purpose

Every requirement gets one status from the specs, the config and the results files. `check` and
`verify` fail on the statuses that mean something is wrong.

## Requirements

- SPC-REQ-005-01: A requirement MUST be `passed` when at least one claiming result passed, in any
  producer or leg.
- SPC-REQ-005-02: A claimed requirement none of whose claiming results passed MUST be `failed` in
  `verify`, and the problem MUST list those results with their outcomes.
- SPC-REQ-005-03: A requirement that is not retired, planned or untested, that nothing claims, and
  that isn't `not run` (SPC-REQ-005-04), MUST be `unclaimed`. `check` and `verify` MUST fail on it,
  and the message MUST show the marker to add.
- SPC-REQ-005-04: In `verify`, a requirement MUST be `not run` when it is claimed only by
  producers that didn't report, or when nothing claims it and a test producer that may claim it
  hasn't reported. It MUST fail `verify` only with `--complete`. A requirement the spec marks
  untested, planned or retired is never `not run`, and a requirement with a result but no passing
  one is `failed` even when a producer that claims it hasn't reported.
- SPC-REQ-005-05: With `--complete`, `verify` MUST fail on every expected producer that didn't
  report: every producer, or with `--workflow` the producers that list that workflow.
- SPC-REQ-005-06: A results file from a producer the config doesn't declare MUST be a problem, and
  its results MUST NOT count.
- SPC-REQ-005-07: A requirement that carries the untested or the planned marker and is claimed
  MUST be a problem that says to remove the marker.
- SPC-REQ-005-08: `check` MUST accept a collect-only run's results and MUST NOT look at outcomes: a
  claimed requirement is `claimed` whatever its results' outcomes are.
- SPC-REQ-005-09: `verify` MUST fail when it read no results file, with or without `--complete`,
  and the problem MUST say that nothing is proven.
- SPC-REQ-005-10: `check` and `verify` MUST fail when two claims have the same text
  (SPC-REQ-001-10), across every results file read and every `[ci.<job>]` entry. Claims from the
  same test or CI job (in another leg, producer or attempt) are one claim. The problem MUST name
  both.
- SPC-REQ-005-11: `check` and `verify` MUST report each claim in a results file or a
  `[ci.<job>]` entry of a malformed, unknown or retired ID, or of an ID in a spec its producer may
  not claim, with the same fix as SPC-REQ-003-13 gives, and the claim MUST NOT count.
