# 011 — A2A conversation contract and streams

status: implemented
sources: prometheus_api/contract.py, prometheus_api/a2a_stream.py, prometheus_api/agent/__init__.py, tests/unit/test_contract.py, tests/unit/test_a2a_stream.py, tests/unit/test_a2a_payloads.py
depends-on: 008, 009, 010

## Purpose
Provide dependency-light payload models and stream consumption helpers shared by the frontend, client-agent, and other callers that need to collapse A2A stream events into task results.

## Requirements
- REQ-011-01: `ConversationStatus.values()` MUST return exactly `needs_info`, `plan_ready`, `executing`, `completed`, `recommendation`, `answer`, `backgrounded`, and `error`.
- REQ-011-02: `ConversationRequest` MUST ignore unknown fields and default optional workflow, artifact, upload, follow-up, and approval fields as defined by the model.
- REQ-011-03: `ConversationResponse` MUST validate status against `ConversationStatus`, store status as a plain string after validation, ignore unknown fields, and default status to `answer`.
- REQ-011-04: `ConversationRequest`, `ConversationResponse`, and `ConversationStatus` MUST be re-exported from `prometheus_api.agent`.
- REQ-011-05: `new_task_accumulator()` MUST return a task accumulator with an empty artifact list.
- REQ-011-06: `extract_status_message_text(...)` MUST extract non-empty text from direct A2A v1 `Part.text` fields, ignore valid non-text parts, and raise `A2AStreamError` for malformed or pre-v1 part shapes.
- REQ-011-07: `merge_artifacts(...)` MUST preserve order, deduplicate keyed artifacts by `artifactId` falling back to `name`, and retain unkeyed artifact entries.
- REQ-011-08: `apply_stream_event(...)` MUST raise `A2AStreamError` for envelopes with `error` or malformed results, skip heartbeat events, and invoke `background_callback` for `metadata.background` events.
- REQ-011-09: A2A v1 `statusUpdate` events MUST update accumulated task ID, context ID, and status; non-terminal text status updates MUST invoke `status_callback`.
- REQ-011-10: A2A v1 `artifactUpdate` events MUST merge the incoming artifact into the accumulated artifact list.
- REQ-011-11: `consume_stream_response(...)` MUST support `application/x-ndjson` and `text/event-stream`, including SSE comments and multiline `data:` blocks, and MUST reject unsupported content types.
- REQ-011-12: `stream_a2a_request(...)` MUST POST JSON with `Content-Type: application/json`, accept SSE or NDJSON, enforce a default 900-second client timeout, raise non-success HTTP responses, and return the accumulated task.
- REQ-011-13: Hosted A2A agents SHOULD handle large request payloads up to the configured SDK content limit and return JSON-RPC payload-too-large errors when that limit is exceeded.
- REQ-011-14: Concurrent A2A streaming sends to the same conversation MUST keep per-request final results isolated.
- REQ-011-15: Stream parsing MUST accept only A2A v1 `task`, `statusUpdate`, and `artifactUpdate` result envelopes and MUST raise `A2AStreamError` for pre-v1 dashed event-kind shapes.
- REQ-011-16: Stream parsing MUST preserve exact A2A v1 ProtoJSON `TASK_STATE_*` enum values in accumulated task statuses and MUST reject missing, lowercase, or otherwise invalid state values instead of normalizing them.

## Behavior
- BEH-011-01: GIVEN a status stream with one progress event and one final event WHEN consumed THEN only the non-final progress text is sent to `status_callback`.
- BEH-011-02: GIVEN an SSE stream ending without a trailing blank line WHEN consumed THEN the final data block is still flushed and applied.
- BEH-011-03: GIVEN a heartbeat status event WHEN applied THEN it does not overwrite the previously accumulated status.
- BEH-011-04: GIVEN a pre-v1 dashed event-kind result WHEN applied THEN `A2AStreamError` is raised.
- BEH-011-05: GIVEN a status event with a non-v1 task-state spelling WHEN applied THEN `A2AStreamError` is raised.
- BEH-011-06: GIVEN a status message containing a pre-v1 root-wrapped part WHEN its text is extracted THEN `A2AStreamError` is raised.

## Interfaces
- `ConversationStatus(str, Enum)`
- `ConversationStatus.values() -> list[str]`
- `ConversationRequest(BaseModel)`
- `ConversationResponse(BaseModel)`
- `ConversationResponse.from_payload(data: dict[str, Any]) -> ConversationResponse`
- `A2AStreamError`
- `new_task_accumulator() -> dict[str, Any]`
- `extract_status_message_text(status_payload: Any) -> str`
- `merge_artifacts(existing: list[dict] | None, incoming: list[dict] | None) -> list[dict]`
- `apply_stream_event(a2a_result: dict, envelope: dict, *, status_callback: StatusCallback | None = None, background_callback: BackgroundCallback | None = None) -> dict`
- `consume_stream_response(response: httpx.Response, *, status_callback: StatusCallback | None = None, background_callback: BackgroundCallback | None = None) -> dict`
- `stream_a2a_request(endpoint: str, message: dict[str, Any], *, headers: dict[str, str] | None = None, timeout_seconds: float = 900.0, status_callback: StatusCallback | None = None, background_callback: BackgroundCallback | None = None) -> dict`

## Constraints
- `prometheus_api.contract` and `prometheus_api.a2a_stream` MUST stay dependency-light and avoid importing the agent runtime.
- Heartbeat events are connection keepalives, not user-facing status.
- Stream callbacks run inline; exceptions from callbacks propagate to callers.

## Out of scope / Non-goals
- This package does not define frontend rendering policy for plans, reports, recommendations, or artifact displays.
- Stream helpers do not implement automatic reconnect or resume.

## Open questions
- Payload-size behavior is validated through the A2A SDK app stack, not a local helper; SDK defaults may change and should be tracked.
- The contract models intentionally ignore unknown fields, so drift detection requires spec review rather than parser failures.
