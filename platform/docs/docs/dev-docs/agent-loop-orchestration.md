# Client-Agent Orchestration as a Tool-Calling Loop

**Date:** 2026-09-30 (sections 2-3 revised 2026-10-27 for the ADK runtime)
**Status:** Implemented (replaces the compile-then-execute planner; runs on Google ADK)
**Scope:** `agents/client-agent/` — how a user turn becomes specialist skill invocations.

---

## 1. Problem

The client-agent planned every request *up front*, before any specialist ran, through a
chain of serial LLM calls:

| # | Stage | Module |
|---|-------|--------|
| 1 | Turn resolution (new task / repeat / discuss / clarify) | `planner.resolve_turn` |
| 2 | Capability-blind task decomposition | `planner.decompose_task` |
| 3 | Dependency assignment between operations | `planner.decompose_task` |
| 4 | Planning-tool loop (≤ 8 turns): select capabilities, map operation coverage, set steps, finalize | `planner.compile_plan_with_tools` |
| 5 | Schema-bound parameter extraction | `parameter_extraction.extract_parameters_with_schemas` |
| 6 | Capability-metadata parameter derivation | `parameters.resolve_params_via_capability_metadata` |
| 7 | Per-step parameter re-resolution at execution time | `execution._resolve_invocation_params` |

That is 6–12 serial LLM calls before the first specialist starts. The design also failed
on simple requests, for two structural reasons:

1. **Decomposition could not see the skills.** `task_decomposition_system.txt` told the
   model to split the request "without considering what tools or capabilities may be
   available". `planner_system.txt` then declared the operation list *immutable*. It also
   required each operation to map to exactly one skill. So "Create a PNG image with the
   word Popelnase" became one operation. No single skill produces a PNG with text, so the
   request was marked unsupported, even though `create_svg_artifact` →
   `convert_svg_to_png` does exactly that.
2. **The plan was fixed before any results existed.** Step *n+1*'s inputs are usually
   step *n*'s outputs, such as an artifact id. A plan compiled up front cannot bind them,
   which produced the `runtime_required_params`, `collect_chain_required_paths`, deferred
   paths, and "requires internal runtime inputs" fallbacks. Explicit chains like "…, then
   convert it to png" fell into those gaps.

## 2. Decision

Replace planning with a **single tool-calling agent**, the standard agent pattern. Since the
ADK runtime change, that agent is one Google ADK `LlmAgent` named `client_agent`. The
client-agent builds it per turn with `build_runner()` from `prometheus_api.adk`:

```
instruction (system prompt)  +  ADK session events  +  tools (one per skill, one per workflow template, ask_user)
      │
      ▼
  LlmAgent turn ──► function calls? ──no──► final answer (end of turn)
      ▲                   │ yes
      │                   ▼
      │      before_tool check → [approval or ask_user pause] → call_a2a_agent to the specialist
      │                   │
      └──── function responses (summary + artifact ids) appended to the session
```

The model sees every skill's description and input schema as a tool. It also sees
everything that has happened so far in the ADK session: user messages, earlier function
calls, and their results with artifact ids. It decides the next call with fully
parameterized arguments, *after* the previous call's result is known. Decomposition,
chaining, parameter extraction and data flow between steps all become ordinary
tool-calling behavior.

"Create a PNG image with the word Popelnase" becomes:

```
assistant → create_svg_artifact(word="Popelnase")
tool      → {"status": "succeeded", "artifacts": [{"artifact_id": "a1", "mime_type": "image/svg+xml", ...}]}
assistant → convert_svg_to_png(artifact_id="a1")
tool      → {"status": "succeeded", "artifacts": [{"artifact_id": "a2", "mime_type": "image/png", ...}]}
assistant → "Here is the PNG image with the word Popelnase."
```

The hand-written loop of the first version (`advance`, `_drive_batch`, `_run_call`) is
removed. ADK now owns the turn, the pauses, and the resume. The SDK spec
`sdk/specs/016-adk-runtime.md` defines `build_runner()` and its plugins.

## 3. Design

### 3.1 Modules

| Module | Role |
|--------|------|
| `orchestrator/agent_loop.py` | Policy and the turn: `build_tool_catalog`, the system prompt, argument checks (`_validation_problem`, `_missing_user_inputs`), result compaction (`_compact_result`), and `run_turn`, which runs or resumes one ADK invocation of `client_agent`. |
| `orchestrator/adk_tools.py` | The catalog as ADK tools: `a2a_skill_tool`, `workflow_tool`, the `ask_user` `LongRunningFunctionTool`, the `before_tool` callback, and `build_client_agent`. |
| `orchestrator/chat_flow.py` | Entry point: slash commands, state load/create, maps a `ConversationRequest` (query / answers / approval / rejection) onto a new or resumed ADK run, and a `TurnOutcome` onto a `ConversationResponse`. |
| `orchestrator/service.py` | The A2A agent: binds each request to an `AdkRun`, detaches long turns to the background, and resumes unfinished turns in `lifespan`. |
| `orchestrator/skills.py` | `invoke_skill` (A2A via LiteLLM, Task Graph tracking, streaming status, long-running detach); workflow steps call it. |
| `workflow_library/` | Loads and compiles the YAML templates. `to_adk_workflow` turns each compiled template into an ADK graph `Workflow`. |
| `prompts/orchestrator_system.txt` | The system prompt. |

Deleted: `planner.py`, `planner_models.py`, `orchestrator/planning_flow.py`,
`orchestrator/parameter_extraction.py`, `orchestrator/parameters.py`,
`orchestrator/execution.py`, the planning and extraction prompts,
`artifact_handling.collect_chain_required_paths` / `resolve_artifact_inputs`,
`workflow_library/matcher.py`, `workflow_library/executor.py` (`execute_workflow`), and the
`agent.py` monkeypatch compatibility layer.

### 3.2 Tools

`adk_tools.build_tools(catalog)` makes one ADK tool per `ToolSpec` of
`agent_loop.build_tool_catalog()`:

* **Skill tools** (`a2a_skill_tool(spec)`): one per registered capability
  (`CapabilityCache`). The name is the skill id, sanitized to `^[a-zA-Z0-9_-]{1,64}$`. The
  description is the skill description, usage notes, and "requires approval" when it
  applies. The function declaration is the spec's JSON schema, with:
  * vendor keywords (`x_*`, `x-*`) stripped, so the provider sees plain JSON Schema;
  * artifact-reference fields (`x_artifact_ref`) described as "artifact_id of an existing
    conversation artifact". The user is never asked for one on a form;
  * `artifacts` / `conversation_id` removed, because the tool attaches them.

  The tool calls `tool_discovery.call_a2a_agent`. That call adds the
  `prometheusParentExecutionRecordId` message metadata key, and it forwards an A2A cancel to
  the remote task when the call is cancelled.
* **Workflow tools** (`workflow_tool(spec, compiled)`): one per compiled template
  (`workflow_tool_name(id)`). Parameters are the template's `required_input_paths`, as flat
  properties keyed by dotted path. The tool runs the template's ADK `Workflow` as one call,
  see 3.6.
* **`ask_user`**: a `LongRunningFunctionTool`. Its arguments are a list of typed form fields.
  It returns `{"status": "pending", ...}` and pauses the run until the user answers.

A tool whose spec requires approval carries `approval_required = True`. The SDK approval
plugin turns its first call into an ADK `adk_request_confirmation` pause.

### 3.3 Call checks

The `before_tool` callback runs before each skill call. It normalizes the arguments to the
skill's input schema and runs `_validation_problem`: an unknown artifact id, a schema
violation (`jsonschema`), or a missing runtime input. A problem is the call's result, and
the model sees it and corrects the call; nothing is dispatched. A missing *user-input*
parameter (`_missing_user_inputs`) is also an error result. It tells the model to ask with
`ask_user` and then call again. The model is told never to invent those values.

A specialist that returns A2A `INPUT_REQUIRED` gives the tool result
`{"status": "input_required", "input_required": {...}}`. The model then decides the next
step, for example an `ask_user` form.

### 3.4 Pausing and resuming across turns

A pause is an ADK long-running call: an `adk_request_confirmation` call of the approval
plugin, or an `ask_user` call. `run_turn` collects the paused calls into
`TurnOutcome.pending_calls`, and sets `awaiting_approval` or `needs_input`. The conversation
record in Valkey (`conversation:{id}`) keeps `pending_calls`, `awaiting_approval`, `plan`,
`missing_info`, and the ids of the ADK run, `adk_session_id` and `adk_invocation_id`. The
ADK session itself is stored by the session service (`ADK_SESSION_DB_URL`).

The next request resumes the paused invocation with one function response per pending call:

| Incoming request | With pending calls |
|------------------|--------------------|
| `plan_approved` | `chat(plan_approved=True)` answers `adk_request_confirmation` with `{"confirmed": true}`. The approved call runs, and the run goes on. |
| `plan_rejected` | Every pending call is closed: the confirmation gets `{"confirmed": false}`, and `ask_user` gets `not_executed`. Reply: "Plan rejected…". |
| `followup_answers` | `ask_user` gets `{"status": "answered", "answers": {...}}`. |
| Free-text `query` | `ask_user` is answered with the text, and an approval is closed unconfirmed. When no `ask_user` was pending, the text then starts a new invocation. So "use 20 mm instead" while a plan waits for approval simply re-plans. |

Without pending calls, the query starts a new invocation. An explicit workflow selection
(`/workflow` slash command, catalog start endpoint) adds a hint to the user message that
names the workflow tool. The form inputs or the free-text arguments go into that hint, and
the model fills the workflow inputs.

**Resume after a restart.** A turn detached to the background records the run's
`invocation_id` and `adk_session_id` on its Task Graph root node (`TaskNode`). At startup,
`lifespan` lists the unfinished nodes that have an `invocation_id`
(`task_graph.list_resumable_nodes`). It resumes each one in the background with
`run_turn(..., message=None, invocation_id=node.invocation_id)`. A resume that pauses again
sets the node to `input-required`; a resume that fails sets it to `failed`.

### 3.4a Concurrent turns

A turn detached to the background keeps running while the user sends the next one, and
`conversation_store` merges stores by turn instead of overwriting (`merge_conversation`).
`conversation_history` and the stored `llm_messages` merge per turn: a store keeps the
entries of every other turn from the stored document, and takes this turn's entries from its
own copy. Unfinished `pending_calls` count as pending input in the newest-turn ownership
rule, so a newer turn that left no form or plan does not overwrite a late turn's open one. A
pause's `followup_questions` / `plan` history entry carries the reply text as `content`, so
artifacts produced before the pause are stamped on it (`stamp_turn_artifacts`).

### 3.5 What goes back to the model

A successful skill result is compact JSON (`_compact_result`):

```json
{"status": "succeeded",
 "summary": "<answer/message/report text, ≤ 2 000 chars>",
 "artifacts": [{"artifact_id": "...", "name": "...", "mime_type": "...", "description": "..."}],
 "result": "<remaining JSON payload, ≤ 6 000 chars>"}
```

A failed call, a failed check, or an unavailable capability is
`{"status": "failed", "error": "..."}`.

Artifacts produced by a call are merged into the session state `context.artifacts` right
away, so the next call's artifact references validate. The system prompt lists the
conversation's artifact catalog (id, name, mime type, description) and the newest
successful inputs of each skill (`recent_skill_inputs`) on every model call.

### 3.6 Workflow templates as ADK graphs

The templates stay YAML data. `compile_workflow` validates a template against the
capability metadata, as before. `to_adk_workflow(compiled, invoke_skill)` then builds one ADK
graph `Workflow`:

* one `FunctionNode` per step, which calls `invoke_skill` with the step's bound inputs
  (`binding.py`);
* one `Edge` per dependency, from `START` for a root step, and a `JoinNode` for a step with
  several predecessors;
* `sequential` also chains the steps in template order; `dag` and `parallel` run ready
  steps up to `max_concurrency` at once;
* under `fail_fast` a failed step stops the run; under `continue_with_partial` its
  dependents are `blocked` and the other steps go on;
* a step that needs input interrupts with a `RequestInput` and reruns with the answer;
* a `finish` node returns `step_statuses`, `step_results`, `errors`, `final_output`,
  `context_delta` and `success`.

The workflow tool runs it with `tool_context.run_node(...)`, so a workflow run is part of
the ADK invocation and resumes with it.

### 3.7 LLM client and bounds

* The model is `prometheus_model("medium", agent.llm_client(context))`, an ADK model whose
  every completion goes through `AsyncLLMClient`. Model flavor `medium` is hardcoded per
  platform convention.
* The turn ends when a model response has no function calls, or when a long-running call
  pauses the run.
* The compaction plugin bounds the request: the client-agent uses
  `CompactionPolicy(trigger_ratio=0.6)`, earlier than the SDK default of `0.7`, because tool
  results are large. It rewrites only the outgoing model request and keeps every artifact id
  and tool-call id; the stored session events do not change.

### 3.8 Response mapping (unchanged wire contract)

| Turn outcome | `ConversationResponse.status` |
|--------------|-------------------------------|
| Final text, ≥ 1 skill ran this turn | `completed` (`message` = `report` = text, `tool_results`, suggested queries) |
| Final text, no skill ran | `answer` |
| Paused on `ask_user` | `needs_info` with `followup_questions` |
| Paused on `adk_request_confirmation` | `plan_ready` with `plan` = the paused calls (steps = `{name, agent, description}` per call; a workflow call adds `workflow_id` and `selection_source`) |
| Error | `error` |

The frontend wire contract (`backend/CONTRACT.md`) does not change with the ADK runtime.

## 4. Consequences

* **Faster.** One LLM call per step plus one for the answer. A single-skill request takes
  2 LLM calls instead of roughly 8.
* **More flexible.** The model chains skills that no one declared a chain for. It adapts
  to results, such as errors or empty data. It also answers conversationally about
  earlier results, without a separate turn-resolution stage.
* **Approval scope changes.** Approval covers the *next batch* of calls, not the whole
  future plan, because later steps are decided after earlier results arrive. That is the
  honest version: the old up-front plan could not bind later inputs either.
* **Auditability.** Not provided yet. The Valkey transcript is trimmed, expiring operational
  context, not an audit record; approvals and calls will be recorded in a durable store.
* **Agent cards matter more.** Skill descriptions are now the model's only routing
  signal. Descriptions that fought the old planner (e.g. `convert_svg_to_png`'s "do NOT
  chain this automatically") were rewritten.
* **Dropped planner-era metadata.** Capability `provides` / `derivation_rules` and
  `execution_priority` are no longer consulted. Data flow is carried by the transcript.
