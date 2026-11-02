# 003 - Claims

status: implemented

## Purpose

A test claims the requirements it proves with a pytest marker. pytest checks the marker, so a typo
fails locally before CI.

## Requirements

- SPC-REQ-003-01: The plugin MUST register the `covers` marker, so `--strict-markers` accepts it.
- SPC-REQ-003-02: A `covers` mark MUST count on a function, on a class (for every method), on a
  module (`pytestmark`) and on one parameter (`pytest.param(..., marks=...)`). Marks from every
  level add up.
- SPC-REQ-003-03: When the project sets `speccheck_config`, collection MUST fail on a claim of a
  malformed ID, an unknown ID, a retired ID, or an ID in a spec the producer may not claim. The
  message MUST name the test and the ID and say how to fix it: for a malformed ID it shows the ID
  format, for an unknown ID it names the spec to add it to, for a retired ID it says to claim what
  replaced it, and for a disallowed ID it names the `producers.<name>.specs` key. Collection MUST
  also fail when no producer is set (by `SPECCHECK_PRODUCER` or `speccheck_producer`), because
  without one the check of which specs the run may claim would be skipped; the message names both.
- SPC-REQ-003-04: A `covers` mark with no IDs, with a non-string ID, or with keyword arguments
  MUST fail collection.
- SPC-REQ-003-05: Without `speccheck_config`, the plugin MUST NOT check any claim, and MUST NOT
  change any test's outcome.
- SPC-REQ-003-06: A docstring or comment that mentions an ID MUST NOT count as a claim.
- SPC-REQ-003-07: The plugin MUST give each claiming test one outcome, merged from its setup, call
  and teardown: an error in setup or teardown makes it `error`, a skip makes it `skipped`, an
  expected failure makes it `xfailed`, and an unexpected pass makes it `xpassed`. An `error` MUST
  stay `error` for the rest of the session, including when a rerun plugin's later attempt passes.
  A `--collect-only` run MUST write each claiming test as `collected`.
