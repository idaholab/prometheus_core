# Stale docs: what older docs say, and what the code does now

Facts as of `prometheus_core` `devel` 2026-10-31, after #310 and #322 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Trust the code, and tell a mentor (deck 01, slide 12 and A18-A19; deck 04, A3).

| you may read | the code now |
|---|---|
| A Chainlit UI on :8500 | React on :5150, FastAPI backend on :8600 |
| A2A `message/send`, `params.context.skillId` | `SendMessage`, `message.metadata.skillId` (A2A 1.0); `message/send` fails with `-32601` |
| `process_analysis()` | `_execute(params, context, event_queue)` (`prometheus_api/prometheus_api/agent/base.py:1417`) |
| `request_user_approval(...)` | Does not exist: `"requires_approval": true`, or `send_input_required` |
| Log in as `prometheus` / `prometheus` | A setup wizard makes the first admin |
| Base image from `mooseharbor`, pinned in compose | From `containers.github.inl.gov`, pinned in the platform `Makefile:22` |
| `PROMETHEUS_DEBUG`, `planner.py`, the pin `2b3dbcf` (v0.8.0) | `DEBUG_AGENTS=true`; `orchestrator/agent_loop.py`; the pin `95c32b5` |
| A workflow YAML with no `description` | `description` is required (`workflow_library/schema.py:75`) |
| LiteLLM on `:9977`, `LITELLM_MASTER_KEY`, `litellm_config.yaml`, "Admin › Signing Keys → generate" | The backend on `:8600` is the registry and gateway (`Bearer $AGENT_SECRET`); no LLM proxy; the signing key is automatic |
| `get_provided_inputs`, `MissingInput(sensitive=…)`, `with_api_key(LITELLM_MASTER_KEY)` | answers in `params`; no `sensitive`; plain `self.llm_client(context)` |
| `docker exec agent-valkey` / `docker restart <agent>` (fixed container names) | `docker compose -p prometheus_platform exec -T redis` / `docker compose -p <project> restart <service>` (no `container_name` since #310; `conventions.md`) |
| `setup_agent.py --help` shows arguments | `main()` ignores them; it is interactive only (`setup_agent.py:389-400`) |
| Host run with `AGENT_SECRET_REQUIRED=false` only | Also `USER_IDENTITY_REQUIRED=false`, else "No 'userToken' found" |
| "Your agent registers only at startup: restart it after a platform `make up`" | True on the pinned base image (`platform/Makefile`). With the re-registration checks (#322; the log says "Checking the registry still lists this agent every") a running agent registers again within about 5 s (`REGISTRY_CHECK_INTERVAL_SECONDS`); restart only if it does not |

Old text remains in the platform `docs/docs/` pages, the template `TUTORIAL.md` and `README.md`, and
`prometheus_api/docs/agent/MULTI_USER.md`. "Planner tool" means "orchestrator tool".

## The client-agent log does not show the turn

Deck 03, A11 and deck 04, slide 19 say it does. It does not: the status lines go to Valkey and the UI
(`agents/client-agent/orchestrator/runtime.py:139-161`). The log shows discovery prints and errors.
Read the turn from Valkey, or run `/diagnose trace my last chat`.

## The `registry` profile

Old docs and the template before the fix default `LLM_CONFIG_PROFILE` to `registry`, which sent LLM calls to
`REGISTRY_URL`. That is now the backend's agent registry, not an LLM proxy: `make init-env` rejects it and
the platform compose stops while the profile is empty. Every other profile defines all flavors. More in `llm.md`.
