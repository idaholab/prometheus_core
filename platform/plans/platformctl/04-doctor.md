# 4: Full doctor, including agent folders

> **Status: Not started**

## Goal

`doctor` covers the common problems in the hackathon knowledge base
(`hackathon/.claude/skills/how/references/checks.md`, `troubleshooting.md`)
for the platform and for a developer's own agent folder, and the start
commands use it to explain failures. Take the checks from those docs, not
their commands: containers are found by service and label.

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
  becomes "Run: `./platformctl doctor <id>`" (with `--agent <dir>` for the
  agent checks). The `diagnose` skill's checklist runs
  `./platformctl doctor --json` and keeps only the manual checks above, with
  a fallback to the old one-liners when the clone's `--version` predates
  `doctor`'s checks. Its `allowed-tools` gain the `doctor` command.
- Hackathon decks: the homework and troubleshooting slides (deck 01, deck 03
  A18-A21) point to `./platformctl doctor`. Rebuild the decks in a separate
  last commit.

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

## Done when

- Every id in `checks.md` is a `doctor` check or in the "Manual" column with
  its reason.
