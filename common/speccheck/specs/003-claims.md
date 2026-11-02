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
  message MUST name the test and say what to do.
- SPC-REQ-003-04: A `covers` mark with no IDs, with a non-string ID, or with keyword arguments
  MUST fail collection.
- SPC-REQ-003-05: Without `speccheck_config` and without a results path, the plugin MUST NOT check
  or write anything, and MUST NOT change any test's outcome.
- SPC-REQ-003-06: A docstring or comment that mentions an ID MUST NOT count as a claim.
