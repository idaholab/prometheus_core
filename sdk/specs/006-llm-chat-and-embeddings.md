# 006 — LLM chat and embeddings

status: implemented
sources: README.md, docs/ENV_SETUP.md, prometheus_api/llm_client/client.py, prometheus_api/llm_client/models.py, prometheus_api/llm_client/normalization.py, prometheus_api/llm_client/tools.py, tests/unit/test_llm_client.py
depends-on: 005

## Purpose
Provide provider-agnostic sync and async chat/embedding APIs that hide LiteLLM proxy and fallback differences behind normalized inputs and response objects.

## Requirements
- REQ-006-01: Chat input normalization MUST accept a non-empty string as one user message and a non-empty list of message dictionaries containing non-empty `role` and non-null/non-empty `content`, except as relaxed by REQ-006-15.
- REQ-006-02: Chat input normalization MUST reject empty strings, empty lists, non-dict message entries, missing `role`, empty roles, and missing, null, or empty-string `content` for any message not covered by REQ-006-15.
- REQ-006-03: Embedding input normalization MUST accept a non-empty string or non-empty list of non-empty strings and MUST report whether the original input was a single string.
- REQ-006-04: `LLMClient.__call__` and `AsyncLLMClient.__call__` MUST delegate to `chat(...)`.
- REQ-006-05: Retired. The default flavor is fixed rather than configurable through `LLMConfig`.
- REQ-006-06: Convenience methods `small`, `medium`, `large`, and `vision` MUST call chat with those aliases.
- REQ-006-07: Embedding methods MUST default to alias `embedding`, send a single string to providers when the caller supplied one string, send a list for list input, and return `EmbeddingResponse`.
- REQ-006-08: Proxy chat MUST POST to `/v1/chat/completions` with `{"model": alias, "messages": messages, ...kwargs}`.
- REQ-006-09: Proxy embedding MUST POST to `/v1/embeddings` with `{"model": alias, "input": input, ...kwargs}`.
- REQ-006-10: Fallback chat and embedding MUST call LiteLLM sync/async SDK functions with the configured provider model and fallback `litellm_params`.
- REQ-006-11: A proxy request-level `httpx.RequestError` MUST trigger fallback for the same alias; a reachable proxy `HTTPStatusError` MUST propagate and MUST NOT fallback.
- REQ-006-12: `ChatResponse` MUST expose `text`, `model_alias`, `provider_model`, `usage`, `raw`, `tool_calls`, and `finish_reason`; `EmbeddingResponse` MUST expose float vectors plus `model_alias`, `provider_model`, `usage`, and `raw`.
- REQ-006-13: `close()` and `aclose()` MUST close only HTTP clients owned by the LLM client. ⚠ untested
- REQ-006-14: Chat methods MUST select the caller-provided `model` or the fixed `default` flavor, pass normalized messages and caller kwargs to the backend, and return `ChatResponse`.
- REQ-006-15: Chat input normalization MUST accept a message with a missing, `None`, or empty-string `content` when its `role` is `assistant` (matched case-insensitively) and it carries a non-empty `tool_calls` list, MUST normalize that message's `content` to `None` when it is absent, null, or whitespace-only, and MUST continue rejecting every other missing, null, or empty-content case.
- REQ-006-16: New `ChatResponse` fields MUST be appended after `raw` with defaults `()` and `None` so existing positional and keyword construction in downstream projects keeps working.
- REQ-006-17: `LLMClient.chat(...)` and `AsyncLLMClient.chat(...)` MUST accept keyword-only `tools` and `tool_choice`, MUST convert `ToolDefinition` values to OpenAI function schemas while passing mapping schemas through unchanged, MUST send both in the proxy payload and the LiteLLM fallback kwargs, MUST omit the `tools` key when `tools` is empty, and MUST raise `LLMToolCallError` before contacting a backend when `tool_choice` is supplied without at least one tool.
- REQ-006-18: Chat methods MUST reject a truthy `stream` argument with `LLMClientError` before contacting any backend.

## Behavior
- BEH-006-01: GIVEN a sync proxy chat response with `choices[0].message.content` WHEN chat returns THEN `ChatResponse.text` is that content.
- BEH-006-02: GIVEN an async embedding response containing integer vectors WHEN embedding returns THEN vectors are converted to floats.
- BEH-006-03: GIVEN a configured fallback YAML and a down proxy WHEN chat or embedding is requested THEN the LiteLLM SDK path is used with the provider model.
- BEH-006-04: GIVEN an assistant message with `content: None` and one `tool_calls` entry followed by a `role: "tool"` reply WHEN the history is normalized THEN normalization succeeds and the assistant `content` stays `None`.
- BEH-006-05: GIVEN `stream=True` WHEN chat is called THEN `LLMClientError` is raised and no request reaches the proxy or the LiteLLM SDK.

## Interfaces
- `normalize_messages(value: str | list[dict[str, Any]]) -> list[dict[str, Any]]`
- `normalize_embedding_input(value: str | list[str]) -> tuple[list[str], bool]`
- `ChatResponse(text: str, model_alias: str, provider_model: str | None, usage: dict[str, Any] | None, raw: Any, tool_calls: tuple[ToolCall, ...] = (), finish_reason: str | None = None)`
- `EmbeddingResponse(embeddings: list[list[float]], model_alias: str, provider_model: str | None, usage: dict[str, Any] | None, raw: Any)`
- `LLMClient(config: LLMConfig | None = None, http_client: httpx.Client | None = None, *, app_name: str | None = None, trace_tags: Mapping[str, Any] | None = None)`
- `LLMClient.__enter__() -> LLMClient`, `__exit__(...) -> None`, `close() -> None`
- `LLMClient.list_models() -> list[str]`, `resolve_model(alias: str) -> str`
- `LLMClient.__call__(text_or_messages, **kwargs) -> ChatResponse`
- `LLMClient.chat(text_or_messages, model: str | None = None, trace_tags: Mapping[str, Any] | None = None, *, tools: Sequence[ToolDefinition | Mapping[str, Any]] | None = None, tool_choice: str | Mapping[str, Any] | None = None, **kwargs) -> ChatResponse`
- `LLMClient.small/medium/large/vision(text_or_messages, **kwargs) -> ChatResponse`
- `LLMClient.embedding(text_or_texts, **kwargs) -> EmbeddingResponse`
- `LLMClient.embed(text_or_texts, model: str = "embedding", **kwargs) -> EmbeddingResponse`
- `AsyncLLMClient(config: LLMConfig | None = None, http_client: httpx.AsyncClient | None = None, *, app_name: str | None = None, trace_tags: Mapping[str, Any] | None = None)`
- `AsyncLLMClient.__aenter__() -> AsyncLLMClient`, `__aexit__(...) -> None`, `aclose() -> None`
- `AsyncLLMClient.list_models/resolve_model/__call__/chat/small/medium/large/vision/embedding/embed`

## Constraints
- Sync and async LLM clients MUST stay aligned for alias selection, fallback behavior, request payloads, response fields, and logging hooks.
- Large or sensitive prompt content should not be logged by this capability; see 007 for logging and redaction rules.
- Fallback calls may include `api_base` or `base_url` only from call kwargs or fallback `litellm_params`.

## Out of scope / Non-goals
- This package does not stream token deltas (see REQ-006-18) and does not expose provider-native response classes as the primary contract.
- This spec does not define retry policy for LLM requests.

## Open questions
- HTTP client ownership is implemented but lacks direct tests for externally supplied clients.
- The `vision` alias is a chat alias only; there is no separate multimodal input schema beyond OpenAI-style message dictionaries.
- The REQ-006-15 relaxation permits missing content only for role `assistant` with a non-empty `tool_calls`; `role: "tool"` messages are not validated for `tool_call_id` presence.
