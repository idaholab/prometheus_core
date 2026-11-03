# 008 - The command line

status: implemented

## Purpose

One command with the same global options everywhere, readable output for people, and one JSON
object for scripts and agents.

## Requirements

- SPC-REQ-008-01: `--help` MUST list every command by section, each with a one-line description.
- SPC-REQ-008-02: `--config`, `--json`, `--quiet` and `--verbose` MUST work before or after the
  command.
- SPC-REQ-008-03: The exit code MUST be 0 when there are no problems, 1 when there are, and 2 on a
  usage or config error.
- SPC-REQ-008-04: With `--json`, stdout MUST be exactly one JSON object with `schema_version`,
  `command`, `ok` and `problems` on every exit path, usage errors included. `check`, `verify` and
  `report` MUST also give each requirement's ID, status and evidence.
- SPC-REQ-008-05: Without `--json`, problems MUST go to stderr, and the last line MUST be a summary
  of the counts. `verify` MUST name the producers that reported and those that are missing.
- SPC-REQ-008-06: Every problem MUST be printed as `path:line: message`, or `path: message` when
  it has no line.
- SPC-REQ-008-07: `lint`, `check` and `verify` MUST take `--summary FILE` and append to it one
  line, then one list entry per problem, and nothing else. The line MUST give the number of
  problems when there are any, then the same counts as the summary line on the terminal.
- SPC-REQ-008-08: What `--summary` writes MUST be escaped as in SPC-REQ-006-03 and MUST stay under
  the step summary's 1 MiB limit. When it doesn't fit, it MUST be cut after a whole entry and say
  that it was cut.
- SPC-REQ-008-09: With `--report-url URL`, the summary line MUST link to the full report, but only
  when the URL has the form of an artifact link of a supported CI provider (see SPC-REQ-007-07) on
  the run's server and repository. Otherwise the line MUST have no link.
- SPC-REQ-008-10: `report` and `verify` MUST take `--job-names FILE`, a JSON object from a job's ID
  to its display name, and name each job that way in what they write. It MUST be optional, and a
  file that isn't such an object MUST be a usage error.
- SPC-REQ-008-11: `--version` MUST print the version.
- SPC-REQ-008-12: Everything speccheck prints MUST have control characters written out (`\n`,
  `\x1b`), so no file name, spec text or results file can start a CI log command.
- SPC-REQ-008-13: Fields MAY be added to the `--json` output within a `schema_version`. Removing
  or changing a field MUST change `schema_version`.
