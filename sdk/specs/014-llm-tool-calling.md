# 014 — LLM tool calling

status: implemented
sources: prometheus_api/llm_client/tools.py, prometheus_api/llm_client/client.py, prometheus_api/llm_client/models.py, prometheus_api/llm_client/normalization.py, prometheus_api/llm_client/exceptions.py, prometheus_api/llm_client/__init__.py, tests/unit/test_llm_tools.py, tests/unit/test_llm_client.py, docs/agent/LLM_CLIENT_MIGRATION.md, examples/llm_tool_calling_usage.py
depends-on: 005, 006, 007

## Purpose
Give agents one canonical, provider-agnostic way to declare tools, read tool calls off a chat
response, and replay tool results into conversation history, so consumers stop hand-rolling
shape-tolerant tool-call parsers against `ChatResponse.raw`.

## Requirements
- REQ-014-01: `ToolCall` MUST be a frozen dataclass exposing `id`, `name`, `arguments`, `arguments_error`, and `raw`, where `arguments` is an already-decoded JSON object, and MUST be hashable despite its dict-valued `arguments` (hashing `id`, `name`, canonically encoded `arguments`, and `arguments_error`, excluding `raw`).
- REQ-014-02: `parse_tool_calls(value)` MUST accept a `ChatResponse` or a raw provider payload, MUST read `choices[0].message.tool_calls` from both mapping-shaped proxy payloads and attribute-shaped LiteLLM responses, MUST return an empty tuple when choices, message, or tool calls are absent or when `tool_calls` is not a non-string sequence, and MUST NOT raise for provider-shaped input.
- REQ-014-03: Tool-call argument decoding MUST accept a JSON-object string or a mapping, MUST copy mappings, MUST decode a missing, `None`, or blank value to `arguments == {}` with no `arguments_error`, and MUST record a non-null `arguments_error` with `arguments == {}` for any other value that is not a decodable JSON object rather than raising.
- REQ-014-04: `parse_finish_reason(value)` MUST return `choices[0].finish_reason` as a string when present and `None` otherwise.
- REQ-014-05: `assistant_message(response)` MUST return a replayable assistant message carrying the provider `tool_calls` verbatim with `role` set to `assistant`, MUST NOT substitute placeholder text for missing or null `content`, and MUST drop null-valued fields identically for mapping-shaped and object-shaped messages; it MUST raise `LLMToolCallError` when the response contains no completion message.
- REQ-014-06: `tool_result_message(call, result)` MUST return `{"role": "tool", "tool_call_id": <id>, "content": <text>}`, MUST accept a `ToolCall` or a call-id string, MUST JSON-encode non-string results with `default=str`, and MUST replace a blank or whitespace-only content string with the placeholder `"(empty result)"` so replay passes chat normalization.
- REQ-014-07: `require_tool_calls(response, *, expected=None, count=None)` MUST raise `LLMToolCallError` when the response has no tool calls, when any call has a blank `id` or `name`, when any call carries an `arguments_error`, when a call name falls outside `expected`, or when the call count differs from `count`.
- REQ-014-08: `ToolDefinition` MUST expose `name`, `description`, and `parameters`; `as_schema()` MUST return `{"type": "function", "function": {"name", "description", "parameters"}}`; and `from_pydantic(name, model, description=...)` MUST build `parameters` from the model's `model_json_schema()`.
- REQ-014-09: `tool_schemas(definitions)` MUST convert `ToolDefinition` values to OpenAI function schemas and MUST pass mapping schemas through unchanged so hand-built tool dictionaries keep working.
- REQ-014-10: `LLMToolCallError` MUST subclass `LLMClientError` so tool failures stay in the existing `RuntimeError` tree rather than the `LLMAliasError` `ValueError` tree.
- REQ-014-11: `prometheus_api.llm_client.__all__` MUST export `ToolCall`, `ToolDefinition`, `LLMToolCallError`, `parse_tool_calls`, `parse_finish_reason`, `assistant_message`, `tool_result_message`, `require_tool_calls`, `tool_schemas`, `call_tool`, and `acall_tool`.
- REQ-014-12: `llm_client/tools.py` MUST NOT import `llm_client/client.py` at runtime so the client can import tool parsing without a circular import.
- REQ-014-13: `call_tool(client, ...)` and `acall_tool(client, ...)` MUST force one named tool with `tool_choice={"type": "function", "function": {"name": <name>}}`, MUST return exactly one validated `ToolCall`, and MUST raise `LLMToolCallError` for zero, multiple, mismatched, or undecodable calls.
- REQ-014-14: `acall_tool(...)` MUST produce the same request payload, return value, and error behavior as `call_tool(...)`.

## Behavior
- BEH-014-01: GIVEN a proxy chat response whose `choices[0].message` has `content: null` and one `tool_calls` entry WHEN chat returns THEN `ChatResponse.text` is `""`, `finish_reason` is `"tool_calls"`, and `tool_calls` holds one decoded `ToolCall`.
- BEH-014-02: GIVEN a tool call whose `arguments` is `"{not json"` WHEN the response is parsed THEN the `ToolCall` has `arguments == {}` and a non-null `arguments_error` and no exception is raised.
- BEH-014-03: GIVEN a LiteLLM object response with attribute-shaped tool calls WHEN `assistant_message(...)` builds history THEN the message keeps `content: None` plus its `tool_calls` and `normalize_messages(...)` accepts it.
- BEH-014-04: GIVEN a response whose only tool call carries an `arguments_error` WHEN `require_tool_calls(...)` runs THEN `LLMToolCallError` is raised.
- BEH-014-05: GIVEN a hand-built `{"type": "function", ...}` mapping WHEN it is passed through `tool_schemas(...)` THEN it is returned unchanged.
- BEH-014-06: GIVEN `call_tool` with one `ToolDefinition` WHEN the model returns two tool calls THEN `LLMToolCallError` is raised.

## Interfaces
- `ToolCall(id: str, name: str, arguments: dict[str, Any], arguments_error: str | None = None, raw: Any = None)`
- `ToolDefinition(name: str, description: str = "", parameters: dict[str, Any] = ...)`
- `ToolDefinition.as_schema() -> dict[str, Any]`
- `ToolDefinition.from_pydantic(name: str, model: type[BaseModel], *, description: str = "") -> ToolDefinition`
- `tool_schemas(definitions: Iterable[ToolDefinition | Mapping[str, Any]]) -> list[dict[str, Any]]`
- `parse_tool_calls(value: ChatResponse | Any) -> tuple[ToolCall, ...]`
- `parse_finish_reason(value: ChatResponse | Any) -> str | None`
- `assistant_message(response: ChatResponse) -> dict[str, Any]`
- `tool_result_message(call: ToolCall | str, result: Any) -> dict[str, Any]`
- `require_tool_calls(response: ChatResponse, *, expected: Sequence[str] | None = None, count: int | None = None) -> tuple[ToolCall, ...]`
- `call_tool(client: LLMClient, text_or_messages, *, tool: ToolDefinition | Mapping[str, Any], model: str | None = None, **kwargs) -> ToolCall`
- `acall_tool(client: AsyncLLMClient, text_or_messages, *, tool: ToolDefinition | Mapping[str, Any], model: str | None = None, **kwargs) -> ToolCall`
- `LLMToolCallError`

## Constraints
- Sync and async tool helpers MUST stay aligned for request payloads, return values, and error behavior, per the parity constraint in 006.
- Tool names and JSON schemas are developer-authored; tool-call arguments are model-authored and MUST be treated as untrusted input for logging and tracing.
- Tool calling is a per-call chat capability. It MUST NOT introduce a YAML flavor alias and MUST NOT change the six-flavor contract in REQ-005-16.
- `ChatResponse` field additions MUST carry defaults and be appended after `raw` so existing positional and keyword construction in downstream projects keeps working.
- `parse_tool_calls(...)` is lenient by design so `chat(...)` never fails on model-authored output; `require_tool_calls(...)` is the single strict gate.
- `finish_reason` MUST NOT be used to terminate a multi-turn tool conversation. The terminator is the absence of tool calls (`not response.tool_calls`), because some providers return `finish_reason == "stop"` alongside tool calls and treating that as terminal silently discards them. `finish_reason` is reported for observability, not for control flow.
- Callers that drive their own multi-turn tool conversation MUST bound the number of turns. Each turn is a billed request with growing context, so an unbounded loop has no cost ceiling.

## Out of scope / Non-goals
- Streaming tool-call deltas. `stream=True` is rejected rather than supported; see REQ-006-18.
- A tool-execution loop, a dispatch mapping, and concurrent dispatch of multiple tool calls in one turn. Callers compose the primitives themselves; the required termination and bounding rules are in Constraints, with a worked loop in `examples/llm_tool_calling_usage.py` and `docs/agent/LLM_CLIENT_MIGRATION.md`.
- Provider-native structured-output modes such as `response_format` or `strict` JSON schemas, beyond forced single tool calls.
- A tool registry, permission model, sandbox, or audit trail for tool execution.
- Retry policy for tool calls.
- MCP or A2A tool discovery and remote tool invocation.

## Open questions
- Provider variance for the replayed assistant tool-call message: whether explicit `content: null` or an absent `content` key is accepted is provider-specific. This package sends explicit `null`, untested against every installed profile.
- `parse_tool_calls(...)` returns an empty tuple when `choices` is absent, while two existing consumers raise in that case. Consumers migrating to `require_tool_calls(...)` keep raising; consumers reading `ChatResponse.tool_calls` directly do not.
- A tool call with a blank `id` cannot produce a valid `tool_call_id` on a follow-up message. `require_tool_calls(...)` rejects it rather than fabricating an id.
- `redact_secrets(...)` is pattern-based; a model-authored argument value containing whitespace is only partially redacted inside a JSON-string payload.
- `assistant_message` is a broad name for a package-level export; `response_to_message` was considered.
- A package-owned tool-execution loop is deferred, not rejected. Implement it when either a second consumer inside this package needs one, or a caller confirms that an external-state stop predicate plus an empty-turn hook covers its policy; a loop that cannot express those is a partial helper that callers will bypass.
- No integration coverage against a live LiteLLM proxy or provider; all evidence is unit-level with stubbed transports, so the LiteLLM object shape is validated against a stub rather than a real `ModelResponse`.
