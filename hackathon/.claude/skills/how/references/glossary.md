# Glossary

Facts as of `prometheus_core` `devel` 2026-10-31, after #310 and #322 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

- **A2A.** Agent-to-Agent protocol 1.0: JSON-RPC `SendMessage`, `SendStreamingMessage` on `POST /`. Old `message/send` fails with `-32601`.
- **Agent.** A `PrometheusAgent` subclass that does skills. You write `_execute(params, context, event_queue)` (`agent-code.md`).
- **Agent card.** `agent_card.json`: name, description, capabilities, skills. Served at `GET /api/agent-card` (`card.md`).
- **Artifact.** A file or data result with an `artifact_id`, in the conversation's catalog (7 days). Pass ids, not data.
- **`ask_user`.** The orchestrator's tool for an open question; the turn ends `needs_info`.
- **Background task.** Work after the turn ends, from `declare_long_running`; `/tasks` shows it (`long-running.md`).
- **Base image.** `prometheus_api:local` with `LOCAL_SDK=true` (else `containers.github.inl.gov/genesis/prometheus_api:<tag>`). It holds the SDK (`environment.md`).
- **`contextId`.** The conversation id: `context.context_id` in your code.
- **Context state.** Per-agent, per-conversation JSON: `save_context_state`, `load_context_state`; 24 hours.
- **DeepLynx.** INL's data store for uploads, result files (`deeplynx://...`), and an execution record per call. No DeepLynx, no agent start.
- **Discovery.** The client-agent reads the registry, fetches each card, and caches it 60 s (`run-and-register.md`).
- **Flavor.** The LLM kind you ask for: `default`, `small`, `medium`, `large`, `vision`, `embedding` (`llm.md`).
- **`inputSchema`.** A skill's parameters as JSON Schema; the LLM gets it without `x_*` keys.
- **Input-required.** `send_input_required` pauses the task; `_execute` runs again with the answers merged into `params` (`get_input_sources` says who gave each).
- **Gateway.** The backend forwards each A2A call at `/a2a/<route key>` to the agent with `Bearer <AGENT_SECRET>`. There is no LiteLLM.
- **`LLMClient`.** The LLM interface: `self.llm_client(context)`; errors subclass `LLMClientError` (`llm.md`).
- **Secrets.** `AGENT_SECRET`: the token for the registry, the gateway, and each agent (the SDK reads it as `LITELLM_MASTER_KEY`, which compose sets to `${AGENT_SECRET}`); `LLM_API_KEY` for the provider.
- **Orchestrator.** The `client-agent`: an LLM loop that calls skills and chains the results.
- **Pin / profile.** The `prometheus_api` commit the platform builds from (`environment.md`); `LLM_CONFIG_PROFILE` maps flavors to models (required, no default).
- **Registry.** The backend's `/v1/agents` (in Valkey). Agents register at startup; a platform `make up` or `make restart` empties it. An agent on a base image with the SDK keep-alive registers again within about 5 s (`REGISTRY_CHECK_INTERVAL_SECONDS`); an older one needs a restart (`run-and-register.md`).
- **`requires_approval`.** A skill field: the user approves first; the turn ends `plan_ready`.
- **Route key.** The card name, lowercase, spaces to hyphens. A second agent with the same key replaces the first.
- **Signing key.** The RS256 key for each turn's `userToken`. The backend creates and activates it; Admin › Signing Keys rotates it.
- **Skill / skill id.** One thing an agent does; one tool. The id: `[a-zA-Z0-9_-]`, at most 64, unique; it arrives as `params["skill_id"]`.
- **Status update.** A `send_status_update` line; it shows live only with `capabilities.streaming: true`.
- **`usage_notes`.** Shown to the LLM as `Usage: <usage_notes>`: when to use the skill, and when not.
- **Valkey.** The state store: service `redis`, container `prometheus_platform-redis-1`, port 6379.
- **Workflow.** A YAML template that chains skills; a `workflow_*` tool and a slash command (`workflows.md`).
- **`x_artifact_ref`, `x_input_source: runtime`.** Marks on a property: an artifact id; a value that another skill makes.
