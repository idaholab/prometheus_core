# The platform: how Prometheus works

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Prometheus is a chat front door to specialist agents (deck 01, slide 7). An orchestrator picks the agents, the
order, and the files. You write one agent: a class with `_execute`, and a card.

## Services and ports

```text
Browser ─:5150─> frontend-dev ─/api/*─> backend (:8600) ─A2A SendStreamingMessage─> client-agent
client-agent ─POST backend:8000/a2a/<route key>─> backend gateway ─Bearer <AGENT_SECRET>─> your agent (:8000)
redis (:6379): conversations, status history, artifact catalog, sessions.  DeepLynx: files.
```

Source: `platform/docker-compose.yml`; deck 01, appendix. `client-agent` has no host port. The `backend` is also the
agent registry (`/v1/agents`, stored in Valkey under `prometheus:agent-registry`) and the A2A gateway
(`/a2a/<route key>`), both behind `Bearer <AGENT_SECRET>` (`backend/app/routers/agent_registry.py`). There is no
LiteLLM and no LLM proxy: agents call their provider directly (`llm.md`). Each platform `make up` or `make restart`
empties the registry (`clear-agent-registry`). `admin-db` holds users and signing keys; `redis` (container
`prometheus_platform-redis-1`) holds the state. All join `prometheus_platform_agent-network`, and so does your agent after
`make up`. Inside it, use service names (`http://backend:8000`, `redis://redis:6379`). `make up` waits until
every container is healthy (`/healthz`), then `make check` waits until every agent is registered.

## One chat turn

1. The browser sends `POST /api/chat/messages` and listens on `GET /api/events` (`backend/app/routers/chat.py:87`).
2. The backend sends A2A `SendStreamingMessage` to the client-agent: `contextId` is the conversation id, and
   `metadata.userToken` is an RS256 token made per turn (`backend/app/a2a_client.py:118-146`).
3. The orchestrator LLM sees the conversation, the artifact catalog, and each skill and workflow as a tool. It
   calls one, reads the result, and picks the next. It calls `POST http://backend:8000/a2a/<route key>`.
4. `_execute` runs. Status lines reach the UI only with `capabilities.streaming: true`. Outputs go into the
   artifact catalog; the backend adds a `render_hint`, and the UI picks a viewer.

The loop is `agents/client-agent/orchestrator/agent_loop.py`: one tool per skill (named by its id), one
`workflow_<id>` per workflow, and `ask_user` (`:307-333`). It uses the `medium` flavor (`:1276`), at most 12
LLM turns (`:67`), at most 6,000 characters per result (`:70`), and 900 s per call (`tool_discovery.py:515`).
Its prompt (`prompts/orchestrator_system.txt`) answers chat directly, prefers a matching `workflow_*`, says so
when no skill fits, and never invents a required value.

## How a turn ends

One `ChatStatus` per turn (`backend/app/contract.py:35`; `orchestrator/chat_flow.py:112-193`; deck 01, A11):

| status | when |
|---|---|
| `completed` | A reply after at least one tool call ("Response ready.") |
| `answer` | A reply with no tool call, a slash command, a rejected plan, or no skill fits |
| `needs_info` | A missing required input, `ask_user`, or an agent's input request (a form) |
| `plan_ready` | The next call has `requires_approval: true` |
| `backgrounded` | An agent called `declare_long_running`; `/tasks` shows it |
| `error` | A loop error, the 12-turn cap, or an exception |

The status history is the Valkey key `agent:status_history:<conversation id>`, kept 15 minutes
(`orchestrator/runtime.py:139-161`). The orchestrator writes the chat text; your output shows as artifacts.

## Chat commands and the reference agents

In the Prometheus chat: `/help`, `/agents` (your agent must be here), `/workflows`, `/artifacts`, `/tasks [id]`.
Each workflow is also a slash command (`orchestrator/debug_commands.py:16-24`).

Always on: `client-agent`, `form-filler-agent`, `synthesis-agent` (the best small LLM example);
`osti-research-agent` with `OPTIONAL_AGENTS=true`. `make DEBUG_AGENTS=true up` in the platform adds `agents/debug-agents/` (it empties the registry:
`make down` your agent first): `artifact-debug-agent` (a PNG through DeepLynx, JSON, a workflow: "Make an image
with the word Success"), `corrosion-agent` (input-required, answers merged into `params`, approval: "Corrosion analysis of
SS316"), `material-data-agent` (many skills), `thermal-agent` (a custom `json_type` viewer), and
`thread-pattern-agent` (`PrometheusWorker`, `declare_long_running`: "Run a background task").
