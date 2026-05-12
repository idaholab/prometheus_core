# Client Agent Developer Guide

The client-agent is the central orchestrator for Prometheus. It receives frontend A2A
requests, plans work from discovered specialist capabilities, gathers missing inputs,
executes one or more specialist skills, tracks artifacts, and persists conversation
state.

This guide documents the local code structure and the major functions you are likely
to touch when maintaining the client-agent.

## Runtime Entry Points

The container runs:

```bash
python agent.py
```

`agent.py` is intentionally small. It is a compatibility entry point for Docker,
tests, and external callers that still import `agent` directly. New implementation
work should generally go into `orchestrator/`, not `agent.py`.

High-level runtime path:

```text
A2A POST /
  -> orchestrator.service.OrchestratorAgent._execute()
  -> orchestrator.chat_flow.chat()
  -> orchestrator.planning_flow.compile_query_plan()
  -> orchestrator.execution.execute_current_plan()
  -> orchestrator.skills.invoke_skill()
  -> tool_discovery-created A2A StructuredTool
  -> specialist agent
```

Slash commands, status polling, workflow catalog endpoints, artifact ingestion, and
file upload pre-processing also enter through `OrchestratorAgent`.

## Directory Structure

```text
agents/client-agent/
  agent.py                         Stable executable and import compatibility module
  orchestrator/
    models.py                      Conversation request/response/state models
    runtime.py                     Environment config, caches, status updates
    service.py                     PrometheusAgent subclass and HTTP/A2A endpoints
    chat_flow.py                   Multi-turn conversation state machine
    planning_flow.py               Planner integration and plan display shaping
    execution.py                   Skill/workflow execution and follow-up handling
    skills.py                      Skill lookup and invocation
    parameters.py                  Parameter, context, and artifact resolution
    debug_commands.py              Slash command handlers
    utils.py                       Pure parsing/formatting helpers
  artifact_handling.py             Artifact catalog normalization and input binding
  capability_cache.py              Redis-backed discovered capability cache
  conversation_store.py            Redis-backed conversation state persistence
  file_upload_handler.py           Uploaded file description and DeepLynx storage
  param_schema.py                  JSON-schema path helpers
  planner.py                       LLM planner tool-calling implementation
  tool_discovery.py                Agent discovery and A2A transport wrapping
  workflow_library/                Declarative workflow template compiler/executor
  workflows/                       Built-in workflow YAML definitions
  tests/                           Focused client-agent tests
```

## Compatibility Module: `agent.py`

`agent.py` re-exports the public names that older tests and callers expect, including
`ConversationRequest`, `ConversationResponse`, `chat`, `execute_current_plan`,
`invoke_skill`, and `OrchestratorAgent`.

It also contains `_sync_compat()`, which propagates monkeypatches made against
`agent` into the split modules. This exists mostly for existing tests and legacy
imports. Avoid adding new orchestration logic here.

Use `agent.py` for:

- Keeping the container command stable.
- Preserving `import agent` compatibility.
- Exporting a new public helper only when existing callers need it.

Do not use `agent.py` for:

- New request flow logic.
- New parameter resolution behavior.
- New A2A/service endpoint behavior.

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

TypedDict for persisted conversation orchestration state. It carries messages,
history, routing decisions, plans, pending subagent `INPUT_REQUIRED` requests,
resolved context, tool results, and final reports.

## Runtime Support: `orchestrator/runtime.py`

Owns environment-driven runtime state and process-wide caches.

Major functions:

- `create_llm()`: Builds the Anthropic chat model used by planner/refinement helpers.
- `_get_status_redis_client()`: Lazily creates the Redis client used for status history.
- `store_status_update(conversation_id, message, final=False)`: Writes latest status and rolling history to Redis for frontend polling.
- `initialize_tools()`: Discovers all specialist tools and stores them in `_tools_cache`.
- `get_refresh_lock()`: Returns the process-local discovery refresh lock.
- `refresh_dynamic_components(trigger="manual")`: Refreshes tools, capability cache, and workflow library metadata.
- `discovery_refresh_loop()`: Background periodic refresh loop.
- `create_tools()`: Returns the initialized tool cache or raises if discovery has not run.
- `refresh_discovery()`: API wrapper for manual refresh endpoint.
- `get_status(conversation_id)`: Reads latest status and history for `/status/{conversation_id}`.

Important globals:

- `AGENT_PORT`
- `MODEL_NAME`
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
- `_status_endpoint(request)`: Returns Redis-backed status history.
- `_refresh_endpoint(request)`: Manually refreshes discovery/capability/workflow state.
- `_workflow_catalog_endpoint(request)`: Returns workflow catalog cards for the frontend picker.
- `_workflow_input_form_endpoint(request)`: Builds the unresolved input form for a workflow template.
- `_workflow_start_endpoint(request)`: Starts a conversation turn from a workflow catalog selection.
- `_forward_status_history(...)`: Polls Redis status history and forwards updates into the A2A event stream.
- `_collect_artifact_reference_payloads(payload)`: Recursively finds artifact-like payloads in responses.
- `_ingest_response_artifacts(conversation_id, payload)`: Registers downstream artifact references in the orchestrator artifact registry.
- `_response_payload_with_artifacts(...)`: Serializes a `ConversationResponse` and attaches `artifacts` plus `new_artifacts`.
- `_handle_uploaded_files(...)`: Validates uploaded files, infers descriptions, stores them in DeepLynx, and injects artifact references into the request payload.
- `_execute(params, context, event_queue)`: Main A2A entry point for normal chat turns.
- `configure_app(app)`: Adds client-agent-specific HTTP routes.

Service-layer rule of thumb: keep HTTP/A2A concerns here. Planning and execution
belong in `chat_flow.py`, `planning_flow.py`, and `execution.py`.

## Conversation Flow: `orchestrator/chat_flow.py`

Owns the top-level multi-turn state machine.

Major functions:

- `chat(request)`: Canonical conversation endpoint. It handles slash commands, existing conversation continuations, follow-up answers, plan approvals, new queries, workflow selections, fallback answers, and execution dispatch.
- `_needs_info_response(conv_id, state, hint=...)`: Persists state and returns a `needs_info` response with generated form questions.
- `_completed_response(conv_id, state)`: Persists final state and returns a `completed` response.
- `_error_response(conv_id, log_msg, user_msg)`: Stores an error status and returns an error-shaped response.

Main branches inside `chat()`:

1. Slash command path, handled before planner/execution work.
2. Existing conversation continuation.
3. Plan approval.
4. Follow-up answer processing.
5. New query or explicit workflow selection.
6. Fallback answer, `needs_info`, `plan_ready`, or immediate execution.

## Planning Flow: `orchestrator/planning_flow.py`

Turns a query plus discovered capabilities into an executable routing decision and
UI-facing plan.

Major functions:

- `_unique_workflow_skills(workflow)`: Returns ordered unique skill IDs in a workflow template.
- `compile_query_plan(state, explicit_workflow_id=None, explicit_workflow_version=None, selection_source=None, seed_params=None)`: Canonical planning function. It loads capabilities, matches workflow templates, calls `planner.compile_plan_with_tools()` when needed, resolves metadata-derived params, computes missing inputs, and returns a state update.
- `extract_refinement_param_updates(query, routing_decision, conversation_history=None)`: Uses the LLM to extract parameter changes from a user refinement while a plan is awaiting approval.
- `plan_analysis(state)`: Builds or preserves the user-visible plan object from routing metadata.
- `show_plan(state)`: Marks state as awaiting approval.

The LLM tool-calling planner itself lives in `planner.py`; `planning_flow.py` is the
orchestrator-facing adapter around it.

## Execution Flow: `orchestrator/execution.py`

Runs selected capabilities or workflow templates and handles mid-execution input
requirements.

Major functions:

- `invoke_agent_generic(state)`: Executes non-template routing decisions. Supports `single`, `parallel`, and `sequential` workflow types.
- `ask_followup_dynamic(state)`: Converts missing required params or pending subagent `INPUT_REQUIRED` payloads into frontend form questions.
- `extract_followup_answers_from_query(state, query)`: Extracts missing required params from a natural-language follow-up response.
- `apply_followup_answers_to_state(state, followup_answers, query="")`: Merges user follow-up answers into routing params and recomputes missing inputs.
- `execute_current_plan(state, start_message)`: Canonical execution path for approved and auto-executed plans. It dispatches either to workflow template execution or direct skill execution.
- `execute_approved_plan(state)`: Convenience wrapper for approved plans.
- `_format_plan_for_response(state)`: Normalizes internal plan state for frontend display.
- `_latest_conversation_entry(state)`: Safe helper for retrieving the most recent history entry.
- `_coerce_followup_value(value, value_type)`: Converts form values into requested primitive types.
- `_lookup_context_value(state, name)`: Finds a missing-input value in routing params or shared context.
- `resolve_missing_inputs_from_state(state, missing_inputs)`: Splits subagent missing inputs into auto-resolved and unresolved sets.
- `_questions_from_pending_subagent_requests(state)`: Builds frontend questions from pending subagent requests.
- `resume_pending_subagent_requests(state, followup_answers)`: Resumes blocked subagent tasks with user-provided inputs.

Execution output is written back into `conversation_history`, `tool_results`,
`context`, `missing_info`, and `final_report` in `AgentState`.

## Skill Invocation: `orchestrator/skills.py`

Contains the direct bridge from an orchestrator skill ID to a discovered LangChain
tool.

Major functions:

- `find_tool_for_skill(skill_id, refresh_on_miss=True)`: Looks up a tool in `runtime.create_tools()`. If missing, it refreshes discovery once and retries.
- `invoke_skill(skill_id, params, conversation_id, emit_status=True)`: Validates required params, normalizes inputs against the capability input schema, invokes the tool, handles JSON/string results, handles `input_required`, and supports multi-material batch calls.

`invoke_skill()` is intentionally generic. Specialist-specific behavior should be
expressed in agent-card metadata, schemas, workflow templates, or downstream agents.

## Parameter and Context Resolution: `orchestrator/parameters.py`

Owns data-driven parameter resolution using capability metadata, workflow metadata,
conversation context, artifacts, and previous tool results.

Major functions:

- `get_selected_skills(routing_decision)`: Returns the primary and supporting skill IDs in stable order.
- `resolve_user_required_params(routing_decision)`: Computes user-facing required params from workflow or capability schemas.
- `order_skills_for_workflow(routing_decision)`: Orders selected skills for sequential workflows using metadata such as `execution_priority`, `provides`, and `derivation_rules`.
- `build_plan_param_metadata(selected_skills, capabilities_by_skill, selected_workflow=None)`: Builds labels, descriptions, types, and units for frontend plan forms.
- `merge_context_map(target_context, context_key, entries)`: Merges context-map entries, including dotted context paths.
- `extract_provided_context_maps(result_data, provides)`: Applies capability `provides` rules to tool results.
- `collect_context_maps_from_history(conversation_history, capabilities_by_skill)`: Rebuilds context maps from previous turns.
- `attach_artifact_context(params, context)`: Adds summarized artifact catalog metadata to skill params.
- `derive_params_from_rules(query, params, rules, context, history_context_maps)`: Applies capability `derivation_rules` to populate missing params.
- `resolve_params_via_capability_metadata(query, extracted_params, selected_skills, context, conversation_history)`: Main metadata-driven parameter resolver. It carries forward context, binds artifact inputs, prefetches provider skills when safe, and applies derivation rules.

This is the right module for changes involving metadata semantics, context maps,
artifact binding, or automatic parameter derivation.

## Slash Commands: `orchestrator/debug_commands.py`

Implements deterministic debug commands that bypass planner LLM calls.

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

Pure helpers used across planning and execution.

Major functions:

- `extract_json_from_text(text)`: Extracts JSON from raw or markdown-wrapped LLM output.
- `extract_material_ids_from_text(text)`: Pulls material IDs such as `SS316` from user text.
- `enrich_material_params(query, extracted_params)`: Normalizes material IDs into `material_id` and `material_ids`.
- `extract_result_text(result_data)`: Converts common agent result shapes into response text.
- `normalize_suggested_queries(raw, limit=3)`: Normalizes suggested follow-up query payloads.
- `collect_suggested_queries(tool_results, limit=3)`: Aggregates suggestions from tool results.
- `build_comparison_summary(user_query, by_material)`: Builds deterministic comparison summaries for common material comparison questions.
- `normalize_by_mode(value, mode)`: Applies metadata normalizers such as `upper_no_space_hyphen`.
- `get_value_by_path(data, path)`: Reads dotted paths from dict/list structures.
- `set_param_path(params, path, value)`: Writes nested and dotted parameter forms.
- `rule_matches_query(query, rule)`: Evaluates simple phrase-based derivation-rule conditions.

Keep this module free of Redis, HTTP, A2A, or LLM side effects.

## Supporting Modules

### `artifact_handling.py`

Normalizes artifact catalog entries and binds artifact references into skill inputs.

Major functions:

- `summarize_artifacts_for_context(...)`: Converts full artifact refs into compact context-safe metadata.
- `merge_artifacts_into_context(context, artifacts)`: Adds artifact summaries to `context["artifacts"]`.
- `merge_artifact_catalogs(primary, secondary)`: Deduplicates artifact lists while preserving order.
- `extract_artifact_field_paths(input_schema)`: Finds artifact-reference fields in an input schema.
- `resolve_artifact_inputs(params, query, context, input_schemas)`: Resolves artifact fields from explicit params, newly uploaded IDs, query mentions, and artifact catalog metadata.

### `capability_cache.py`

Caches flattened specialist capabilities discovered from agent cards.

Major classes/functions:

- `AgentCapability`: Dataclass-like capability record with agent, skill, schema, execution, and metadata fields.
- `CapabilityCache`: Redis-backed cache with refresh and lookup helpers.
- `get_capability_cache()`: Process singleton accessor.

### `conversation_store.py`

Persists full `AgentState` payloads in Redis.

Major functions:

- `store_conversation(conv_id, state)`: Writes conversation state.
- `get_conversation(conv_id)`: Reads conversation state.

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

### `planner.py`

Implements the LLM tool-calling planner.

Major classes/functions:

- `PlanningResult`: Structured planning output consumed by `planning_flow.py`.
- `WorkflowPlanningCandidate`: Candidate workflow metadata passed into planner prompts.
- `_build_capability_context(capabilities)`: Formats capability metadata for the planner.
- `_build_prompt(...)`: Builds the planner system/user prompt.
- `_build_planning_tools(...)`: Defines planner-side tools such as selecting capabilities, setting params, and fallback responses.
- `compile_plan_with_tools(...)`: Main planner entry point.

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
3. Add a focused test in `tests/test_execution_path.py`.
4. Keep the command deterministic and avoid planner LLM calls.

### Add a new workflow template

1. Add YAML under `workflows/`.
2. Ensure required skills exist in discovered capabilities.
3. Update or add workflow tests under `tests/test_workflow_library.py`.
4. Verify `/workflows/catalog` and `/workflows/{workflow_id}/input-form`.

### Change parameter resolution

Use `orchestrator/parameters.py` for generic metadata-driven behavior. Use
`param_schema.py` only for schema path mechanics.

Avoid hardcoding domain-specific skill names unless there is no metadata-based
alternative.

### Change execution behavior

Use `orchestrator/execution.py` for orchestration execution mechanics and
`orchestrator/skills.py` for individual skill invocation mechanics.

Avoid putting HTTP/A2A request handling in `execution.py`; that belongs in
`service.py`.

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
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio.plugin tests
```

The plugin-autoload-disabled form avoids unrelated pytest plugins from the ambient
Python environment.

Useful focused runs:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio.plugin tests/test_execution_path.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio.plugin tests/test_tool_discovery.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio.plugin tests/test_workflow_library.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -p pytest_asyncio.plugin tests/test_artifact_handling.py
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

- Keep `agent.py` as a compatibility wrapper.
- Keep request transport concerns in `service.py`.
- Keep conversation state transitions in `chat_flow.py`.
- Keep planner adaptation in `planning_flow.py`.
- Keep skill execution mechanics in `execution.py` and `skills.py`.
- Keep metadata semantics in `parameters.py`.
- Prefer agent-card metadata, workflow templates, and schemas over hardcoded
  skill-specific behavior.
- Preserve the public response contracts used by the frontend and A2A client.
