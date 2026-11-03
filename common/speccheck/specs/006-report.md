# 006 - Report

status: implemented

## Purpose

The report says, for every requirement, whether it is proven and by which job, with a link to it.

## Requirements

- SPC-REQ-006-01: The report MUST give a summary line, a count per status, and a table of the
  specs with a link to each, its number of requirements and its count per status. Each spec MUST
  then have a section with its title, its Purpose when it has one, and a table of its requirements'
  IDs and statuses with `failed`, `unclaimed` and `not run` first. Each requirement MUST have its
  own section, in spec order, with its ID, status and full text, and within it one section per
  claiming test or CI job, giving how it proves the requirement.
- SPC-REQ-006-02: Each result MUST give its outcome and the job that produced it, named by its
  display name from `--job-names` when that is known and otherwise by its producer, and link to
  the job, or to the run when the job's ID isn't known.
- SPC-REQ-006-03: Every string taken from a results file, a spec or `--job-names` MUST be written
  so it can't add a heading, list, quote, link, image, autolink, HTML or emphasis to the report,
  and MUST be capped: 200 characters for a name, 1000 for an explanation. A link to a job or run
  MUST be used only if it has the form of a run or job URL of a supported CI provider (see
  SPC-REQ-007-07) and is on the server and repository of the run that `report` is in, so outside
  CI nothing is linked.
- SPC-REQ-006-04: The report MUST list its inputs: the commits, the runs, and which producers
  reported or were missing.
- SPC-REQ-006-05: `report` MUST exit 0 whatever the requirements' statuses are, so the report is
  published even when `verify` fails.
- SPC-REQ-006-06: In CI, each requirement MUST link to its line in its spec file, and each test to
  its line in its test file, at the commit the run tested, on the server and repository of the run
  that `report` is in. A path MUST be linked only when it is plain: letters, digits, `.`, `_`, `-`
  and `/`, with no `..`. Outside CI, nothing is linked.
