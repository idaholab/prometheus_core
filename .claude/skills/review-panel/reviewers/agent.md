### Agent

You own the agent side: the `client-agent` orchestrator (`platform/agents/client-agent/`), the
specialist agents in `platform/agents/`, and the `PrometheusAgent` base class and LLM client in
`sdk/prometheus_api/`. Review the change for how it behaves inside a real chat turn:

1. **Orchestration:** in `orchestrator/agent_loop.py` and `chat_flow.py`, can the tool-calling
   loop still end? Check the step limits, the repeated-call guards, and what happens when a tool
   fails or returns nothing. Are pauses (`needs_info`, `plan_ready`, `INPUT_REQUIRED`,
   `ask_user`) persisted and resumed correctly? Do artifact ids still flow through the tool
   results?
2. **Discovery and cards:** `tool_discovery.py` and `capability_cache.py` read LiteLLM
   `/v1/agents` and fall back to each agent's `/.well-known/agent.json`. Does the change work
   through both paths? Does an `agent_card.json` change still give the orchestrator a skill
   description it will pick correctly, and does it avoid stealing calls from other agents?
3. **The A2A and SDK contract:** the task lifecycle (working → completed/failed/input-required),
   status updates, artifacts emitted on the event queue vs. the auto-wrapped `process_analysis()`
   dict, `contextId` state, and the backend ↔ client-agent contract in `prometheus_api.contract`.
   Does an agent built on the previous base image still work?
4. **LLM use:** agents pick semantic flavors (`small`, `medium`, `large`, ...), not provider
   models, and deployment config must not override that. Check the prompts for injection from
   user input or tool results, and the cost of a turn (calls per turn, context size, retries).
   No secrets or user tokens should reach a prompt or a log.
5. **Failure in a turn:** what the user sees when an agent times out, crashes, is unregistered,
   or returns malformed output. Is the turn left hanging in Valkey?
6. **Checks:** unless the `platform: agent` and `sdk: python` CI jobs passed on this commit,
   run `uv run pytest` in each touched agent directory and in `sdk/` (unit only:
   `-m "not integration"`). If Docker is available, start a throwaway stack and run one chat
   turn that goes through the change. Say which behavior changed without a test, and name the
   simplest test that would cover it.

Read: the diff; `platform/CLAUDE.md` ("Request flow", "Why LiteLLM is in the loop", "Agents");
`platform/docs/docs/dev-docs/agent-loop-orchestration.md`; `sdk/CLAUDE.md`; the touched agents'
`agent.py` and `agent_card.json`.
