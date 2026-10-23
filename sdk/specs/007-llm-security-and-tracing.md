# 007 — LLM security and tracing

status: implemented
sources: README.md, docs/ENV_SETUP.md, prometheus_api/llm_client/security.py, prometheus_api/llm_client/tracing.py, prometheus_api/llm_client/client.py, tests/test_llm_client.py
depends-on: 005, 006

## Purpose
Keep LLM usage safe for agents and operators by redacting secrets, never taking LLM credentials from A2A requests, and making MLflow tracing opt-in.

## Requirements
- REQ-007-01: `redact_secrets(...)` MUST recursively redact dict fields whose names contain common secret fragments including `api_key`, `llm_api_key`, `authorization`, `token`, `secret`, and `password`.
- REQ-007-02: `redact_secrets(...)` MUST redact secret assignment patterns inside strings while preserving non-secret values.
- REQ-007-03: Retired. LLM clients MUST NOT read API keys from any part of an A2A request; credentials come only from `LLMConfig` and the environment. A request-independent credential provider will be specified separately.
- REQ-007-04: Retired with REQ-007-03 (`from_a2a_context(...)` is removed).
- REQ-007-05: Proxy requests MUST send `Authorization: Bearer <key>` when a transient config key or per-call `api_key` is provided.
- REQ-007-06: Debug logging MUST hide prompt and embedding content by default while still logging metadata such as alias, path, counts, roles, provider model, usage, and latency.
- REQ-007-07: When `debug_log_messages=True`, debug logging MAY include normalized prompt/embedding content only after secret redaction.
- REQ-007-08: MLflow MUST NOT be imported or configured when `ENABLE_MLFLOW_TRACING` is false.
- REQ-007-09: When tracing is enabled, setup MUST load `.env`, import MLflow, set `MLFLOW_EXPERIMENT_NAME` when present, enable `mlflow.litellm.autolog()`, and run setup only once.
- REQ-007-10: `enable_mlflow_x_api_key()` MUST inject `MLFLOW_API_KEY` as `X-Api-Key` into MLflow REST calls and warn when the env var is absent.
- REQ-007-11: Chat tracing MUST create spans named `llm_client.chat`, record model alias/provider/path/client attributes, record messages as inputs, record supplied tool names as inputs when tools are provided, set normalized response data including `finish_reason` as outputs, and add `tool_calls` to outputs only when the response contains tool calls.
- REQ-007-12: Trace tags `app_name`, `base_url`, and `model` MUST be protected and override caller-supplied tags.
- REQ-007-13: Tool-call arguments recorded in MLflow span outputs MUST pass through `redact_secrets(...)`, and full tool JSON schemas MUST NOT be recorded as span inputs.
- REQ-007-14: Debug logging for tool-calling chat MUST include tool names, tool count, tool-call count, and `finish_reason` while withholding model-authored tool-call arguments unless `debug_log_messages` is enabled, in which case they MUST be redacted.

## Behavior
- BEH-007-01: GIVEN an A2A request whose data parts contain `llm_api_key` WHEN `PrometheusAgent.llm_client(context)` creates a client THEN the client's config has no API key from the request.
- BEH-007-02: GIVEN debug logging without opt-in message logging WHEN a prompt contains sensitive content THEN logs include counts/roles but not prompt text.
- BEH-007-03: GIVEN tracing with caller tags that conflict with protected tags WHEN chat runs THEN protected `app_name`, `base_url`, and `model` values win.
- BEH-007-04: GIVEN tracing enabled and a tool-call response whose arguments contain an `api_key` value WHEN chat returns THEN span outputs include the tool call with redacted arguments.
- BEH-007-05: GIVEN tracing enabled and a response without tool calls WHEN chat returns THEN span outputs contain only `text`, `model_alias`, `provider_model`, `usage`, and `finish_reason`.

## Interfaces
- `redact_secrets(value: Any) -> Any`
- `MLFLOW_API_KEY_ENV = "MLFLOW_API_KEY"`
- `enable_mlflow_x_api_key() -> None`
- `setup_mlflow_tracing() -> Any`
- `chat_trace(enabled: bool, tags: Mapping[str, str], attributes: Mapping[str, Any], inputs: Mapping[str, Any]) -> Iterator[Any | None]`

## Constraints
- MLflow tracing remains opt-in because traces can record chat inputs and outputs.
- Credentials never travel as A2A parameters or data parts, so they cannot reach parameter logs, conversation state, or LLM transcripts.
- `MLFLOW_API_KEY` is specific to MLflow REST authentication (e.g. the AMSC MLflow server) and is not a model-provider API key; provider keys MUST NOT be sent to MLflow.

## Out of scope / Non-goals
- This package does not redact arbitrary semantic secrets outside the configured field fragments and assignment pattern.
- This package does not provide per-user or per-request LLM credentials; that is the job of a future credential provider.

## Open questions
- Redaction is pattern-based and may miss provider-specific secret field names that do not contain the configured fragments, including model-authored tool-call argument values that contain whitespace.
- Tracing support depends on the installed MLflow version exposing `mlflow.litellm` and `mlflow.entities.SpanType`.
