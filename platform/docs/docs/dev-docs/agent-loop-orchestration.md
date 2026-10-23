# Client-Agent Orchestration as a Tool-Calling Loop

**Date:** 2026-09-30
**Status:** Implemented (replaces the compile-then-execute planner)
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

Replace planning with a **single tool-calling loop**, the standard agent pattern:

```
system prompt  +  transcript  +  tools (one per skill, one per workflow template, ask_user)
      │
      ▼
  LLM turn ──► tool calls? ──no──► final answer (end of turn)
      ▲              │ yes
      │              ▼
      │     validate → [pause for user if needed] → invoke specialists via LiteLLM A2A
      │              │
      └──── tool results (summary + artifact ids) appended to transcript
```

The model sees every skill's description and input schema as a tool. It also sees
everything that has happened so far: user messages, earlier tool calls, and their results
with artifact ids. It decides the next call with fully parameterized arguments, *after* the previous
call's result is known. Decomposition, chaining, parameter extraction and data flow
between steps all become ordinary tool-calling behavior.

"Create a PNG image with the word Popelnase" becomes:

```
assistant → create_svg_artifact(word="Popelnase")
tool      → {"status": "succeeded", "artifacts": [{"artifact_id": "a1", "mime_type": "image/svg+xml", ...}]}
assistant → convert_svg_to_png(artifact_id="a1")
tool      → {"status": "succeeded", "artifacts": [{"artifact_id": "a2", "mime_type": "image/png", ...}]}
assistant → "Here is the PNG image with the word Popelnase."
```

## 3. Design

### 3.1 Modules

| Module | Role |
|--------|------|
| `orchestrator/agent_loop.py` | The loop: tool catalog, LLM turns, call validation, pausing and resuming, execution, result compaction. |
| `orchestrator/chat_flow.py` | Thin entry point: slash commands, state load/create, maps a `ConversationRequest` (query / answers / approval / rejection) onto the loop and a `LoopOutcome` onto a `ConversationResponse`. |
| `orchestrator/skills.py` | Unchanged: `invoke_skill` (A2A via LiteLLM, Task Graph tracking, streaming status, long-running detach). |
| `workflow_library/` | Unchanged engine. Each compiled template is exposed as one tool and executed deterministically by `execute_workflow`. |
| `prompts/orchestrator_system.txt` | The system prompt. |

Deleted: `planner.py`, `planner_models.py`, `orchestrator/planning_flow.py`,
`orchestrator/parameter_extraction.py`, `orchestrator/parameters.py`,
`orchestrator/execution.py`, the planning and extraction prompts,
`artifact_handling.collect_chain_required_paths` / `resolve_artifact_inputs`,
`workflow_library/matcher.py`, and the `agent.py` monkeypatch compatibility layer.

### 3.2 Tools

* **Skill tools**: one per registered capability (`CapabilityCache`). The name is the
  skill id, sanitized to `^[a-zA-Z0-9_-]{1,64}$`. The description is the skill
  description, usage notes, and "requires approval" when it applies. Parameters are the
  skill's `input_schema`, with:
  * vendor keywords (`x_*`, `x-*`) stripped, so the provider sees plain JSON Schema;
  * artifact-reference fields (`x_artifact_ref`) described as "artifact_id of an existing
    conversation artifact". The user is never asked for one on a form. A missing required
    artifact reference is an error result that sends the model to the catalog or to the
    upstream skill;
  * `artifacts` / `conversation_id` removed, because the orchestrator attaches them.
* **Workflow tools**: one per compiled template (`workflow_tool_name(id)`). Parameters are
  the template's `required_input_paths`, as flat properties keyed by dotted path.
* **`ask_user`**: open clarification questions, given as a list of typed form fields.

### 3.3 Call lifecycle

Every tool call in an assistant message becomes a **pending call** with a status:

| Status | Meaning | Leaves the state when |
|--------|---------|-----------------------|
| `needs_args` | Required *user-input* parameters are missing (schema-derived). | The user submits the form. |
| `needs_answer` | `ask_user` question. | The user answers (form or free text). |
| `needs_approval` | Skill has `requires_approval` or the workflow has `metadata.requires_approval`. | The user approves or rejects. |
| `ready` | Validated, runnable. | It executes. |
| `waiting_input` | A specialist returned A2A `INPUT_REQUIRED`. | The user answers and the same A2A task resumes. |
| `done` | Has a tool-result message. | — |

Validation happens before anything runs. These problems produce an immediate **error
result** for the model: an unknown tool, malformed JSON arguments, a schema violation
(`jsonschema`), an unknown artifact id, or a missing *runtime* input. The model can then
correct the call. A missing *user-input* parameter pauses with a typed form instead. The
model is told never to invent those values. Form answers go through the same validation
before the call runs.

**Batch rule:** if any call in an assistant message needs the user (args, answer,
approval), nothing in that message runs until every call is ready. Forms come first,
then approval. Once all calls are ready, they run concurrently (`asyncio.gather`), which
is how parallel work is expressed. After every call in the batch is `done`, the tool
results are appended in call order and the loop continues. This keeps the transcript
valid for every provider: each `tool_call_id` gets exactly one result before the next
LLM turn.

### 3.4 Pausing and resuming across turns

Loop state lives in the conversation record in Valkey (`conversation:{id}`):

```jsonc
{
  "llm_messages": [ ... ],      // OpenAI-format transcript (user / assistant+tool_calls / tool)
  "pending_calls": [ ... ],     // the unfinished batch, see 3.3
  "turn_tool_results": { ... }, // skill_id → raw result for this user turn (response payload)
  "conversation_history": [ ... ], // user-visible transcript + evidence (backend chat history)
  "context": { "artifacts": [ ... ] },
  "awaiting_approval": bool, "missing_info": [...], "final_report": str|null, "plan": {...}
}
```

How the next request is mapped:

| Incoming request | With pending calls |
|------------------|--------------------|
| `followup_answers` | Merged into `needs_args` call arguments; used as the `ask_user` answer; merged into the params that resume `waiting_input` A2A tasks (same context and task id, same Task Graph node), with sources in `inputSources` metadata. |
| `plan_approved` | `needs_approval` → `ready`, then execute. |
| `plan_rejected` | Every unfinished call gets the result "The user rejected this call". Reply: "Plan rejected…". No LLM call. |
| Free-text `query` | An `ask_user` call is answered with the text. Every other unfinished call gets the result "Not executed: the user replied instead: …", and the loop continues. So "use 20 mm instead" while a plan awaits approval simply re-plans. |

Without pending calls, the query is appended as a user message and the loop runs.
An explicit workflow selection (`/workflow` slash command, catalog start endpoint)
with no free-text arguments injects a synthetic assistant tool call to that workflow.
The form inputs are its arguments, so it takes the same validate/pause/execute path
without an LLM routing decision. A `/workflow` command with free-text arguments
instead adds a hint to the user message, and the model fills the workflow inputs.

### 3.4a Concurrent turns

A turn detached to the background keeps running while the user sends the next one, and
`conversation_store` merges stores by turn instead of overwriting (`merge_conversation`).
The loop fits into that model as follows:

* **`llm_messages` merges per turn like `conversation_history`.** Each message is tagged
  with its turn's `turn_id` and `turn_started_at` when first stored. A store keeps the
  messages of every other turn from the stored document. It takes this turn's messages
  from its own copy, as one contiguous block ordered by turn start.
* **`llm_view` repairs the merged transcript before every LLM call.** A paused batch
  resumes in a later request, which is a new turn, so another turn's block can land
  between a call and its result. A superseded pending call may never get a result.
  `llm_view` puts each call's stored result directly after its assistant message. Where a
  call has no result, it substitutes a "not executed" one. It drops results with no call
  and strips the bookkeeping tags.
* **Unfinished `pending_calls` count as pending input** in the newest-turn ownership rule
  (`_leaves_pending_input`). So a newer turn that left no form or plan does not overwrite
  a late turn's open one.
* **Restore fidelity:** a pause's `followup_questions` / `plan` history entry carries the
  reply text as `content`. So artifacts produced before the pause are stamped on it
  (`stamp_turn_artifacts`) and restore with that reply. The `plan_approved` entry has no
  content, so a restored chat shows no bubble that the live UI never showed.

### 3.5 What goes back to the model

A tool result is compact JSON:

```json
{"status": "succeeded|failed|rejected|not_executed|answered",
 "summary": "<answer/message/report text, ≤ 2 000 chars>",
 "artifacts": [{"artifact_id": "...", "name": "...", "mime_type": "...", "description": "..."}],
 "result": "<remaining JSON payload, ≤ 6 000 chars>",
 "inputs": {"<name>": "<value>"},
 "input_sources": {"<name>": "model|user|context"},
 "error": "..."}
```

Values supplied after the call was made (form answers for missing required parameters
or a specialist's `INPUT_REQUIRED`, and values resolved from context) are merged into the
call's arguments, so they are part of `turn_tool_inputs` and the params the agent
receives. Each call tracks `input_sources`: `model` for the model's own arguments, `user`
for form answers, `context` for values the platform filled in. When anything other than
the model supplied an input, the tool result includes `inputs` (what ran) and
`input_sources`, so the model credits each value correctly. The sources also travel to
the agent as A2A message metadata `inputSources`.

Sensitive answers reach only the resumed invocation: they are never written to the
arguments, context, `inputs`, or transcript (their name still appears in
`input_sources`). Agents read every input from `params` and the sources with
`PrometheusAgent.get_input_sources(context)`; there is no separate provided-inputs data part.

Artifacts produced by a call are merged into `context.artifacts` right away, so the next
call's artifact references validate. The full raw result is kept in `turn_tool_results`
and `conversation_history` for the response and the chat-history UI.

The system prompt lists the conversation's artifact catalog (id, name, mime type,
description) on every LLM call. Files uploaded this turn are named in the user message.
A reply to a pending call names its files in that call's tool result.
The `answered` result of `ask_user` and the `not_executed` result of a superseded call
carry the note.
The chat history keeps the reply text without the file note.

The system prompt also lists the newest successful inputs of each skill
(`recent_skill_inputs`). They come from the `tool_inputs` of every `conversation_history`
entry, so they survive the transcript window in 3.6. A follow-up such as "redo the valve
with 6 holes" can then start from inputs the model no longer sees in the transcript.

### 3.6 LLM client and bounds

* Uses the `prometheus_api.llm_client` tool-calling API (base image ≥ `1914b55`).
  Tools are `ToolDefinition`s sent with `tool_choice="auto"`, calls come from
  `response.tool_calls` (`arguments_error` set on malformed JSON), and the transcript is
  built with `assistant_message(response)` / `tool_result_message(call_id, content)`.
  The loop ends **only** when a response has no tool calls, never on `finish_reason`. An
  empty final answer is reported as an error instead of being stored.
* At most **12 LLM turns** per user request. On hitting the limit, the loop ends with an
  error message.
* Transcript window: when `llm_messages` exceeds 80 entries, the oldest turns are
  dropped, always cutting at a user-message boundary so no tool result is orphaned.
* Model flavor: `medium`, hardcoded per platform convention.
  One call per step replaces 6–12 calls per request, so this is the speed lever. Switch
  to `large` in code only if routing quality requires it.

### 3.7 Response mapping (unchanged wire contract)

| Loop outcome | `ConversationResponse.status` |
|--------------|-------------------------------|
| Final text, ≥ 1 skill ran this turn | `completed` (`message` = `report` = text, `tool_results`, suggested queries) |
| Final text, no skill ran | `answer` |
| Paused on `needs_args` / `needs_answer` / `waiting_input` | `needs_info` with `followup_questions` |
| Paused on `needs_approval` | `plan_ready` with `plan` = the pending batch (steps = `{name, agent, description}` per call; a workflow call adds `workflow_id`, `selection_source` and any pinned `workflow_version`) |
| Loop error or turn limit | `error` |

The wire contract is unchanged except for one field. The conversation record no longer
carries a `material_id`, so `ConversationSummary.material_id` is removed from the backend
contract (`backend/CONTRACT.md`) and its TypeScript mirror. No frontend code read it.

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
