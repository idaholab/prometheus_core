# 008 - The command line

status: implemented

## Purpose

The same shape as platformctl: one module per command, the same global options everywhere, and
one JSON object for scripts and agents.

## Requirements

- SPC-REQ-008-01: Each command MUST be one module in `speccheck/actions/`, found automatically, and
  `--help` MUST list the commands by section.
- SPC-REQ-008-02: `--config`, `--json`, `--quiet` and `--verbose` MUST work before or after the
  command. `--version` MUST print the version.
- SPC-REQ-008-03: The exit code MUST be 0 when there are no problems, 1 when there are, and 2 on a
  usage or config error.
- SPC-REQ-008-04: With `--json`, stdout MUST be exactly one JSON object with `schema_version`,
  `command`, `ok` and `problems` on every exit path, usage errors included. `check`, `verify` and
  `report` MUST also give each requirement's ID, status and evidence.
- SPC-REQ-008-05: Without `--json`, problems MUST go to stderr, and the last line MUST be a summary
  of the counts. `verify` MUST name the producers that reported and those that are missing.
- SPC-REQ-008-06: `run.py` MUST run speccheck from a checkout with nothing installed.
