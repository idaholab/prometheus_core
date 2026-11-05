# 006 - Report

## Purpose

The report says, for every requirement, whether it is proven and by which job, with a link to it.

## Requirements

- SPC-REQ-006-01: The report MUST start with a summary line, a count per status, and a table of
  the specs with a link to each, its number of requirements and its count per status.
- SPC-REQ-006-02: Each result MUST give its outcome and the job that produced it, named as
  SPC-REQ-008-10 says, and linked as SPC-REQ-007-05 says.
- SPC-REQ-006-03: Every string taken from a results file, a spec or `--job-names` MUST be written
  so it can't add a heading, list, quote, link, image, autolink, HTML or emphasis to the report.
- SPC-REQ-006-04: The report MUST list its inputs: the commits, the runs, and which producers
  reported or were missing.
- SPC-REQ-006-05: `report` MUST exit 0 whatever the requirements' statuses are, so the report is
  published even when `verify` fails.
- SPC-REQ-006-06: In CI, each requirement MUST link to its line in its spec file, and each test to
  its line in its test file, at the commit the run tested, as SPC-REQ-007-10 allows. A path MUST be
  linked only when it is plain: letters, digits, `.`, `_`, `-` and `/`, with no `..` as a whole
  segment (`a..b.py` is plain, `a/../b.py` is not).
- SPC-REQ-006-07: Each spec MUST have a section in the report with its title, its Purpose when it
  has one, and a table of its requirements' IDs and statuses, with the reason for each
  unimplemented one, with `failed`, `unclaimed` and `not run` first.
- SPC-REQ-006-08: Each requirement MUST have its own section in the report, in spec order, with its
  ID, status, its reason when it is unimplemented, and its full text without the unimplemented
  suffix, and within it one section per claim: per claiming test or CI job and explanation, giving
  how it proves the requirement and the results of every run of that claim.
- SPC-REQ-006-09: A producer, CI job or display name MUST be at most 200 characters, and a test's
  node ID at most 250. A longer one MUST be refused where it comes in (SPC-REQ-002-09,
  SPC-REQ-003-17, SPC-REQ-004-02, SPC-REQ-008-10), never cut. A heading may still shorten a long
  test name to stay on one line.
