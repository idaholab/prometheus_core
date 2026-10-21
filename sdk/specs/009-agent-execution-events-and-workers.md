# 009 — Agent execution, events, and workers

status: implemented
sources: docs/agent/GUIDE.md, prometheus_api/agent/base.py, prometheus_api/agent/events.py, prometheus_api/agent/worker.py, tests/test_agent.py, tests/test_a2a_payloads.py
depends-on: none

## Purpose
Define the standard A2A task lifecycle for Prometheus agents, including parameter extraction, status/finalization, heartbeats, background hints, cancellation, and blocking-work offload.

## Requirements
- REQ-009-01: `PrometheusAgentExecutor._extract_params(...)` MUST parse JSON object text as params, wrap JSON non-objects as `{"value": ...}`, wrap invalid JSON/plain text as `{"message": text}`, and return `{}` for empty input.
- REQ-009-02: Parameter extraction MUST inject `skill_id` from `message.metadata.skillId` when present and not already provided.
- REQ-009-03: Parameter extraction logs MUST include only sorted parameter keys and MUST NOT log prompt or credential values.
- REQ-009-04: Executor `execute(...)` MUST emit an initial non-final `working` status before calling `_execute(...)`.
- REQ-009-05: Executor `execute(...)` MUST emit a final `completed` status whose text message is JSON serialized from the returned dict, unless `_execute(...)` already emitted a final status.
- REQ-009-06: If `_execute(...)` raises before finalization, executor `execute(...)` MUST emit a final `failed` status and re-raise the exception.
- REQ-009-07: `cancel(...)` MUST emit a final `canceled` status event.
- REQ-009-08: Heartbeat interval MUST default to 15 seconds and MUST reject non-numeric or non-positive `PROMETHEUS_HEARTBEAT_INTERVAL` values.
- REQ-009-09: While `_execute(...)` is running, the executor MUST emit silent non-final `working` heartbeat events tagged `metadata.heartbeat=True`; heartbeat emit failures MUST NOT fail task execution.
- REQ-009-10: `send_status_update(...)` MUST route status construction through shared event helpers.
- REQ-009-11: `declare_long_running(...)` MUST emit a non-final `working` status tagged `metadata.background=True`, include optional `estimate_seconds`, merge extra metadata, and provide a default message when none is supplied.
- REQ-009-12: `PrometheusAgent.create_executor()` MUST return a `DelegatingPrometheusAgentExecutor` that delegates work to the agent's `_execute(...)`.
- REQ-009-13: `PrometheusAgent.run_worker(...)` MUST execute `PrometheusWorker.run()` off the event loop, forward queued worker events, return the worker result, propagate worker exceptions, and set cooperative cancellation on caller cancellation.
- REQ-009-14: `PrometheusWorker.emit_status_update(...)` MUST queue non-final status events only after the worker has been bound through `run_worker(...)`.
- REQ-009-15: `PrometheusWorker.emit_json_artifact(...)` MUST queue inline JSON artifact events and return/reuse the artifact ID, but MUST NOT perform catalog registration or loop-bound I/O.
- REQ-009-16: A standard `PrometheusAgent` execution MUST create one DeepLynx item after identity verification and parameter extraction, but before emitting the initial `working` status or invoking `_execute(...)`.
- REQ-009-17: The execution item MUST be created with a just-in-time `deeplynx` credential and MUST contain a versioned schema identifier, agent name, normalized producer agent ID, authenticated user ID, task ID, context ID, creation timestamp, and the effective parameters passed to `_execute(...)`.
- REQ-009-18: Secret-bearing values in execution-record parameters MUST be recursively redacted with the shared LLM security redactor while preserving the parameter structure; the unredacted effective parameters MUST still be passed to `_execute(...)`.
- REQ-009-19: A verified identity MUST overwrite any caller-provided `user_id` parameter. Execution-record metadata MUST derive the authenticated user from the active verified identity, never from untrusted request data.
- REQ-009-20: If credential acquisition, storage configuration, or execution-item creation fails, the executor MUST emit its normal terminal failure and MUST NOT invoke `_execute(...)`.
- REQ-009-21: `PrometheusAgent.execution_record_id` MUST expose the created DeepLynx item ID only within the active execution scope and MUST isolate concurrent executions and reset after success or failure.

## Behavior
- BEH-009-01: GIVEN a slow `_execute(...)` and a short heartbeat interval WHEN execution runs THEN at least one silent non-final heartbeat is emitted before the final completed event.
- BEH-009-02: GIVEN `_execute(...)` emits a final status WHEN it returns a dict THEN the executor skips automatic finalization and does not emit a contradictory terminal event.
- BEH-009-03: GIVEN a worker emits status, artifact, and status events WHEN `run_worker(...)` completes THEN those events are forwarded in order and the worker result is returned.
- BEH-009-04: GIVEN an authenticated standard agent request WHEN execution begins THEN one execution item is created before agent work and `_execute(...)` can read that item's ID from `self.execution_record_id`.
- BEH-009-05: GIVEN a request parameter containing a spoofed `user_id` and nested credentials WHEN the execution item is created THEN both the item and `_execute(...)` use the verified user ID, while only the persisted parameter snapshot has credential values redacted.
- BEH-009-06: GIVEN concurrent requests on one agent instance WHEN both execute THEN each invocation observes only its own execution-record ID and neither ID remains bound after its invocation ends.
- BEH-009-07: GIVEN DeepLynx execution-item creation fails WHEN execution begins THEN the task fails before `_execute(...)` runs.

## Interfaces
- `MissingInput` is owned by spec 010.
- `PrometheusAgentExecutor(agent_name: str = "Agent")`
- `PrometheusAgentExecutor.execute(context: RequestContext, event_queue: EventQueue) -> None`
- `PrometheusAgentExecutor.cancel(context: RequestContext, event_queue: EventQueue) -> None`
- `PrometheusAgentExecutor._execute(params: dict[str, Any], context: RequestContext, event_queue: EventQueue) -> dict[str, Any]`
- `DelegatingPrometheusAgentExecutor(agent_name: str, execute_fn: Callable[..., Awaitable[dict[str, Any]]], execution_scope: Callable[..., AsyncContextManager[None]] | None = None)`
- `PrometheusAgent.execution_record_id -> int | None`
- `PrometheusAgent._execute(params: dict[str, Any], context: RequestContext, event_queue: EventQueue) -> dict[str, Any]`
- `PrometheusAgent.send_status_update(context, event_queue, state: TaskState = TaskState.working, final: bool = False, message: str | None = None, metadata: dict | None = None) -> None`
- `PrometheusAgent.declare_long_running(context, event_queue, *, estimate_seconds: float | None = None, message: str | None = None, metadata: dict | None = None) -> None`
- `PrometheusAgent.run_worker(worker: PrometheusWorker, context: RequestContext, event_queue: EventQueue, *, poll_interval: float = 0.5) -> dict[str, Any]`
- `PrometheusWorker(mailbox_size: int = 256)`
- `PrometheusWorker.drain() -> list[Any]`, `cancel() -> None`, `cancelled -> bool`
- `PrometheusWorker.emit_status_update(message: str | None = None, *, state: TaskState = TaskState.working, metadata: dict | None = None) -> None`
- `PrometheusWorker.emit_json_artifact(payload: Any, *, name: str = "result", description: str | None = None, json_type: str | None = None, artifact_id: str | None = None, append: bool = False, last_chunk: bool | None = None, metadata: dict | None = None) -> str`
- `PrometheusWorker.run() -> dict[str, Any]`
- `utc_now_iso() -> str`, `normalize_producer_agent_id(agent_name: str) -> str`, `build_artifact_metadata(...) -> dict`, `context_task_id(context) -> str`, `context_id(context) -> str`
- `build_status_update_event(...) -> TaskStatusUpdateEvent`, `emit_status_update(...) -> None`, `build_data_artifact_event(...) -> tuple[TaskArtifactUpdateEvent, str]`

## Constraints
- Blocking SDK calls and CPU work SHOULD be run through `run_worker(...)` or another off-loop mechanism so A2A streaming and heartbeat events keep flowing.
- Status updates are transient progress; durable user-visible messages should use artifact/conversation helpers in spec 010.
- Worker APIs intentionally expose only pure event construction; operations requiring async I/O must stay on the event loop.

## Out of scope / Non-goals
- The executor does not validate the semantic content of returned result dicts.
- Worker threads cannot be force-killed; cancellation is cooperative only.

## Open questions
- Runtime enforcement that `_execute(...)` returns a dict is not explicit; non-dict returns serialize but violate the guide.
- Heartbeats are silent by design, but downstream UIs must continue ignoring `metadata.heartbeat` events to avoid progress noise.
