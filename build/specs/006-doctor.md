# 006 - Doctor

status: draft
sources: platform/ctl/platformctl/actions/doctor.py, platform/ctl/platformctl/diagnostics/base.py, platform/ctl/platformctl/diagnostics/docker_checks.py, platform/ctl/platformctl/diagnostics/env_checks.py, platform/ctl/platformctl/diagnostics/host_checks.py, platform/plans/platformctl/04-doctor.md, hackathon/.claude/skills/how/references/checks.md
tests: platform/ctl/tests
depends-on: 001, 003

## Purpose
`doctor` tells a user what is wrong with their laptop, the platform or their
agent, and what to do about it, without changing anything. Covers how
results are reported, what evidence may show, how checks are selected and
named, the agent-folder checks, and the hints a failed start prints.

## Requirements

Results

- REQ-006-01: Each check MUST report PASS, WARN, FAIL or SKIP, with evidence
  and, for a WARN or FAIL, a fix.
- REQ-006-02: `doctor` MUST exit 1 when any check FAILs, and 0 when there are
  only warnings.
- REQ-006-03: A check MUST be skipped, saying which check caused it, when a
  check it depends on FAILs or is skipped; a WARN doesn't skip its
  dependents.
- REQ-006-04: A check that doesn't apply to the current target MUST be
  skipped.
- REQ-006-05: Text output MUST list the fix under each failure and end with
  the number of problems (warnings and failures) or "No problems found.".
- REQ-006-06: `doctor` MUST only read: it never applies a fix, and never
  changes `.env`.

Evidence

- REQ-006-07: Evidence MUST say whether a value is set, never the value;
  comparisons say `same` or `differs`, and parse errors name the line, not
  its text.
- REQ-006-08: Evidence MUST NOT echo the output of a command it doesn't
  recognise.

Selecting checks

- REQ-006-09: `doctor` MUST run every applicable check by default, only the
  named checks when ids are given, and only the checks with a tag with
  `--tag preflight` or `--tag diagnose`.
- REQ-006-10: An unknown check id MUST exit 2 and point to `doctor --list`.
- REQ-006-11: `doctor --list` MUST print every check's id, tags and targets
  and exit 0.
- REQ-006-12: A check MUST be selectable by an old id after it is renamed.
- REQ-006-13: Check ids MUST be unique.

`--json`

- REQ-006-14: `doctor --json` MUST give, for each check, `id`, `area`,
  `tags`, `status`, `evidence`, `fix`, `fix_kind` (`safe`, `yes` or `you`)
  and `skipped_because`, plus `counts` by status.
- REQ-006-15: `ok` in `doctor --json` MUST be true when the checks ran,
  whatever they found, and false only when `doctor` itself couldn't run.

The step 1 checks

- REQ-006-16: The `docker` check MUST tell apart a missing `docker`, a
  stopped daemon (with a fix for macOS, Linux and WSL), no permission on the
  socket, `DOCKER_HOST` set (by name only), rootless Docker, Podman (a WARN),
  a missing Compose plugin, and a Compose older than 2.20.0.
- REQ-006-17: The `build-cache-store` check MUST WARN, with the
  `daemon.json` fix, when the build cache is on without the containerd image
  store, and MUST be skipped on Podman.
- REQ-006-18: The `platform-env` check MUST FAIL when `.env` is missing or
  doesn't parse, or a required key is unset, naming the keys.
- REQ-006-19: The `base-image-pin` check MUST WARN about a blank pin line,
  and PASS with `LOCAL_SDK` or the default pin.
- REQ-006-20: `env-hides-environment` MUST WARN, by key name only, when a
  `.env` value differs from the environment's; `env-derived-keys` MUST WARN
  when `.env` sets a key the tool derives.
- REQ-006-21: The `env-file` check MUST WARN when `.env` is group- or
  world-readable, tracked by git, or not git-ignored; the mode check is
  skipped on a WSL `/mnt/<drive>` checkout.
- REQ-006-22: The `ports-free` check MUST check every host port the
  settings and features would publish, and for a busy one name what holds
  it: the platform from another folder (with the fix to stop it), another
  container, AirPlay on port 5000 on macOS, or a process, ignoring the
  platform's own containers.
- REQ-006-23: The `checkout-path` check MUST WARN about CRLF line endings in
  the shim, WSL 1, and a checkout on a Windows drive.

Later

- REQ-006-24: `doctor` MUST cover every `checks.md` id the step 4 plan lists
  as a check, grouping text output by area with a one-line summary per
  group. (planned: step 4)
- REQ-006-25: `doctor --agent <dir>`, inferred from the current folder
  inside an agent folder, MUST also run the agent-folder checks.
  (planned: step 4)
- REQ-006-26: When `up`, `restart` or `status --wait` fails, the last lines
  MUST name the likely cause and fix from the diagnose checks for that step.
  (planned: step 4)

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
