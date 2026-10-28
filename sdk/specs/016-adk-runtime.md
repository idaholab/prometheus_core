# 016 — ADK runtime

status: implemented
sources: prometheus_api/adk/__init__.py, prometheus_api/adk/model.py, prometheus_api/adk/artifacts.py, prometheus_api/adk/memory.py, prometheus_api/adk/retrieval.py, prometheus_api/adk/runner.py, prometheus_api/adk/agent.py, prometheus_api/adk/plugins/__init__.py, prometheus_api/adk/plugins/bridge.py, prometheus_api/adk/plugins/provenance.py, prometheus_api/adk/plugins/compaction.py, prometheus_api/adk/plugins/approval.py, prometheus_api/adk/plugins/cancel.py, prometheus_api/adk/plugins/credentials.py, prometheus_api/agent/base.py, tests/test_adk_model.py, tests/test_adk_artifacts.py, tests/test_adk_provenance.py, tests/test_adk_compaction.py, tests/test_adk_approval.py, tests/test_adk_cancel.py, tests/test_adk_credentials.py, tests/test_adk_memory.py, tests/test_adk_retrieval.py, tests/test_adk_runner.py, tests/test_adk_agent.py
depends-on: 003, 006, 009, 010

## Purpose
Run Google ADK 2.13.0 inside every Prometheus agent while `PrometheusAgent` and A2A remain the contract between agents, and DeepLynx remains the store of record. `prometheus_api.adk` gives every agent the same model, sessions, artifacts, memory and plugins from one factory, `build_runner()`.

## Requirements
- REQ-016-01: `prometheus_model(alias, client)` MUST return an ADK `LiteLlm` whose every completion goes through the given `AsyncLLMClient.chat` with that alias and the request's tool declarations, and MUST NOT carry a provider URL, key or model ID.
- REQ-016-02: `DeepLynxArtifactService.save_artifact` MUST create one new DeepLynx item for each save, with the version, the SHA-256, the idempotency key and a `generated` relation from the current execution record, and MUST NOT update or delete an existing artifact item.
- REQ-016-03: The provenance plugin MUST add an `input_to` relation from each artifact named in the parameters or loaded during the run to the execution record of spec 009 (REQ-009-16), a `child_of` relation to the parent record named in the message metadata, and MUST close that record once with its status, end time, token use and tool-call log.
- REQ-016-04: When the prompt tokens pass the trigger ratio, the compaction plugin MUST replace the middle of the outgoing request with one reference-only summary and MUST keep every artifact ID, `deeplynx://` URI and tool-call ID of the dropped events in that request, without changing the stored session events.
- REQ-016-05: The approval plugin MUST pause a tool whose skill has `requires_approval: true` with `request_confirmation` before the tool runs, MUST run it only after a confirmation, and MUST return a rejected result without running it after a rejection.
- REQ-016-06: After the run's abort signal is set, the cancel plugin MUST block every new tool call, MUST call `cancel()` on the run's registered workers, and the run MUST end with the execution record closed as `cancelled` and the IDs of the artifacts that finished.
- REQ-016-07: The credential plugin MUST get a credential from `PrometheusAgent.get_credential` for each tool that declares a `credential_resource`, MUST give it to that call only, and MUST NOT write the value to session state, events or logs.
- REQ-016-08: `PrometheusMemoryService.add_session_to_memory` MUST store a procedure only for a run whose execution record closed `succeeded`, and `search_memory` MUST NOT return a procedure whose required tools the calling agent does not have.
- REQ-016-09: The `retrieve` tool MUST return each result with its source, item ID, URI, score and version, marked untrusted, from the configured `RetrievalBroker`.
- REQ-016-10: `build_runner()` MUST return a resumable ADK runner with the DeepLynx artifact service, the database session service from `ADK_SESSION_DB_URL`, the Prometheus memory service and the bridge, provenance, credential, approval, cancel and compaction plugins, and MUST leave out the compaction plugin when `compaction=None`.
- REQ-016-11: `AdkPrometheusAgent` MUST run the ADK node mapped to the request's `skill_id`, MUST fail at startup when a card skill has no node and no `_execute` handling or a node has no card skill, and MUST send the same A2A status and artifact events as `send_status_update` and `send_artifact_reference`.
- REQ-016-12: An `AdkPrometheusAgent` run on the database session service MUST resume after its process is killed, with the same `invocation_id`, without running a finished step again and without a second DeepLynx item or job for a repeated tool call.

## Behavior
- BEH-016-01: GIVEN a tool call that already saved `mesh.exo` WHEN the resumed run saves it again with the same `invocation_id` and `function_call_id` THEN no second item is created and the first version number is returned.
- BEH-016-02: GIVEN a running ADK skill WHEN the A2A executor's `cancel` is called THEN `on_cancel` sets that task's abort event before the `canceled` status is emitted.

## Interfaces
- `AdkPrometheusAgent(PrometheusAgent)` with `adk_agents: dict[str, BaseNode]`, `long_running: dict[str, int]`, `compaction: CompactionPolicy | None = CompactionPolicy()` and `async on_cancel(context) -> None`
- `build_runner(agent: PrometheusAgent, context: RequestContext, root: BaseNode, *, event_queue: EventQueue, compaction: CompactionPolicy | None = CompactionPolicy(), extra_plugins: Sequence[BasePlugin] = (), test: bool = False, abort_signal: asyncio.Event | None = None, summarizer_model: BaseLlm | None = None, bridge_events: bool = True) -> Runner`
- `CompactionPolicy` (dataclass): `trigger_ratio: float = 0.7`, `tail_tokens: int = 8000`, `cooldown_calls: int = 3`, `input_windows` (per alias, default `small` 32000, `medium` 128000, `large` 128000), `default_input_window: int = 32000`
- `PrometheusLlm`
- `prometheus_model(alias: str, client: AsyncLLMClient) -> LiteLlm`
- `DeepLynxArtifactService(BaseArtifactService)`
- `PrometheusMemoryService(BaseMemoryService)`
- `RetrievalBroker` (`Protocol`): `async search(query, *, user_id, limit) -> list[RetrievedChunk]`
- `retrieve_tool(broker: RetrievalBroker) -> FunctionTool`
- `ADK_SESSION_DB_URL`
- A2A message metadata key `prometheusParentExecutionRecordId` (`PARENT_EXECUTION_RECORD_METADATA_KEY`, defined in the dependency-light `prometheus_api.contract`)
- `files.upload_bytes(...)` is owned by spec 003; `PrometheusAgent.on_cancel(...)` and `PrometheusAgentExecutor.cancel(...)` are owned by spec 009.

## Constraints
- The ADK pin is exact: `google-adk==2.13.0`.
- Each skill gets its own ADK `App` and `Runner`; all of them share one app name and the same session, artifact and memory services.
- ADK's built-in `EventsCompactionConfig` stays off (`events_compaction_config=None`); the compaction plugin rewrites only the outgoing `LlmRequest.contents`.
- An empty `ADK_SESSION_DB_URL` gives in-memory sessions with one warning, as spec 012 degrades Redis state.
- `DeepLynxArtifactService` never calls `items.delete`; `delete_artifact` creates a `tombstone` item, and no `supersedes` relation is written.
- The provenance plugin never creates a second execution record; it extends the record of spec 009 (REQ-009-16 to REQ-009-21).

## Out of scope / Non-goals
- Approval gates 3 and 4 of PPLT-114, backend credential provisioning and the approval UI (PPLT-32).
- A backend cancel route and a Stop control in the UI (PPLT-140).
- Compaction archive to Valkey (PPLT-89), and PPLT-91 and PPLT-92.
- MACLA memory scoring, a federated retrieval registry and vector search.

## Open questions
- Postgres ADK sessions depart from the Glossary, which puts session state in Valkey; open until the Glossary row changes.
- Closing the execution record updates a DeepLynx item, which the white paper calls immutable; open until the white paper says so.
- Compaction is on by default, against PPLT-83 ("should never be enforced"); open until the PPLT-83 text changes.
