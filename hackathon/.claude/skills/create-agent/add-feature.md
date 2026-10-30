# Add a feature to the agent

Add one platform feature to the user's agent: teach it, write the plumbing, test, and run. The
argument, when given, names the feature. Agent code picks LLM flavors, imports no provider SDK,
hard-codes no model ID, and calls `self.llm_client(context)` with no key swap.

## 1. Find the agent and the feature

1. Find the agent ("Find your agent" in `conventions.md`). With none, run `new-agent.md` first.
   `<project>` and `<service>` as in "Find your agent". Read `agent.py`,
   `agent_card.json`, `pyproject.toml`, `Dockerfile`, and `tests/`.
2. Match the argument to a row below. Else ask (header `Group`): "Files and artifacts", "Talk to
   the user", "Call an LLM", "Structure and long work"; then (header `Pattern`) its rows. With
   more than one skill, ask which skill gets it (header `Skill`), except for a second skill or a
   workflow.

Paths are below `<platform>`; when the lines moved, find them with `grep -n <helper>`. Each row:
the KB file, the reference, and what changes in the card, the code, and the chat.

| pattern | KB | reference | card | code | chat |
|---|---|---|---|---|---|
| Read an upload | `artifacts.md` | `agents/debug-agents/artifact-debug-agent/agent.py:206-227` (copy only its `FileNotFoundError` branch); card `agent_card.json:64-68` | a string input with `"x_artifact_ref": "single"` | `get_artifact_file_path(...)` gives a local `Path` | the user uploads; the orchestrator passes the artifact id |
| Publish a JSON table | `artifacts.md` | `agents/debug-agents/corrosion-agent/agent.py:234-242`; a custom viewer: `thermal-agent/agent.py:301-309` | nothing | `send_json_artifact(..., catalog_artifact=True)`; return the id | a JSON tree; `/artifacts` lists it |
| Publish a PNG | `artifacts.md` | `artifact-debug-agent/agent.py:262-302`; storage config `:30-35` | nothing | render in a thread, `send_deeplynx_artifact(..., mime_type="image/png")` | the image viewer |
| Status updates | `agent-code.md` | `artifact-debug-agent/agent.py:148-158`; card `:5-8` | `capabilities.streaming: true` | `send_status_update`, `send_conversation_message` | live progress lines |
| Ask the user | `asking-the-user.md` | `corrosion-agent/agent.py:112-168` | the asked input stays optional | `send_input_required`, `return {}`; on the resume the answer is in `params` | a form, then a second run |
| Approval | `asking-the-user.md` | `corrosion-agent/agent_card.json:15` | `"requires_approval": true` | nothing | Approve and Reject |
| Call an LLM | `llm.md` | `agents/synthesis-agent/agent.py:61-69` only (deck 04, A6 forbids its blanket `except`) | nothing | `async with self.llm_client(context)`, catch `LLMProviderError` | the answer text |
| Structured answer | `llm.md` | deck 04, slide 16; `prometheus_api/llm_client/tools.py:335-352` | nothing | `ToolDefinition.from_pydantic`, `acall_tool(..., model=...)` | a reliable value |
| Long work | `long-running.md` | `debug-agents/thread-pattern-agent/agent.py:57-207`; `asyncio.to_thread`: `osti-research-agent/agent.py:1081` | `capabilities.streaming: true` | `asyncio.to_thread`, or `PrometheusWorker` + `run_worker` + `declare_long_running` | progress; `/tasks` |
| A second skill | `card.md`, `agent-code.md` | `material-data-agent/agent.py:198-258`; `artifact-debug-agent/agent.py:429-453` (return an error dict for an unknown skill) | a new prefixed skill entry | a `skill_id` dispatch | a new tool |
| A workflow | `workflows.md` | `artifact-debug-agent/workflows/patriotic_usa_png.yaml` | nothing (merged at startup) | nothing | a `workflow_*` tool; `/workflows` |

Read SDK code from the image:
`docker compose -p <project> exec -T <service> python -c "import inspect, prometheus_api.llm_client.tools as t; print(inspect.getsource(t.acall_tool))"`.
The debug agents run only with `make DEBUG_AGENTS=true up` in the platform; that empties the
registry, so ask first (header `Debug run`), and `make up` the agent again after it.

## 2. Teach and predict

1. Primer from the KB file (2-3 lines, with its deck and slide). Show the reference code (at most
   15 lines). Ask the check question: `artifacts` (file rows), `input-required` (ask the user),
   `card-interface` (a second skill).
2. Predict (headers `Card`, `Code`, `Chat`): the table answer plus two plausible wrong ones, in a
   random order. Then give the answers.

## 3. Settle the details

Find each fact yourself; ask only decisions: the input name (`<thing>_artifact_id`) and MIME
type, what to ask and save, which long-work tool (`long-running.md`), the new skill's id,
description, `usage_notes`, and inputs (`card.md`). Uploads and PNGs need DeepLynx:
`grep -c '^DEEPLYNX_KEY=.' <agent>/.env` and `grep -c '^DEEPLYNX_PROJECT_ID=.' <agent>/.env`.
On a 0, offer "## Local DeepLynx" of `artifacts.md` or `/diagnose check my laptop` first.

LLM rows: read the flavors first (`llm.md`). List them for the agent's profile:
`grep 'model_name:' <platform>/../sdk/prometheus_api/llm_configs/$(grep '^LLM_CONFIG_PROFILE=' <agent>/.env | tail -n 1 | cut -d= -f2).yaml`.
Pick one that exists. Teach `LLMAliasError` and `LLMProviderError` in two lines. Check the key
in the container:
`docker compose -p <project> exec -T <service> sh -c 'test -n "$<KEY>" && echo set || echo missing'`.

## 4. Write, test, run

1. Prepare diffs from the KB snippets: card fields, imports, helper calls, the dispatch, the
   return dict with ids, `# TODO:` hints for the domain logic. A new dependency:
   `uv add --no-sync <package>` then `uv sync --inexact` (never `prometheus_api`, `a2a-sdk`, or a
   provider SDK). A new module needs a `COPY` line in the `Dockerfile`.
2. Obey "Before a write": one question per file (headers such as `agent.py`, `Card`, `Tests`),
   "Accept", "Edit", "Skip". Then ask (header `Domain`): "I write it myself (Recommended)",
   "Write it for me", "Give me more hints".
3. Tests with the mocks of `testing.md`, `skill_id` in the params, both calls for input-required.
   `uv run pytest && uv run ruff check .` (`--fix` for import order).
4. Say that `make up` stops a running call of this agent. `make up`, wait for
   `docker compose -p <project> logs --no-log-prefix <service> 2>&1 | grep "Registered '" | tail -1`, then the discovery refresh.
   Give one chat prompt for a fresh conversation. Errors go to `/diagnose`; not called or wrong
   arguments go to `/diagnose trace my last chat`.
5. Sum up in three lines. Offer `/how explain <pattern>`, and another pattern.
