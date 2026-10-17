# Client Agent Developer Guide

The client-agent is the central orchestrator for Prometheus. It receives frontend A2A
requests and runs a tool-calling loop over the discovered specialist capabilities,
with each skill as an LLM tool. It also gathers missing inputs, tracks artifacts, and
persists conversation state. Design: `../../docs/docs/dev-docs/agent-loop-orchestration.md`.

This guide documents the local code structure and the major functions you are likely
to touch when maintaining the client-agent.

## Runtime Entry Points

The container runs:

```bash
python agent.py
```

`agent.py` is only the Docker entry point; the implementation lives in `orchestrator/` and the top-level modules listed below.

High-level runtime path:

```text
A2A POST /
  -> orchestrator.service.OrchestratorAgent._execute()
  -> orchestrator.chat_flow.chat()
  -> orchestrator.agent_loop.advance()        (LLM turn ↔ tool calls, until an answer or a pause)
  -> orchestrator.skills.invoke_skill()       (or workflow_library.execute_workflow)
  -> tool_discovery-created A2A StructuredTool
  -> specialist agent
```

Slash commands, streaming status updates, workflow catalog endpoints, artifact ingestion,
and file upload pre-processing also enter through `OrchestratorAgent`.

## Directory Structure

```text
agents/client-agent/
  agent.py                         Docker entry point
  orchestrator/
    models.py                      Conversation request/response/state models
    runtime.py                     Environment config, caches, status updates
    service.py                     PrometheusAgent subclass and HTTP/A2A endpoints
    llm_model.py                   Resolves the `medium` alias to the provider model
    chat_flow.py                   Maps requests onto the loop, outcomes onto responses
    agent_loop.py                  Tool-calling orchestration loop
    skills.py                      Skill lookup and invocation
    debug_commands.py              Slash command handlers
    utils.py                       Pure parsing/formatting helpers
  artifact_handling.py             Artifact catalog normalization, artifact-ref schema paths
  capability_cache.py              Redis-backed discovered capability cache
  conversation_store.py            Redis-backed conversation state persistence
  file_upload_handler.py           Uploaded file description and DeepLynx storage
  param_schema.py                  JSON-schema path helpers
  tool_discovery.py                Agent discovery and A2A transport wrapping
  workflow_library/                Declarative workflow template compiler/executor
  workflows/                       Built-in workflow YAML definitions
  tests/                           Focused client-agent tests
```

## Core Models: `orchestrator/models.py`

### `ConversationRequest`

Pydantic model for one frontend/orchestrator conversation turn. Major fields:

- `query`: Natural-language user input.
- `conversation_id`: Conversation key used for Redis state, status, and artifacts.
- `followup_answers`: Structured form values returned by the frontend.
- `plan_approved`: Approval flag for gated plans.
- `artifacts`: Current conversation artifact catalog.
- `workflow_id`, `workflow_version`, `selection_source`: Explicit workflow-template selection.
- `uploaded_files`: Raw uploaded file payloads. These are handled in `service.py`.
- `newly_uploaded_artifact_ids`, `received_files`: Transient fields injected after upload handling.

### `ConversationResponse`

Pydantic model returned to the frontend/A2A caller. Major statuses:

- `needs_info`: More user inputs are required.
- `plan_ready`: A plan exists and needs approval.
- `completed`: Execution finished and a report is available.
- `answer`: Non-execution answer, such as fallback or slash-command output.
- `error`: Request failed.

### `AgentState`

TypedDict for the persisted conversation record: the LLM transcript (`llm_messages`),
the unfinished tool calls of the latest assistant turn (`pending_calls`), the
user-visible `conversation_history`, the artifact catalog in `context`, per-turn tool
results, and pause bookkeeping (`plan`, `missing_info`, `awaiting_approval`,
`final_report`) that the backend also reads.

## Runtime Support: `orchestrator/runtime.py`

Owns environment-driven runtime state and process-wide caches.

Major functions:

- `create_llm()`: Builds the request-scoped `AsyncLLMClient` used by the orchestration loop and title generation.
- `_get_status_redis_client()`: Lazily creates the Redis client used for status history.
- `status_stream(emitter)`: Registers a request-local A2A status emitter.
- `wait_for_status_stream(tasks)`: Waits for queued status emission tasks.
- `store_status_update(conversation_id, message, final=False)`: Streams live status updates to the active request and persists status history in Redis.
- `initialize_tools()`: Discovers all specialist tools and stores them in `_tools_cache`.
- `get_refresh_lock()`: Returns the process-local discovery refresh lock.
- `refresh_dynamic_components(trigger="manual")`: Refreshes tools, capability cache, and workflow library metadata.
- `discovery_refresh_loop()`: Background periodic refresh loop.
- `create_tools()`: Returns the initialized tool cache or raises if discovery has not run.
- `refresh_discovery()`: API wrapper for manual refresh endpoint.

Important globals:

- `AGENT_PORT`
- `DISCOVERY_REFRESH_SECONDS`
- `ENABLE_WORKFLOW_LIBRARY`
- `_tools_cache`
- `_refresh_task`

## Service Layer: `orchestrator/service.py`

Defines `OrchestratorAgent`, the concrete `PrometheusAgent` subclass.

Major methods:

- `__init__()`: Configures the agent name and `agent_card.json`.
- `_on_startup()`: Refreshes discovery state and starts the background refresh task.
- `_on_shutdown()`: Cancels the background refresh task.
- `lifespan(app)`: Starlette lifespan wrapper used by the base agent.
- `_refresh_endpoint(request)`: Manually refreshes discovery/capability/workflow state.
- `_llm_model_endpoint(request)`: Returns the `medium` alias and its resolved provider model for `GET /llm/model`.
- `_workflow_catalog_endpoint(request)`: Returns workflow catalog cards for the frontend picker.
- `_workflow_input_form_endpoint(request)`: Builds the unresolved input form for a workflow template.
- `_workflow_start_endpoint(request)`: Starts a conversation turn from a workflow catalog selection.
- `_collect_artifact_reference_payloads(payload)`: Recursively finds artifact-like payloads in responses.
- `_ingest_response_artifacts(conversation_id, payload)`: Registers downstream artifact references in the orchestrator artifact registry.
- `_response_payload_with_artifacts(...)`: Serializes a `ConversationResponse` and attaches `artifacts` (the whole catalog) plus `new_artifacts`. `new_artifacts` holds the artifacts this turn produced: the ids that its dispatches and uploads reported (`task_tracking.record_produced_artifacts`), and any artifact the response brings into the catalog. It is not a catalog diff. It then stamps those ids on the turn's reply (`record_turn_artifacts`).
- `_handle_uploaded_files(...)`: Validates uploaded files, infers descriptions, stores them in DeepLynx, and injects artifact references into the request payload.
- `_execute(params, context, event_queue)`: Main A2A entry point for normal chat turns.
- `configure_app(app)`: Adds client-agent-specific HTTP routes.

`configure_app()` also adds the internal route `GET /llm/model`. The backend reads it
for the `llm_model` field of `GET /api/config`. The base agent's bearer middleware
guards it with `AGENT_SECRET`. It returns `{"alias": "medium", "model": <str or null>}`.
`orchestrator/llm_model.py` (`resolve_llm_model()`) resolves the model. In proxy mode
it reads LiteLLM `/model/info` and returns `litellm_params.model` of the `medium` entry.
Without a proxy URL, it reads the fallback profile's `provider_model` for `medium`.
A resolved model is cached for `DISCOVERY_REFRESH_SECONDS`; a failure gives `null`
and is not cached. The orchestrator system prompt names the same model, or `unknown`.

Service-layer rule of thumb: keep HTTP/A2A concerns here. Planning and execution
belong in `chat_flow.py` and `agent_loop.py`.

## Conversation Flow: `orchestrator/chat_flow.py`

Maps one `ConversationRequest` onto the loop and the resulting `LoopOutcome` onto a
`ConversationResponse`.

- `chat(request)`: handles slash commands first (no LLM), then:
  - with pending calls: `plan_rejected` → `agent_loop.reject_pending`, `plan_approved` →
    `approve_pending`, `followup_answers` → `apply_answers`, free text → `apply_reply`;
  - an explicit workflow (slash command or catalog start) → `inject_tool_call`, or, with
    free-text arguments, a hint in the user message;
  - otherwise a new user turn (`begin_user_turn`).

  Then `agent_loop.advance()` runs and `_respond()` persists state and builds the response
  (`completed` / `answer` / `needs_info` / `plan_ready` / `error`).
- `_maybe_generate_title(state, conv_id)`: one-time chat-history title via the `small` flavor.

## Orchestration Loop: `orchestrator/agent_loop.py`

Every registered skill and workflow template is a tool; the LLM (`medium` flavor, via the
`prometheus_api.llm_client` tool-calling API) decides each next call with the whole
transcript in view.

- `build_tool_catalog()`: `ToolSpec` per skill (cleaned input schema, artifact-ref hints,
  approval flag) and per workflow, plus `ask_user`.
- `advance(state, catalog)`: drives the pending batch, then LLM turns, until a final answer
  (no tool calls) or a pause; bounded by `MAX_LLM_TURNS`.
- `_new_call(...)`: validates one tool call (unknown tool, bad JSON, schema errors, unknown
  artifact ids, missing runtime inputs → error result back to the model) and assigns a
  status (`needs_args`, `needs_answer`, `needs_approval`, `ready`).
- `_drive_batch(...)`: pauses for forms/approval, otherwise runs ready calls concurrently;
  specialist `INPUT_REQUIRED` becomes `waiting_input` and resumes the same A2A task.
- `apply_answers` / `apply_reply` / `approve_pending` / `reject_pending`: user input on
  pending calls. `commit_batch` appends one tool result per call, in order.
- `_compact_result(...)`: what the model sees of a result: summary, artifact ids, a
  bounded JSON payload.

## Skill Invocation: `orchestrator/skills.py`

Contains the direct bridge from an orchestrator skill ID to a discovered LangChain
tool.

Major functions:

- `find_tool_for_skill(skill_id, refresh_on_miss=True)`: Looks up a tool in `runtime.create_tools()`. If missing, it refreshes discovery once and retries.
- `invoke_skill(skill_id, params, conversation_id, emit_status=True)`: Validates required params, normalizes inputs against the capability input schema, invokes the tool, handles JSON/string results, handles `input_required`, and supports multi-material batch calls.

`invoke_skill()` is intentionally generic. Specialist-specific behavior should be
expressed in agent-card metadata, schemas, workflow templates, or downstream agents.

## Slash Commands: `orchestrator/debug_commands.py`

Implements deterministic debug commands that bypass the LLM.

Major functions:

- `_parse_slash_command(query)`: Parses `/command args`.
- `_is_slash_command_query(query)`: Boolean slash-command check.
- `_collect_registered_agent_debug_entries()`: Combines live discovery and capability-cache data for `/agents`.
- `_format_agents_debug_response(entries, errors)`: Renders `/agents` text.
- `_collect_conversation_artifacts_for_debug(request_artifacts, existing_state)`: Merges request and state artifacts for `/artifacts`.
- `_format_artifacts_debug_response(artifacts)`: Renders `/artifacts` text.
- `_maybe_handle_slash_command(request, conv_id, existing_state, request_artifacts)`: Dispatches supported slash commands and returns a `ConversationResponse` when handled.

Add new slash commands here and keep them side-effect-light.

## Utility Helpers: `orchestrator/utils.py`

Pure helpers: `extract_result_text(result_data)` (response text from common result
shapes), `normalize_suggested_queries(raw, limit=3)` and `collect_suggested_queries(tool_results, limit=3)`.

Keep this module free of Redis, HTTP, A2A, or LLM side effects.

## Supporting Modules

### `artifact_handling.py`

Normalizes artifact catalog entries and finds artifact-reference fields in skill schemas.

Major functions:

- `summarize_artifacts_for_context(...)`: Converts full artifact refs into compact context-safe metadata.
- `merge_artifacts_into_context(context, artifacts)`: Adds artifact summaries to `context["artifacts"]`.
- `merge_artifact_catalogs(primary, secondary)`: Deduplicates artifact lists while preserving order.
- `extract_artifact_field_paths(input_schema)`: Finds artifact-reference fields in an input schema.

### `capability_cache.py`

Caches flattened specialist capabilities discovered from agent cards.

Major classes/functions:

- `AgentCapability`: Dataclass-like capability record with agent, skill, schema, execution, and metadata fields.
- `CapabilityCache`: Redis-backed cache with refresh and lookup helpers.
- `get_capability_cache()`: Process singleton accessor.

### `conversation_store.py`

Persists full `AgentState` payloads in Redis. Turns of one conversation can run at once
(a backgrounded turn and the next one), so writes merge by turn instead of overwriting.

Major functions:

- `store_conversation(conv_id, state)`: Tags the current turn's new history entries with its `turn_id`. Then it merges the state with the stored document in one `WATCH`/`MULTI` transaction (`merge_conversation`). Other turns' entries are kept, and the newest-started turn owns the top-level fields. A late turn that leaves a form or plan pending takes them from a newer turn that left none.
- `get_conversation(conv_id)`: Reads conversation state; untagged history entries read as `turn_id: "legacy"`.
- `record_turn_artifacts(conv_id, turn_id, artifact_ids)`: Stamps a turn's artifact ids on its last reply (`stamp_turn_artifacts`), which a restored conversation renders from.

### `file_upload_handler.py`

Handles user-uploaded files before planning starts.

Major classes/functions:

- `UploadedFile`: Pydantic model for frontend-uploaded file payloads.
- `mime_type_label(mime_type, filename="")`: Produces human-readable file type text.
- `infer_file_descriptions(query, uploaded_files, llm)`: Uses the LLM to describe uploaded files for artifact metadata.
- `upload_files_to_deeplynx(agent, uploaded_files, descriptions, context, event_queue, storage_config)`: Stores uploaded files and registers artifact references.

### `param_schema.py`

Shared JSON-schema path helpers.

Major functions:

- `set_nested_value(data, path, value)`: Writes dotted paths.
- `get_nested_value(data, path)`: Reads dotted paths.
- `has_param_path(params, path)`: Checks whether a nested/dotted param is present.
- `schema_input_source(prop)`: Reads source metadata for an input field.
- `is_user_input_schema(prop)`: Identifies user-facing schema fields.
- `extract_required_param_paths(schema, include_internal=False)`: Extracts required input paths.
- `flatten_schema_properties(schema)`: Flattens nested schema properties into dotted paths.
- `normalize_params_for_input_schema(params, input_schema)`: Converts dotted params into the nested shape expected by a skill schema.

### `tool_discovery.py`

Discovers specialist agents and wraps their skills as LangChain `StructuredTool`
objects.

Major functions:

- `discover_agents()`: Lists available agents from the LiteLLM agent directory.
- `get_agent_card(agent_id, direct_url=None)`: Fetches a specialist agent card.
- `create_input_schema_from_skill(skill)`: Builds a Pydantic model from skill `inputSchema`.
- `call_a2a_agent(...)`: Calls a downstream agent over A2A JSON-RPC.
- `create_tool_from_skill(...)`: Creates a LangChain tool wrapper for one skill.
- `get_all_tools_dynamic()`: Discovers all non-self agents and returns all skill tools.

### `workflow_library/`

Loads, compiles, matches, and executes declarative workflow templates.

Important files:

- `schema.py`: Workflow YAML schema models.
- `registry.py`: Loads workflow definitions and builds catalog/form payloads.
- `compiler.py`: Compiles workflow definitions against capability metadata.
- `matcher.py`: Scores workflow templates against user queries.
- `binding.py`: Resolves step/input bindings.
- `executor.py`: Executes compiled workflow steps.

## State and Data Contracts

Relevant external contracts are also documented in:

- `../../docs/MESSAGE_SCHEMAS.md`
- `../../docs/docs/dev-docs/artifacts.md`
- `../../docs/docs/dev-docs/file-uploads.md`
- `../../docs/docs/dev-docs/adding-agents.md`

Keep these docs aligned when changing request/response payloads, artifact metadata,
or agent-card metadata semantics.

## Common Maintenance Tasks

### Add a new specialist capability

Prefer agent-card and schema changes in the specialist agent. The client-agent should
discover it through `tool_discovery.py` and `capability_cache.py` without code changes.

Touch client-agent code only if the new capability requires new generic metadata
semantics, a new artifact-binding mode, or workflow-template support.

### Add a new slash command

1. Add parser/handler behavior in `orchestrator/debug_commands.py`.
2. Return `ConversationResponse(status="answer", ...)`.
3. Add a focused test in `tests/test_service.py`.
4. Keep the command deterministic and avoid LLM calls.

### Add a new workflow template

1. Add YAML under `workflows/`.
2. Ensure required skills exist in discovered capabilities.
3. Update or add workflow tests under `tests/test_workflow_library.py`.
4. Verify `/workflows/catalog` and `/workflows/{workflow_id}/input-form`.

### Change orchestration behavior

The model fills parameters from the conversation; there is no separate extraction
stage. Tune behavior through `prompts/orchestrator_system.txt`, the tool advertisement
in `agent_loop.build_tool_catalog`, or call validation in `agent_loop._new_call`. Prefer
improving skill descriptions in agent cards over special-casing skills here.

### Change execution behavior

Use `orchestrator/agent_loop.py` for call lifecycle and pausing, and
`orchestrator/skills.py` for individual skill invocation mechanics. HTTP/A2A request
handling belongs in `service.py`.

### Change uploaded file behavior

Use `file_upload_handler.py` for upload validation/description/storage logic and
`orchestrator/service.py` for request-payload integration.

### Add a new HTTP endpoint

Add the handler to `OrchestratorAgent` in `orchestrator/service.py`, then register it
in `configure_app()`.

## Testing

Run client-agent tests from this directory:

```bash
cd agents/client-agent
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests
```

The plugin-autoload-disabled form avoids unrelated pytest plugins from the ambient
Python environment. Use `python -m pytest` so pytest runs under this agent's uv
environment instead of an ambient executable on PATH.

Useful focused runs:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests/test_agent_loop.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests/test_tool_discovery.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests/test_workflow_library.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -p pytest_asyncio.plugin tests/test_artifact_handling.py
```

Compile-check the split modules:

```bash
python -m py_compile agent.py orchestrator/*.py
```

## Docker Notes

The Dockerfile copies both `agent.py` and `orchestrator/` into `/app`. If you change
code under `orchestrator/`, rebuild or restart the `client-agent` container so the
running image uses the new files.

## Design Rules

- Keep `agent.py` a bare entry point.
- Keep request transport concerns in `service.py`.
- Keep conversation state transitions in `chat_flow.py`.
- Keep orchestration decisions with the model (`agent_loop.py`); keep the code generic.
- Keep skill invocation mechanics in `skills.py`.
- Prefer agent-card metadata, workflow templates, and schemas over hardcoded
  skill-specific behavior.
- Preserve the public response contracts used by the frontend and A2A client.
