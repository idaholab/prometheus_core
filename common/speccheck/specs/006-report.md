# 006 - Report

status: implemented

## Purpose

The report says, for every requirement, whether it is proven and by which job, with a link to it.

## Requirements

- SPC-REQ-006-01: The report MUST give a summary line and a count per status, then one table per
  spec with each requirement's ID, status, text and evidence. Requirements that need attention
  MUST come first.
- SPC-REQ-006-02: Each piece of evidence MUST name the test or CI job, its outcome, the producer
  and leg, and link to the job, or to the run when the job's ID isn't known.
- SPC-REQ-006-03: Every string taken from a results file or a spec MUST be escaped for markdown
  and capped in length, and a link MUST be used only if it has the form of a GitHub Actions run or
  job URL.
- SPC-REQ-006-04: `--summary` MUST append only the counts, the problems and the rows that need
  attention, and MUST stay under the step summary's size limit.
- SPC-REQ-006-05: The report MUST list its inputs: the commits, the runs, and which producers
  reported or were missing.
- SPC-REQ-006-06: `report` MUST exit 0 whatever the requirements' statuses are, so the report is
  published even when `verify` fails.
