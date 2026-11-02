# 008 - The command line

status: implemented

## Purpose

One command with the same global options everywhere, readable output for people, and one JSON
object for scripts and agents.

## Requirements

- SPC-REQ-008-01: `--help` MUST list every command by section, each with a one-line description.
- SPC-REQ-008-02: `--config`, `--json`, `--quiet` and `--verbose` MUST work before or after the
  command. `--version` MUST print the version.
- SPC-REQ-008-03: The exit code MUST be 0 when there are no problems, 1 when there are, and 2 on a
  usage or config error.
- SPC-REQ-008-04: With `--json`, stdout MUST be exactly one JSON object with `schema_version`,
  `command`, `ok` and `problems` on every exit path, usage errors included. `check`, `verify` and
  `report` MUST also give each requirement's ID, status and evidence. Fields MAY be added within a
  `schema_version`; removing or changing a field MUST change it.
- SPC-REQ-008-05: Without `--json`, problems MUST go to stderr, and the last line MUST be a summary
  of the counts. `verify` MUST name the producers that reported and those that are missing.
- SPC-REQ-008-06: Every problem MUST be printed as `path:line: message`. Everything speccheck prints
  MUST have control characters written out (`\n`, `\x1b`), so no file name, spec text or results
  file can start a CI log command.
