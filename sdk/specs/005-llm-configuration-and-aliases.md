# 005 — LLM configuration and aliases

status: implemented
sources: README.md, docs/ENV_SETUP.md, llm_config.example.yaml, prometheus_api/llm_configs/, prometheus_api/llm_client/config.py, prometheus_api/llm_client/client.py, prometheus_api/llm_client/exceptions.py, tests/test_llm_client.py, tests/test_llm_configs.py
depends-on: none

## Purpose
Let applications select LLM models through stable aliases while using an explicit, installed YAML configuration for either a LiteLLM proxy or a provider connection.

## Requirements
- REQ-005-01: Retired. The default model alias is no longer configurable and provider selection now comes from an LLM YAML configuration.
- REQ-005-02: When no explicit env mapping is supplied, `LLMConfig.from_env(...)` MUST load a `.env` file from the current working directory if present.
- REQ-005-03: Retired. Chat defaults to the fixed `default` flavor; it is not part of runtime configuration.
- REQ-005-04: `LLMConfig.with_api_key(...)` MUST return a shallow copy with a stripped transient API key and preserve the loaded fallback model cache.
- REQ-005-05: `LLMConfig.with_trace_options(...)` MUST merge trace tags, stringify non-null tag values, update `app_name` only when provided, and preserve the fallback model cache.
- REQ-005-06: Retired. Every `LLMConfig` now resolves an installed or explicitly selected YAML file.
- REQ-005-07: Fallback YAML MUST be a mapping with a list-shaped `model_list`; each valid entry MUST expose `model_name` and `litellm_params.model`.
- REQ-005-08: Fallback YAML parsing MUST resolve `os.environ/NAME` references when environment variables are available and MUST cache parsed aliases.
- REQ-005-09: Proxy alias discovery MUST read `/v1/models`, accept aliases from `id`, `model_name`, or `model`, deduplicate them, sort them, and cache them.
- REQ-005-10: `list_models()` MUST prefer proxy aliases when the selected configuration's `proxy_url` is reachable and fall back to its `model_list` aliases only when the proxy is unreachable.
- REQ-005-11: Missing aliases MUST raise `LLMAliasError` with the missing alias, available aliases, and an instruction to configure LiteLLM or the selected LLM config file.
- REQ-005-12: `resolve_model(alias)` MUST return the alias itself on the proxy path and the provider model name on the fallback path.
- REQ-005-13: The YAML files in `prometheus_api/llm_configs/` are the sole definition of the installed profiles (the profile name is the file stem); there is no separate profile list. The package MUST install at least the `registry` profile, and `get_llm_config_path(profile)` MUST return the package-owned path for an installed profile and reject unknown names.
- REQ-005-14: `LLMConfig.from_env(...)` MUST select the first available configuration in this order: `LLM_CONFIG_FILE`, `LLM_CONFIG_PROFILE`, then the installed `registry` profile.
- REQ-005-15: `LLMConfig` MUST resolve a top-level YAML `proxy_url`, including `os.environ/NAME` references, unless an explicit `proxy_url` constructor argument overrides it.
- REQ-005-16: Every direct-inference profile (any installed profile other than `registry`) MUST define `default`, `small`, `medium`, `large`, `vision`, and `embedding` aliases and MUST reference provider API keys through environment variables rather than embedding credentials. Every installed profile, including `registry`, MUST read its inference key from `LLM_API_KEY`; profiles whose provider supplies no embeddings MAY read the `embedding` flavor's key from `EMBEDDING_API_KEY`. Profiles for keyless local providers (e.g. Ollama) MAY set `api_key: none` instead of an environment reference.
- REQ-005-17: `LLMConfig.from_env(...)` MUST load `LLM_CONFIG_FILE`, `LLM_CONFIG_PROFILE`, `LLM_DEBUG_LOG_MESSAGES`, and `ENABLE_MLFLOW_TRACING`, trim string selectors, and convert truthy flag strings from `1`, `true`, `yes`, or `on`.

## Behavior
- BEH-005-01: Retired. Agent code owns flavor selection and chat without an explicit model always requests `default`.
- BEH-005-02: GIVEN a reachable proxy that lacks `default` WHEN default chat is requested THEN `LLMAliasError` lists the proxy aliases and does not consult fallback YAML.
- BEH-005-03: GIVEN a proxy connection error WHEN aliases are listed THEN fallback YAML aliases are returned if configured.
- BEH-005-04: GIVEN no LLM configuration selector WHEN `LLMConfig.from_env(...)` is called THEN the installed `registry` profile resolves `proxy_url` from `REGISTRY_URL`.
- BEH-005-05: GIVEN both `LLM_CONFIG_FILE` and `LLM_CONFIG_PROFILE` WHEN configuration is loaded THEN the explicit file wins.

## Interfaces
- `FallbackModelConfig(alias: str, provider_model: str, litellm_params: dict[str, Any])`
- `get_llm_config_path(profile: str = "registry") -> Path`
- `list_llm_config_profiles() -> tuple[str, ...]`
- `LLMConfig(proxy_url: str | None = None, config_file: Path | None = None, debug_log_messages: bool = False, enable_mlflow_tracing: bool = False, app_name: str | None = None, mlflow_trace_tags: dict[str, str] = {}, api_key: str | None = None, timeout: float = 30.0)`
- `LLMConfig.from_env(env: Mapping[str, str] | None = None, env_file: Path | None = None) -> LLMConfig`
- `LLMConfig.with_api_key(api_key: str | None) -> LLMConfig`
- `LLMConfig.with_trace_options(app_name: str | None = None, trace_tags: Mapping[str, Any] | None = None) -> LLMConfig`
- `LLMConfig.load_fallback_models() -> dict[str, FallbackModelConfig]`
- `LLMClientError`
- `LLMAliasError`

## Constraints
- The selected YAML determines whether the primary path is a proxy (`proxy_url`) or direct provider aliases (`model_list`). A file containing both keeps direct aliases as a degraded path used only when proxy discovery or calls fail with request-level unavailability.
- Installed profiles are package data and must remain readable from source, wheel, and container installs. Developer-specific `llm_config.yaml` files must remain untracked.
- Alias names are deployment configuration, not provider model names, on the proxy path.

## Out of scope / Non-goals
- Agent code chooses only semantic flavors. This package does not choose deployment-specific provider model names beyond reading the selected profile.
- This spec does not require proxy aliases to match fallback aliases.
- Tool calling is a per-call chat capability, not a model flavor. This spec does not define a `tools` alias and the six-flavor contract in REQ-005-16 is unchanged. See 014.

## Open questions
- Error cases for malformed fallback YAML are enforced in code but not all have direct regression tests.
- Proxy alias cache invalidation is not exposed; a long-lived client will keep the first discovered alias set.
