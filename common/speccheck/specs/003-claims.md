# 003 - Claims

status: implemented

## Purpose

A test claims the requirements it proves with a pytest marker, and says how it proves each one.
pytest checks the marker, so a typo or a missing explanation fails locally before CI.

## Requirements

- SPC-REQ-003-01: The plugin MUST register the `covers` marker, so `--strict-markers` accepts it.
- SPC-REQ-003-02: A `covers` mark MUST be on a test function that isn't parametrized, or on one
  `pytest.param(..., marks=...)` in the test's own `@pytest.mark.parametrize`, and it MUST claim
  for that one test only.
- SPC-REQ-003-03: When the project sets `speccheck_config`, collection MUST fail on a claim of a
  malformed ID, an unknown ID, a retired ID, or an ID in a spec the producer may not claim, and the
  message MUST name the test and the ID.
- SPC-REQ-003-04: A `covers` mark MUST take exactly two positional strings: the ID, and how the
  test proves it. A mark with any other number of arguments, a non-string, or keyword arguments
  MUST fail collection.
- SPC-REQ-003-05: Without `speccheck_config`, the plugin MUST NOT check claims against the specs
  (003-03, 003-09, 003-13 and 003-14), and MUST NOT change any test's outcome. The checks that need no specs
  (003-02, 003-04, 003-08, 003-10, 003-11, 003-12 and 003-17) MUST run only when the run asks for a results file,
  so installing the plugin changes nothing for a project that doesn't use it.
- SPC-REQ-003-06: A docstring or comment that mentions an ID MUST NOT count as a claim.
- SPC-REQ-003-07: The plugin MUST give each claiming test one outcome, merged from its setup, call
  and teardown: an error in setup or teardown makes it `error`, a skip makes it `skipped`, an
  expected failure makes it `xfailed`, and an unexpected pass makes it `xpassed`. A skip in
  teardown MUST NOT change the outcome of the call.
- SPC-REQ-003-08: Each run of whitespace in an explanation, newlines included, MUST become one
  space, and the ends MUST be trimmed, before it is checked or written.
- SPC-REQ-003-09: When the project sets `speccheck_config`, collection MUST fail when an
  explanation has the same text (SPC-REQ-001-10) as any requirement in the folder that isn't
  retired. The message MUST name that requirement and say to describe how the test proves the
  claimed one.
- SPC-REQ-003-10: Collection MUST fail when one test claims the same ID more than once.
- SPC-REQ-003-11: Collection MUST fail when two claims in the session have the same text
  (SPC-REQ-001-10), whether they are in one test or two and whatever IDs they claim, so a repeat
  that SPC-REQ-005-10 would find later fails before the run. The message MUST name both claims.
- SPC-REQ-003-12: Collection MUST fail on a claiming test with a mark on its class or module
  (`pytestmark`), with a mark on its function while it is parametrized, with more than one
  `parametrize`, or that uses a parametrized fixture. The message MUST say to put the claim on each
  `pytest.param` of one `parametrize`, each with its own explanation.
- SPC-REQ-003-13: The message for a refused ID MUST say how to fix it: for a malformed ID it shows
  the ID format, for an unknown ID it names the spec to add it to, for a retired ID it says to
  claim what replaced it, and for a disallowed ID it names the `producers.<name>.specs` key.
- SPC-REQ-003-14: When the project sets `speccheck_config`, collection MUST fail when no producer
  is set, and the message MUST name both ways to set one: `SPECCHECK_PRODUCER` and
  `speccheck_producer`.
- SPC-REQ-003-15: When a rerun plugin runs a claiming test again, an `error` MUST stay `error` for
  the rest of the session, and a test whose call failed and whose later attempt passes MUST be
  `passed`.
- SPC-REQ-003-16: A `--collect-only` run MUST write each claiming test as `collected`.
- SPC-REQ-003-17: An explanation MUST be refused when, after its whitespace is collapsed as in
  SPC-REQ-003-08, it is empty, longer than 1000 characters, the claimed ID itself, or a placeholder
  (`TODO`, `TBD`, `FIXME`, `...` or `-`, the whole text, in any case). In pytest, a refused
  explanation MUST fail collection, and the message MUST name the test and the ID.
