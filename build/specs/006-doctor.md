# 006 - Doctor

status: draft
sources: platform/ctl/platformctl/actions/doctor.py, platform/ctl/platformctl/diagnostics/base.py, platform/ctl/platformctl/diagnostics/docker_checks.py, platform/ctl/platformctl/diagnostics/env_checks.py, platform/ctl/platformctl/diagnostics/host_checks.py, platform/plans/platformctl/04-doctor.md, hackathon/.claude/skills/how/references/checks.md
tests: platform/ctl/tests, .github/workflows/platformctl.yml, .github/workflows/test.yml
depends-on: 001, 003

## Purpose
`doctor` tells a user what is wrong with their laptop, the platform or their
agent, and what to do about it, without changing anything. Covers how
results are reported, what evidence may show, how checks are selected and
named, the agent-folder checks, and the hints a failed start prints.

## Requirements

## Behavior

## Interfaces
- `./platformctl doctor [check-id...]` (`--tag preflight|diagnose`, `--list`,
  `--agent <dir>`, `--json`)
- Check ids, matching the hackathon `checks.md` ids where one exists
- Per-check JSON fields: `id`, `area`, `tags`, `status`, `evidence`, `fix`,
  `fix_kind`, `skipped_because`, and `counts`

## Constraints
- `doctor` only reads; it never applies a fix.
- Renamed check ids keep an alias, as renamed commands do.

## Out of scope / Non-goals
- The list of individual checks. It lives in the step 4 plan and
  `doctor --list`, so a new check doesn't need a spec change.

## Open questions
