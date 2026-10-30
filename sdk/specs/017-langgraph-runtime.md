# 017 - LangGraph runtime

status: implemented
sources: prometheus_api/langgraph/__init__.py, prometheus_api/langgraph/model.py, prometheus_api/langgraph/artifacts.py, prometheus_api/langgraph/middleware.py, prometheus_api/langgraph/agent.py, pyproject.toml, tests/test_langgraph_model.py, tests/test_langgraph_artifacts.py, tests/test_langgraph_middleware.py, tests/test_langgraph_agent.py
depends-on: 003, 006, 009, 010

## Purpose
Let a Prometheus agent run its skills as `langchain.agents.create_agent` graphs with a LangGraph
checkpointer, so a run that waits for approval or dies mid-tool resumes on the same A2A task.
The module adds only what LangGraph and LangChain do not ship: a chat model over
`AsyncLLMClient`, DeepLynx artifacts, DeepLynx provenance, and the A2A shell.

## Requirements
- REQ-017-01: `PrometheusChatModel` MUST send every completion through the given `AsyncLLMClient.chat` with its alias and the bound tool schemas, MUST return the response's tool calls as `AIMessage.tool_calls`, and MUST NOT carry a provider URL, key or model ID.
- REQ-017-02: `save_artifact` MUST create one new DeepLynx item per save, with the properties `artifact_key`, `version`, `sha256` and `idempotency_key`, MUST emit its `deeplynx://` reference, and MUST NOT update or delete an existing artifact item.
- REQ-017-03: `ProvenanceMiddleware` MUST add a `generated` relation from the execution record to each artifact saved in a tool call and an `input_to` relation from each loaded artifact to the record, each `(from, to, type)` once, and MUST close the record once with `status`, `ended_at` and the tool-call digests when the graph ends without an interrupt.
- REQ-017-04: `LangGraphPrometheusAgent` MUST pause a tool of a `requires_approval` skill (or of `approval_tools`) before it runs, with a final `TASK_STATE_INPUT_REQUIRED` that asks for the boolean `approved`, MUST run it once after `approved: true` on the same task, and MUST return a rejected result without running it after `approved: false`.
- REQ-017-05: The summarization middleware MUST use the `small` alias, MUST trigger at `LANGGRAPH_SUMMARY_TRIGGER_TOKENS`, and MUST keep every `deeplynx://` URI and `tool_call_id` of the summarized messages in the next model request.
- REQ-017-06: `LangGraphPrometheusAgent` MUST key the checkpoints of a request by its A2A task ID, MUST fail at startup when a card skill has no tools or a tool list has no card skill, and a new agent instance on the same checkpointer MUST resume an unfinished task without running a finished tool again.

## Behavior
- BEH-017-01: GIVEN a tool call that already saved `slow-job.json` WHEN the resumed run calls the same tool with the same `thread_id` and `tool_call_id` THEN no second item is created and the first version is returned.

## Interfaces
- `PrometheusChatModel(alias: str = "default", client: AsyncLLMClient)`, a LangChain `BaseChatModel`; async only, `invoke` raises `NotImplementedError`.
- `PrometheusContext(agent, request, event_queue, thread_id, execution_record_id, storage, provenance)`, the `create_agent` `context_schema`.
- `save_artifact(runtime, filename, data, mime_type, *, description=None, json_type=None, metadata=None) -> SavedArtifact`; `description` goes to the item and the reference (default `"<filename> (version N)"`), and `json_type` and the `metadata` entries go to the item properties and the reference metadata.
- `SavedArtifact(item_id, file_id, version, uri, filename, mime_type, artifact_id)`; `artifact_id` is the registry artifact ID, stored on the item as the property `artifact_id`.
- `merge_item_properties(dl, item_id, properties, *, name=None, description=None) -> Item` merges `properties` into the properties of a DeepLynx item and writes the item back.
- `load_artifact(runtime: ToolRuntime[PrometheusContext], item_id: int) -> LoadedArtifact`
- `ProvenanceMiddleware`, an `AgentMiddleware` with `awrap_tool_call` and `aafter_agent`.
- `summarization(client)` returns a `SummarizationMiddleware` on `PrometheusChatModel(alias="small", ...)`.
- `approval(card_skills, extra_tools=())` returns a `HumanInTheLoopMiddleware` for the approval tools, or `None` when there are none.
- `LangGraphPrometheusAgent(PrometheusAgent)` with `model_alias`, `approval_tools`, `skill_tools()`, `system_prompt(skill_id)`, `checkpointer()`, `build_graph(skill_id, model, checkpointer)` and `_execute(params, context, event_queue)`.
- `LANGGRAPH_CHECKPOINT_DB_URL`: the psycopg connection string of the `AsyncPostgresSaver`; empty means `InMemorySaver`, which cannot resume after a restart, and the agent logs one warning.
- `LANGGRAPH_SUMMARY_TRIGGER_TOKENS` (default `24000`) and `LANGGRAPH_SUMMARY_KEEP_MESSAGES` (default `20`): the summarization trigger and the count of kept messages.

## Constraints
- The checkpoint `thread_id` is the A2A task ID, one thread per task.
- The idempotency key of a save in a tool call is `{thread_id}:{tool_call_id}:{filename}`; a save outside a tool call has no key and always creates a new item.
- The item properties of a saved artifact are `artifact_key`, `version`, `sha256`, `idempotency_key`, `mime_type`, `filename`, `file_id` and `artifact_id`; they win over a `json_type` or `metadata` entry of the same name.
- A repeated save in the same tool call returns the item, the version and the `artifact_id` of the first save, and sends no second reference.
- `save_artifact` and `load_artifact` raise `RuntimeError` when no DeepLynx storage is configured; there is no local fallback.
- A paused run keeps its execution record open; a tool exception closes the record `failed` and re-raises.
- The module writes to the execution record that the executor creates and MUST NOT create a second record.
- Semantic aliases stay in agent code; the module sends no provider key, URL or model ID.
- `pyproject.toml` pins `psycopg[binary]` directly, because the `AsyncPostgresSaver` needs a psycopg driver and the `binary` extra ships its prebuilt wheels.

## Out of scope / Non-goals
- A multi-replica lease or a stale-writer check on the checkpointer; the OSS Postgres saver is a plain upsert, so the prototype runs one replica.
- Cross-pod cancel and a cancel middleware.
- A background run service, a memory service, and a workflow compiler.
- Credential middleware, `child_of` edges, and token usage on the execution record.
- LangSmith Deployment, LangSmith tracing, LangGraph Studio and `langgraph.json`.
- Token streaming from the model.

## Open questions
- None.
