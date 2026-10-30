# 6 (follow-on): Fix doc problems that predate this work

> **Status: Not started**

Found while reviewing the docs for this plan. Not caused by platformctl.
Fixed separately, before this plan, and not part of it:

- the hackathon material's container names after `container_name` was
  removed (`docker exec agent-valkey`, `docker restart <agent>`, the skills'
  `allowed-tools`): a standalone fix before the hackathon;
- `agent-template/setup_agent.py` copying the local DeepLynx server's own
  secrets into agent `.env` files: a standalone fix.

## Work

- `make clear-litellm-db` is documented but doesn't exist
  (`platform/README.md`, `platform/CLAUDE.md`). It was replaced by
  `clear-agent-registry` (see `sdk/docs/agent/AGENT_MIGRATIONS.md:31`);
  with platformctl it's `./platformctl reset registry`.
- `platform/CLAUDE.md` still describes podman, the LiteLLM proxy and
  `scripts/generate-agents-compose.sh`, which are gone, and says launches
  clear LiteLLM's Postgres volume.
- `troubleshooting.md` lists `[ERROR] .env does not exist.`, which nothing
  prints any more (`config init` creates the file).
- The hackathon KB (`.claude/skills/how/references/artifacts.md`, "Local
  DeepLynx", and deck 03 slides 18-20) teaches cloning and building DeepLynx
  by hand, plus browser steps to create a project and key and copy them into
  `.env`. `LOCAL_DEEPLYNX=true` with `./platformctl deeplynx setup` does all
  of that from published images. Replace the manual steps.

`build-plain`'s undefined `$(CONTAINER_RUNTIME)` is fixed in step 3a.

Use the `./platformctl` commands in every fix. Hackathon changes wait for
the end of the freeze; rebuild the decks in a separate last commit.

Line numbers are from 2026-10-30; search again before editing.

## Replaces

- The hackathon's manual DeepLynx clone, build and browser steps:
  `LOCAL_DEEPLYNX=true` with `deeplynx setup`.

## Breaking changes

None.

## Review

Before merging, run the reviewers in `reviews.md` for this step: user, agent developer, AI skills.
Record each finding in the PR as fixed, deferred or rejected.
