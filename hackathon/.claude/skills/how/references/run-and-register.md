# Run and register your agent

Facts as of `prometheus_core` `devel` 2026-10-31, after #310 and #322 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

## Start it

`make up` in the agent folder runs `docker compose up --build -d` and joins
`prometheus_platform_agent-network` (`agent_template/Makefile:71-73`); without the network it
stops with "The Prometheus Platform must be launched first…". The build needs a committed `uv.lock`
(`uv add <pkg>`, then commit it with `pyproject.toml`; `agent-lockfile`). The image holds the code and the
card (`agent_template/Dockerfile:46-49`), and Compose reads `environment:` only on create: after
any change, run `make up`, not a restart. `make logs` never ends; use `docker compose -p <project> logs --no-log-prefix`. The agent exits at
startup with "Invalid required DeepLynx configuration: …" without the `DEEPLYNX_*` values (`deeplynx-env`).

## Registration and the route key

At startup the agent POSTs its card, URL, and `static_headers` (`Bearer <AGENT_SECRET>`) with the backend, using
`LITELLM_MASTER_KEY` as the token (the SDK's legacy name; compose sets it to `${AGENT_SECRET}`)
to `{REGISTRY_URL}/v1/agents` (`sdk/prometheus_api/agent/registry.py`, `AgentRegistryClient.register_once_async`;
deck 04, appendix). The POST replaces the entry of the same name, so there is no delete first. `REGISTRY_URL` is `http://backend:8000` in
Docker, `http://prometheus.host.internal:8600` in external mode, `http://localhost:8600` on the host. The log
says `Registered '<route key>' with LiteLLM at http://backend:8000` (old wording, same backend).

- **The route key** is the card `name` in lowercase, spaces changed to hyphens
  (`AgentRegistryClient.agent_name`): "Hello Max Agent" → `hello-max-agent`. A second agent with
  the same route key replaces the first one's entry.
- **Retries**: 2 s, doubled, at most 30 s, 11 attempts, then "Continuing without registration"
  (`AgentRegistryClient.register_with_retries_async`). Verify with `agent-registered-log` and `registry-agents` (`checks.md`).
- **Re-registration checks** (SDK, `AgentRegistryClient.keep_registered_async`): after startup the agent
  checks every `REGISTRY_CHECK_INTERVAL_SECONDS` (default 5, `0` off) that `/v1/agents` still lists it, and
  registers again if not. This also covers startup retries that ran out. An agent that overrides
  `register_with_registry_async` is not re-registered (it logs a WARNING). Whether an agent has the checks
  depends on its base image: the platform's agents use the pin in `platform/Makefile`
  (`PROMETHEUS_API_BASE_IMAGE_HASH`), a template agent defaults to `latest`, and `LOCAL_SDK=true` uses the
  local SDK. To tell, look for the INFO line "Checking the registry still lists this agent every 5s" in its log (`agent-registered-log`);
  without it, the agent registers only at startup.

## Discovery: how the orchestrator finds you

The `client-agent` reads `backend:8000/v1/agents`, fetches your full card from your URL first (then
the registry copy, `client-agent/tool_discovery.py:133-145`), and makes one tool per skill. It calls
`POST http://backend:8000/a2a/<route key>` with `A2A-Version: 1.0`; the backend forwards with your
`static_headers`, for up to 900 s. The cards
that the LLM sees refresh every 60 s (`capability_cache.py:96`); the dispatch tools every 300 s
and once on an unknown skill (`orchestrator/runtime.py:209-217`). `discovery-refresh` renews both.

## What to run after a change

| what changed | run |
|---|---|
| code, card, `pyproject.toml`, `Dockerfile`, compose, or the agent `.env` | `make up` in the agent folder, then `discovery-refresh` |
| the platform restarted (it empties the registry: `clear-agent-registry`) | If the agent logs "Checking the registry still lists this agent every", wait about 5 s, check `registry-agents`, then `discovery-refresh` (the client-agent's card cache can lag up to 60 s). Otherwise, or if it's still missing: `docker compose -p <project> restart <service>`, or `make up` after a `make down` |
| The restart fails: "network … not found" | `make down`, then `make up` |
| any of these, before a chat test | a fresh chat conversation (deck 04, slide 18) |

## Without the platform: the debug route

Run `AGENT_SECRET=dev AGENT_SECRET_REQUIRED=false USER_IDENTITY_REQUIRED=false PROMETHEUS_TASK_STORE=memory python agent.py`
in the venv, then `curl -s -X POST localhost:8000/api/chat -H "Content-Type: application/json" -d '{"params": {"skill_id": "<id>", "person_name": "Marie Curie"}, "conversation_id": "conv-1"}'`.
It runs `_execute` in-process (`agent/debug_routes.py:144-185`; deck 04, A18). On the host, a
`.env` in the folder wins over the environment (`llm_client/config.py:76-87`).

## A2A errors

A real call: `POST /`, `A2A-Version: 1.0`, method `SendMessage`, inputs as JSON text in
`parts[0].text`, and `metadata.skillId` (deck 04, A19).

| error | cause |
|---|---|
| `-32601` Method not found | the v0.3 method `message/send`; v1 uses `SendMessage` |
| `-32009` "A2A version '0.3' is not supported…" | no `A2A-Version: 1.0` header |
| `-32603` with "No 'userToken' found…" | `USER_IDENTITY_REQUIRED=true` and no user token |
| `-32004` "Streaming is not supported by the agent" | `SendStreamingMessage` to a card with `"streaming": false` |
| HTTP 401 | a missing or wrong bearer token (`AGENT_SECRET`) |
