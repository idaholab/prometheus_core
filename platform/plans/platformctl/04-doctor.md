# 4: Full doctor, including agent folders

> **Status: Not started**

## Goal

`doctor` covers the common problems in the hackathon knowledge base
(`hackathon/.claude/skills/how/references/checks.md`, `troubleshooting.md`)
for the platform and for a developer's own agent folder, and the start
commands use it to explain failures. Take the checks from those docs, not
their commands: containers are found by service and label.

## Requirements

This step satisfies the requirements tagged `(planned: step 4)` in
[`build/specs/`](../../../build/specs/000-index.md). They are drafts: change
them in this step's PR if the work shows they're wrong, and add any that are
missing. The PR removes each tag and cites the ID from the test that proves
it. The individual checks stay in the table below, not in the spec, so a
new check needs no spec change; REQ-006-29 ties the two together.

- [001 Using the CLI](../../../build/specs/001-using-the-cli.md): REQ-001-26
  (every failure ends with the fix and the check to run)
- [006 Doctor](../../../build/specs/006-doctor.md): REQ-006-24 to
  REQ-006-26, REQ-006-29 to REQ-006-36, BEH-006-01, BEH-006-02 (every
  `checks.md` id covered or manual, grouped output, `--agent`, the "why
  isn't it called?" checks, evidence from logs, hints after a failed start,
  what `--json` says it checked, fixes an assistant can act on)

## Every `checks.md` id

Each id is either a `doctor` check (same id) or stays manual, with the
reason. The PR updates this table if it finds more.

| Area | `doctor` | Manual, and why |
|---|---|---|
| Laptop | `tools`, `docker`, `base-image-pin`, `registry-login` (only without `LOCAL_SDK`), `platform-env`, `ports-free`, `platform-current` | `repo-access` (GitHub login, hackathon-only), `siblings` (hackathon layout; step 7 covers platform discovery), `personal-skills` (the Claude config folder) |
| Stack | `stack-ps`, `store` | |
| Registry | `platform-check`, `registry-auth`, `registry-agents`, `registry-details` | `llm-call` (needs a chat question) |
| Backend | `backend-health`, `backend-logs`, `chat-ui`, `admin-user`, `signing-key`, `identity-required-match`, `llm-key` | |
| DeepLynx | `deeplynx-env`, `deeplynx-backend`, `deeplynx-agent` | |
| Your agent | `agent-running`, `agent-registered-log`, `agent-logs`, `agent-env-sync`, `agent-base-image`, `agent-lockfile`, `llm-key-in-agent-env`, `llm-key-in-container`, `llm-profile-valid`, `dockerfile-copy`, `card-in-image`, `client-agent-reaches-agent` | `llm-flavors`, `llm-client-pattern` (greps of the user's own code; reported as hints, not checks) |
| Discovery | `discovery-refresh` (whether the client-agent cached your skills; `agents refresh` does the refresh) | |
| Activity | `activity` (open chat turns; also shown by `status`) | the turn tracing in `diagnose/trace-turn.md` (reads conversation history; uses `logs --since`) |

## Work

- **The checks above**, all applying to the compose target.
- **Agent checks** (`doctor --agent <dir>`, automatic inside an agent
  folder), grouped under **"Why isn't it called?"**: a stale image
  (`card-in-image`), the client-agent not reaching the agent, the
  client-agent not having cached its skills, duplicate route keys or skill
  ids, plus `.env` in sync with the platform's (by the explicit key list;
  `same`/`differs` only), quoted values and a non-default
  `COMPOSE_PROJECT_NAME`, a private key found in the agent's `.env`, and an
  agent without the agent label.
- **More platform checks:** keys missing from `.env`; a stale
  `.platform.env`; `.env` hiding an environment value or setting a derived
  key (by key name); `.env` mode and git-ignore; `prometheus.host.internal`
  reachable from a container (rootless Docker, ufw, a host service on
  127.0.0.1).
- **Hints on failure:** when `up`, `restart` or `status --wait` fails, run
  the `diagnose` checks for the step that failed and print the likely cause
  and fix.
- **`--json`** per the JSON contract, with `fix_kind` and
  `skipped_because` per check, for the hackathon `/diagnose` skill. Evidence
  from logs is the matched error class, never the line.
- **Options:** `--tag`, `--list`, check ids as arguments.
- Keep the agent checks in their own modules, independent of the platform
  folder, so step 7 can reuse them.

## Output

- `doctor`: grouped by area (Laptop, Platform, Registry, DeepLynx, Your
  agent), with a one-line summary per group, so a passing run is short and a
  failing one points at the group to look at.
- Failure hints: when `up`, `restart` or `status --wait` fails, the last
  lines name the likely cause and the fix, from the checks for that step.

## Replaces

- The hackathon `checks.md` shell one-liners for every check in the table
  above. Those needed care not to print secrets (`set -a; source .env`).
- The `activity` check before a restart: `restart` warns itself (3b).
- The `diagnose` skill's item-by-item Bash checks: one `doctor --json` run,
  plus the manual ones in the table.

## Docs and slides

- **User guide:** `troubleshooting.md` grows into "something's wrong:
  run `./platformctl doctor`", with the common problems and what `doctor`
  says for each. `agents.md` gets `doctor --agent` and "why isn't it
  called?".
- `platform/README.md`: its troubleshooting points to the user guide.
- Hackathon knowledge base: in `checks.md`, every check `doctor` now covers
  becomes "Run: `./platformctl doctor <id> --agent <dir>`", with the old
  one-liner kept under a "Before platformctl" line in the same entry, for
  clones whose `--version --json` lacks `doctor.checks.v1`. The `diagnose`
  skill's checklist runs `./platformctl doctor --json --agent <dir>` and
  keeps only the manual checks above. Its `allowed-tools` gain the `doctor`
  command (by wildcard). `agent-logs` is marked "hint + raw logs": the
  evidence is only the error class, so a traceback still needs
  `logs --since`, and the "your code can log values: read before you
  quote" rule stays.
- Hackathon decks: the homework and troubleshooting slides (deck 01, deck 03
  A18-A21) point to `./platformctl doctor`. Rebuild the decks in a separate
  last commit.

## What changes for you

- **Commands:** `./platformctl doctor` now covers the hackathon checks;
  failed starts end with the likely cause.
- **Files created:** none (`doctor` only reads).
- **First run:** nothing.
- **Roll back:** revert the PR.

## Breaking changes

None. `doctor` only reads, and the new warnings don't change what any
command does. The `--json` schema is versioned (`schema_version` 1).

## Tests

- **Unit:** each check passing, failing and skipped (its dependency failed),
  from canned command output; the failure hints for each step of `up`; the
  JSON golden files; the secrets canary for every check's evidence.
- **Live:** `doctor` against the minimal compose project, and against an
  agent folder generated by `agent-template/setup_agent.py` in `tmp_path`.
- **Docs test:** every check id the skills cite exists in `doctor --list`
  or is listed as manual.

## From the step 1 review

Findings the step 1 review deferred to here. "Checked" means the review's author reproduced it;
"reported" means a reviewer found it and nobody has reproduced it yet, so reproduce it first.

- **Five step 1 checks are not in `checks.md`** (checked: 0 matches for each): `build-cache-store`,
  `env-hides-environment`, `env-derived-keys`, `env-file` and `checkout-path`. Add them to the
  table above, and to `checks.md` when the hackathon freeze lifts. Step 1 promised a test that
  checks the ids the skills cite against `doctor --list`; the docs test below is that test, so it
  must pass over these five too. Also compare each check's tags and fix kind with `checks.md`
  (`ports-free` is `preflight,diagnose` in the tool; the reviewer read `checks.md` as `diagnose`
  only).
- **Fix text that says how, and for whom** (reported). The `platform-env` fix says `make init-env`
  (a raw Make target that prompts in a terminal): tell an assistant to ask the user first. The
  rootless branch of the daemon-down check tests `info.rootless`, which is always false when
  `docker info` failed, so "rootless" is never named.
- **`doctor --json` should say what it checked** (reported): add the selected check ids and the
  target to the object, since a skill otherwise has to call `--version --json` first.
- **Timeouts** (reported): the port probe and the Docker calls have timeouts of 0.3 s, 10 s and 30
  s and no overall limit; a hung daemon can take up to a minute per call. Add `--timeout`, or
  document the worst case for assistants.

## Review

Before merging, run `/review-panel` on the PR (see `reviews.md`) with these reviewers: all eight.

Ask them to look at:

- **Technical:** that every `checks.md` id is a `doctor` check or manual with a reason, as the
  table says; the agent checks in their own modules, independent of the platform folder (step 7
  reuses them); the hints printed when `up` fails.
- **CI and tests:** a test that the ids the skills cite exist in `doctor --list` (step 1 promised
  it and only some ids matched); each check passing, failing and skipped against recorded output.
- **Security:** evidence from logs as the matched error class, never the line; a private key found
  in an agent's `.env` named but not printed; `.env` sync reported as `same` or `differs` only.
- **AI skills:** `--json` per check with `fix_kind` and `skipped_because`; the `/diagnose` skill
  using them; how `ok`, `counts.fail` and the exit code relate.
- **Linux/WSL:** `prometheus.host.internal` from a container (rootless Docker, ufw); the `tools`
  and `registry-login` checks on a distro.
- **User and agent developer:** the "Why isn't it called?" group, in words they would act on.
- **Rollout:** a stale `.platform.env`; keys missing from an existing `.env`.

## Done when

- Every id in `checks.md` is a `doctor` check or in the "Manual" column with
  its reason.
