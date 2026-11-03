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
  usage or config error. `report` is the exception: it MUST exit 0 when it has written the report,
  whatever the problems (SPC-REQ-006-05). An output path that can't be written MUST be a usage
  error.
- SPC-REQ-008-04: With `--json`, stdout MUST be exactly one JSON object with `schema_version`,
  `command`, `ok` and `problems` on every exit path, usage errors included. `ok` MUST be true
  exactly when the command exits 0, so `report`, which exits 0 whatever is wrong, has `ok` true
  with its problems listed. `check`, `verify` and `report` MUST also give each requirement's ID,
  status and evidence.
- SPC-REQ-008-05: Without `--json`, `lint`, `check` and `verify` MUST print problems to stderr, and
  the last line MUST be a summary of the counts. `verify` MUST name the producers that reported and
  those that are missing. With `--quiet`, a run with no problems MUST print nothing, and one with
  problems MUST print the same as without it. `report` MUST NOT print problems to stderr, since the
  report holds them (SPC-REQ-006-05).
- SPC-REQ-008-06: Every problem MUST be printed as `path:line: message`, or `path: message` when
  it has no line.
- SPC-REQ-008-07: `lint`, `check` and `verify` MUST take `--summary FILE` and append to it one
  line, then one list entry per problem, and nothing else. The line MUST give the number of
  problems when there are any, then the same counts as the summary line on the terminal.
- SPC-REQ-008-08: What `--summary` writes MUST be escaped as in SPC-REQ-006-03 and MUST stay under
  the step summary's 1 MiB limit. When it doesn't fit, it MUST be cut after a whole entry and say
  that it was cut.
- SPC-REQ-008-09: With `--report-url URL`, the summary line MUST link to the full report when
  SPC-REQ-007-10 allows a link to that artifact URL. Otherwise the line MUST have no link.
- SPC-REQ-008-10: `report` and `verify` MUST take `--job-names FILE`, a JSON object from a job's ID
  to its display name. They MUST name each job by its display name when the file gives one, and
  otherwise by its producer. The option MUST be optional, and a file that isn't such an object, or
  that gives a name over 200 characters, MUST be a usage error.
- SPC-REQ-008-11: `--version` MUST print the version.
- SPC-REQ-008-12: Everything speccheck prints MUST have control characters written out (`\n`,
  `\x1b`), so no file name, spec text or results file can start a CI log command.
- SPC-REQ-008-13: Fields MAY be added to the `--json` output within a `schema_version`. Removing
  or changing a field MUST change `schema_version`.
