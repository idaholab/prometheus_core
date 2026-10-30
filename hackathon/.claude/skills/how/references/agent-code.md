# Agent code: the `_execute` contract

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

You write one class with one method, plus `agent_card.json` (deck 04, slides 2-3). The base class
`PrometheusAgent` (`prometheus_api/prometheus_api/agent/base.py:570`) gives the A2A server, the card, the
registration, auth, the task lifecycle, heartbeats, and the helpers (deck 04, A2). Short paths: `base.py` is in
`prometheus_core/sdk/prometheus_api/agent/`; `orchestrator/...` and `tool_discovery.py` (at the client-agent root) are in
`prometheus_core/platform/agents/client-agent/`; `agent_template/...` is in `prometheus_core/agent-template/`.

```python
from typing import Any

from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext


class HelloAgent(PrometheusAgent):
    async def _execute(
        self, params: dict[str, Any], context: RequestContext, event_queue: EventQueue
    ) -> dict[str, Any]:
        name = params.get("person_name")
        if not name:
            return {"status": "error", "error": "person_name is required"}
        return {"status": "success", "greeting": f"Hello, {name}!"}
```

## What arrives in `params`

| key | from | source |
|---|---|---|
| your `inputSchema` properties | the JSON that the orchestrator sent | `base.py:446-460` |
| `skill_id` | `message.metadata.skillId` | `base.py:462-469` |
| `user_id` | the verified token; `local` without one | `base.py:471-477` |
| `conversation_id`, `artifacts` | the client-agent adds them | `orchestrator/skills.py:95`, `orchestrator/agent_loop.py:879-884` |

- Answers to your own input request arrive merged into `params`; `self.get_input_sources(context)`
  says who supplied each value (`asking-the-user.md`).
- A test or a workflow can call you without a required field. Check every value you need.
- `str(context.context_id)` is the conversation id, the key for state.
- The base class logs only the sorted keys, never the values (`base.py:479`; REQ-009-03).

## Several skills: dispatch on `skill_id`

```python
handler = {"neutron_extract_table": self.extract, "neutron_plot_table": self.plot}.get(params.get("skill_id"))
if handler is None:
    return {"status": "error", "error": f"Unknown skill: {params.get('skill_id')}"}
return await handler(params, context, event_queue)
```

Example: `prometheus_platform/agents/debug-agents/material-data-agent` (deck 04, slide 3).

## Return a dict

- It becomes the `TASK_STATE_COMPLETED` text (`base.py:253-260`). Return ids and names, not the data
  (deck 04, slide 10; `card.md`, "Your result, as the LLM sees it").
- Never use the key `artifacts`: the client-agent puts your artifact list there
  (`tool_discovery.py:585-586`). `suggested_queries` gives up to 3 follow-up chips.

## Errors

| problem | do | result |
|---|---|---|
| the user or the input is wrong | `return {"status": "error", "error": "<what>"}` | the LLM reads it and can retry |
| the infrastructure is broken | let it raise | `TASK_STATE_FAILED`; `Error during execution` in your log |

The client-agent checks the `error` key, not `status`: always put a non-empty `error`
(`orchestrator/skills.py:150-159`). No blanket `try/except` (deck 04, A6).

## The helpers on `self`

`eq` is the `event_queue`. Lines are in `base.py`.

| helper | what | line | more in |
|---|---|---|---|
| `send_status_update(context, eq, message=...)` | a live progress line (needs `streaming: true`); always write `message=` | 1528 | - |
| `send_conversation_message(context, eq, message)` | a message that stays in the chat | 1876 | - |
| `send_json_artifact(...)`, `send_deeplynx_artifact(...)`, `get_artifact_file_path(...)` | artifacts | 1642, 1741, 1196 | `artifacts.md` |
| `send_input_required(...)`, `get_input_sources(...)`, `load_context_state` / `save_context_state` | ask the user, keep state | 1096, 1047, 1038 | `asking-the-user.md` |
| `declare_long_running(...)`, `run_worker(...)` | long or blocking work | 1551, 1592 | `long-running.md` |
| `llm_client(context, config=cfg)` | the async LLM client | 1000 | `llm.md` |

Import `MissingInput` and `PrometheusWorker` from `prometheus_api.agent`.

## The template files

- `pyproject.toml`: your dependencies only. Never add `prometheus_api`, `a2a-sdk`, `starlette`, or
  `uvicorn`: the base image has them (deck 04, A5). Commit `uv.lock` with it.
- `Dockerfile`: it copies only `agent.py`, `agent_card.json`, `prompts/`, and `workflows/`
  (`agent_template/Dockerfile:46-49`). Add a `COPY` line per new module, else `ModuleNotFoundError`.
- `Makefile`: `up`, `up-fg`, `down`, `logs`. `make logs` never ends; use `docker compose -p <project> logs --no-log-prefix <service>`.
- `docker-compose.yml`: the container gets only the variables that `environment:` lists.
