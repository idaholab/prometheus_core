# 002 - Config

status: implemented

## Purpose

One config describes one spec folder: where it is, its ID prefix, and what may prove it.

## Requirements

- SPC-REQ-002-01: speccheck MUST use `--config PATH` when given, and otherwise `speccheck.toml` in
  the current folder, and otherwise `[tool.speccheck]` in `pyproject.toml`. When none exists, it
  MUST be a config error that says so.
- SPC-REQ-002-02: Paths in the config MUST be relative to the config file, and `specs` MUST name a
  folder that exists.
- SPC-REQ-002-03: An unknown key MUST be an error that names the file and the key, at the top level
  and in every table.
- SPC-REQ-002-04: `id-prefix` MUST be capital letters and digits starting with a letter, or empty
  for bare IDs.
- SPC-REQ-002-05: A `[producers.<name>]` entry MUST be able to limit the specs it may claim to a
  list of spec numbers. `"all"` is the default.
- SPC-REQ-002-06: A `[ci.<job>]` entry's `covers` MUST be a table from ID to how the job proves
  it, with at least one entry. Each explanation MUST NOT be one that SPC-REQ-003-17 refuses or one that
  has a requirement's text (SPC-REQ-003-09), and a problem MUST name the job and the ID.
- SPC-REQ-002-07: The config MUST be read the same way on every supported Python, 3.10 and newer. A
  TOML syntax error MUST be an error naming the file.
- SPC-REQ-002-08: A `[ci.<job>]` entry MUST NOT share a name with a `[producers.<name>]` entry.
