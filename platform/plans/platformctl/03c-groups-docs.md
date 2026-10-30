# 3c: Command groups, per-service up, and the switch of docs, slides and CI

> **Status: Not started**

Lands after 3b. After this, every command the hackathon material uses
exists, so the slides, skills and knowledge base switch in one go, with no
mixed `make`/`./platformctl` blocks.

## Goal

Add the remaining everyday commands, and switch every doc, slide, skill and
CI job to `./platformctl`.

## Work

- **`up <service...>`**: build and recreate only those services, then wait
  for them ("I changed the backend"). Also lets CI start only what a test
  needs.
- **`agents list`** (agent, included, why) and `agents list --registered`
  (route key, card URL, skill ids; flags duplicate route keys and skill ids;
  `--json`; never prints `AGENT_SECRET`).
- **`agents refresh`** (the client-agent's `/discovery/refresh`).
- **`compose -- <args>`** (refuses `config`/`convert` unless
  `--no-interpolate` without `--environment`; prints "output is not
  redacted" on stderr every run, and its help says so) and
  **`compose --print`** (only `-f` and `--profile`).
- **`logs --since`** (the `diagnose` skill's turn tracing needs it).
- The hackathon skills' **`allowed-tools`** lists switch to the new
  commands (`Bash(cd <platform> && ./platformctl agents refresh)` and so
  on).

## Output

- `agents list`: a table; `--registered` marks duplicates and which agent
  is yours.
- `agents refresh`: how many tools the client-agent now has, and yours.
- `compose --print`: the command, ready to paste.

## Replaces

- The registry and discovery one-liners in the docs and skills
  (`registry-agents`, `registry-details`, `discovery-refresh`):
  `agents list --registered`, `agents refresh`.
- `docker compose -p prometheus_platform restart|logs|exec <service>` in
  the hackathon material (from the container-name fix before the event):
  `./platformctl restart|logs|compose -- exec <service>`.
- The CI card check's inline curl and Python (`agent-template: platform`):
  `agents list --registered --json`.

## Docs and slides

- **User guide:** `agents.md` (`agents list --registered`, `agents refresh`,
  "why isn't my agent called?"), `compose.md` (`compose --print`),
  `everyday.md` (`up <service>`); the remaining `from-make.md` rows.
- Switch every doc to the new commands (`./platformctl up`, `restart`,
  `down`, `logs`, `status`, `reset ...`, `agents ...`, `compose --`), and
  simplify where the tool now does the work:
  - `platform/README.md`, `platform/tests/README.md`, root `README.md`,
    `CONTRIBUTING.md`, `docs/docs/` (getting started, local DeepLynx, adding
    agents), `agent-template/README.md` and `TUTORIAL.md` where they start
    the platform.
- **Hackathon** (after the freeze): the knowledge base, skills and slides
  switch together.
  - Skills check `./platformctl --version --json` and fall back to the old
    commands when it's missing (a participant's clone can be older).
  - "Restart your agent after every platform restart" goes away from
    `run-and-register.md`, `troubleshooting.md`, `conventions.md` and the
    `diagnose` skill.
  - The registry and discovery one-liners become `agents list --registered`
    and `agents refresh`.
  - The reset ladder uses `reset registry|users|data` and `down --volumes`.
  - Deck 03: `config init` with its new questions replaces the
    `echo "LOCAL_SDK=true" >> .env` step and its callout; the
    "**Every `make up` or `make restart` empties the agent registry ...
    restart it afterwards**" callout becomes one line saying the tool
    re-registers your agent. Decks 01, 04 and 05: the same command changes.
  - `make DEBUG_AGENTS=true up` (deck 03) becomes
    `./platformctl up --set DEBUG_AGENTS=true`.
  - The hackathon `CLAUDE.md` rule 3 and `conventions.md` add
    `./platformctl compose -- config` and `compose -- exec` to the commands
    never run to read a value, pointing to `config show --json`.
  - Rebuild the decks in a separate last commit.

## Breaking changes

None beyond 3a and 3b.

## Tests

- **Unit:** the new commands at 100%; duplicate detection; `compose --`
  refusals; `compose --print` never contains a value; the secrets canary.
- **Docs test** (from step 1, now with content): every `./platformctl` line
  in the user guide, slides, skills and agent-template docs parses with the
  real parser, and every check id cited exists.
- **Live:** `up backend` recreates only the backend; `agents list
  --registered` and `agents refresh` against the minimal project; the
  `compose --print` command run by hand.

## CI

- `agent-template: platform` follows the updated `TUTORIAL.md`, as its
  header comment requires, and asserts with `agents list --registered
  --json`.
- Optional: a fast infra-integration job with `up admin-db redis backend`
  for `test_integration_{backend,postgres,redis}.py`, split off
  `platform: up`.

## Review

Before merging, run the reviewers in `reviews.md` for this step: all eight.
Record each finding in the PR as fixed, deferred or rejected.

## Done when

- No doc, slide or skill teaches a platform `make` command or a raw
  `docker` command that has a platformctl equivalent.
- The hackathon skills' `allowed-tools` match the commands they run.
