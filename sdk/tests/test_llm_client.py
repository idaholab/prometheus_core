# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Tests for the provider-agnostic LLM client."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from prometheus_api.llm_client import (
    AsyncLLMClient,
    ChatResponse,
    EmbeddingResponse,
    LLMAliasError,
    LLMClient,
    LLMClientError,
    LLMConfig,
    LLMConfigError,
    LLMEndpointUnavailableError,
    LLMProviderError,
    LLMToolCallError,
    ToolDefinition,
    normalize_embedding_input,
    normalize_messages,
    redact_secrets,
)
from prometheus_api.llm_client.tracing import MLFLOW_API_KEY_ENV, enable_mlflow_x_api_key
from prometheus_api.llm_configs import get_llm_config_path


def _fallback_yaml(tmp_path):
    path = tmp_path / "llm_config.yaml"
    path.write_text(
        """
model_list:
  - model_name: default
    litellm_params:
      model: openai/default-model
      api_key: os.environ/LLM_API_KEY
  - model_name: small
    litellm_params:
      model: openai/small-model
  - model_name: medium
    litellm_params:
      model: openai/medium-model
  - model_name: large
    litellm_params:
      model: anthropic/large-model
  - model_name: embedding
    litellm_params:
      model: openai/text-embedding-model
""".strip(),
        encoding="utf-8",
    )
    return path


def _proxy_response(
    request: httpx.Request, payload: dict, status_code: int = 200
) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=request)


def _proxy_models(*aliases: str) -> dict:
    return {"data": [{"id": alias} for alias in aliases]}


class _FakeMlflowContext:
    def __init__(self, value=None):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeMlflowSpan:
    def __init__(self, name, span_type, attributes):
        self.name = name
        self.span_type = span_type
        self.attributes = attributes
        self.inputs = None
        self.outputs = None

    def set_inputs(self, inputs):
        self.inputs = inputs

    def set_outputs(self, outputs):
        self.outputs = outputs


def _install_fake_mlflow(monkeypatch):
    from prometheus_api.llm_client import tracing as tracing_module

    monkeypatch.setattr(tracing_module, "_MLFLOW_SETUP_DONE", False)
    state = SimpleNamespace(
        autolog_calls=0,
        experiments=[],
        http_request_kwargs=[],
        rest_utils=None,
        spans=[],
        trace_tags=[],
    )

    mlflow = ModuleType("mlflow")
    mlflow.__path__ = []
    mlflow_litellm = ModuleType("mlflow.litellm")
    mlflow_entities = ModuleType("mlflow.entities")
    mlflow_utils = ModuleType("mlflow.utils")
    mlflow_utils.__path__ = []
    rest_utils = ModuleType("mlflow.utils.rest_utils")
    state.rest_utils = rest_utils

    def autolog():
        state.autolog_calls += 1

    def set_experiment(name):
        state.experiments.append(name)

    def tracing_context(*, tags):
        state.trace_tags.append(dict(tags))
        return _FakeMlflowContext()

    def start_span(*, name, span_type, attributes):
        span = _FakeMlflowSpan(name, span_type, dict(attributes))
        state.spans.append(span)
        return _FakeMlflowContext(span)

    def http_request(host_creds, endpoint, method, *args, **kwargs):
        state.http_request_kwargs.append(dict(kwargs))
        return {"endpoint": endpoint, "method": method, "kwargs": kwargs}

    mlflow_litellm.autolog = autolog
    mlflow_entities.SpanType = SimpleNamespace(CHAIN="CHAIN")
    mlflow.tracing = SimpleNamespace(context=tracing_context)
    mlflow.start_span = start_span
    mlflow.set_experiment = set_experiment
    mlflow.litellm = mlflow_litellm
    rest_utils.http_request = http_request

    monkeypatch.setitem(sys.modules, "mlflow", mlflow)
    monkeypatch.setitem(sys.modules, "mlflow.litellm", mlflow_litellm)
    monkeypatch.setitem(sys.modules, "mlflow.entities", mlflow_entities)
    monkeypatch.setitem(sys.modules, "mlflow.utils", mlflow_utils)
    monkeypatch.setitem(sys.modules, "mlflow.utils.rest_utils", rest_utils)
    return state


def test_config_from_env(monkeypatch, tmp_path):
    config_path = tmp_path / "llm.yaml"
    config_path.write_text("proxy_url: http://custom-proxy:4000\n", encoding="utf-8")
    env = {
        "REGISTRY_URL": " http://registry:4000 ",
        "LLM_CONFIG_FILE": str(config_path),
        "LLM_CONFIG_PROFILE": " openai ",
        "LLM_DEBUG_LOG_MESSAGES": "true",
        "ENABLE_MLFLOW_TRACING": "true",
    }

    config = LLMConfig.from_env(env)

    # REQ-005-14, BEH-005-05: an explicit file wins over a packaged profile.
    assert config.proxy_url == "http://custom-proxy:4000"
    assert config.config_file == config_path
    assert config.debug_log_messages is True
    assert config.enable_mlflow_tracing is True

    profile_config = LLMConfig.from_env({"LLM_CONFIG_PROFILE": " openai "})
    assert profile_config.config_file == get_llm_config_path("openai")


def test_config_from_env_loads_default_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REGISTRY_URL", raising=False)
    (tmp_path / ".env").write_text(
        "REGISTRY_URL=http://from-dotenv:4000\nENABLE_MLFLOW_TRACING=true\n",
        encoding="utf-8",
    )

    config = LLMConfig.from_env()

    # REQ-005-02, BEH-005-04: the default registry profile reads the local .env.
    assert config.proxy_url == "http://from-dotenv:4000"
    assert config.config_file == get_llm_config_path("registry")
    assert config.enable_mlflow_tracing is True


def test_default_registry_profile_reads_registry_url():
    config = LLMConfig.from_env({"REGISTRY_URL": " http://registry:4000 "})

    # BEH-005-04: REGISTRY_URL remains the default registry profile endpoint.
    assert config.config_file == get_llm_config_path("registry")
    assert config.proxy_url == "http://registry:4000"


def test_config_resolves_proxy_url_from_yaml_env_reference(monkeypatch, tmp_path):
    config_path = tmp_path / "proxy.yaml"
    config_path.write_text("proxy_url: os.environ/CUSTOM_PROXY_URL\n", encoding="utf-8")
    monkeypatch.setenv("CUSTOM_PROXY_URL", " https://proxy.example/v1 ")

    config = LLMConfig(config_file=config_path)
    overridden = LLMConfig(config_file=config_path, proxy_url="http://override:4000")

    # REQ-005-15: YAML environment references resolve unless explicitly overridden.
    assert config.proxy_url == "https://proxy.example/v1"
    assert overridden.proxy_url == "http://override:4000"


def test_fallback_yaml_parsing_resolves_env_refs(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "env-secret")
    config = LLMConfig(config_file=_fallback_yaml(tmp_path))

    models = config.load_fallback_models()

    assert sorted(models) == ["default", "embedding", "large", "medium", "small"]
    assert models["default"].provider_model == "openai/default-model"
    assert models["default"].litellm_params["api_key"] == "env-secret"


def test_local_development_example_config_parses():
    """The tracked local-development template must stay parseable and complete.

    This is the only client-side guard that the example YAML keeps the full
    six-flavor contract, including `vision`. Without it the template rots silently.
    """
    config_path = Path(__file__).resolve().parents[1] / "llm_config.example.yaml"
    config = LLMConfig(config_file=config_path)

    models = config.load_fallback_models()

    assert sorted(models) == ["default", "embedding", "large", "medium", "small", "vision"]
    assert models["default"].provider_model
    assert models["embedding"].provider_model


def test_default_alias_is_fixed():
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        requests.append(json.loads(request.content))
        return _proxy_response(
            request,
            {
                "model": "provider-default",
                "choices": [{"message": {"content": "handled"}}],
                "usage": {"total_tokens": 4},
            },
        )

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client("Summarize this.")

    assert response.text == "handled"
    # REQ-006-14: callers cannot configure away the agent-owned default flavor.
    assert response.model_alias == "default"
    assert requests[0]["model"] == "default"


def test_alias_discovery_and_resolution_from_proxy():
    def handler(request: httpx.Request) -> httpx.Response:
        return _proxy_response(request, _proxy_models("small", "large"))

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_models() == ["large", "small"]
    assert client.resolve_model("small") == "small"


def test_missing_default_alias_error_is_actionable():
    def handler(request: httpx.Request) -> httpx.Response:
        return _proxy_response(request, _proxy_models("embedding", "large", "medium", "small"))

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMAliasError) as exc_info:
        client("hello")

    message = str(exc_info.value)
    assert "LLM alias 'default' is not available" in message
    assert "Available aliases: embedding, large, medium, small" in message
    assert "Configure it in LiteLLM or the selected LLM config file" in message


def test_normalize_raw_string_and_message_list():
    assert normalize_messages(" hello ") == [{"role": "user", "content": " hello "}]

    messages = [{"role": "system", "content": "Be concise."}]
    normalized = normalize_messages(messages)

    assert normalized == messages
    assert normalized is not messages


@pytest.mark.parametrize(
    "value, expected_error",
    [
        ("", ValueError),
        ([], ValueError),
        ([{"role": "user"}], ValueError),
        ([{"role": "", "content": "hello"}], ValueError),
        ([{"role": "user", "content": ""}], ValueError),
        ({"role": "user", "content": "hello"}, TypeError),
        # REQ-006-15 relaxes content only for assistant turns that carry tool calls.
        ([{"content": "hello"}], ValueError),
        ([{"role": "assistant", "content": None}], ValueError),
        ([{"role": "assistant", "content": None, "tool_calls": []}], ValueError),
        ([{"role": "assistant", "tool_calls": []}], ValueError),
        ([{"role": "tool", "content": None, "tool_calls": [{"id": "call_1"}]}], ValueError),
        ([{"role": "user", "content": None, "tool_calls": [{"id": "call_1"}]}], ValueError),
    ],
)
def test_normalize_messages_rejects_invalid_inputs(value, expected_error):
    with pytest.raises(expected_error):
        normalize_messages(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("content", [None, "", "   "])
def test_normalize_messages_accepts_assistant_tool_call_turns(content):
    """REQ-006-15, BEH-006-04: a tool-call turn replays without placeholder content."""
    tool_calls = [{"id": "call_1", "function": {"name": "lookup", "arguments": "{}"}}]

    normalized = normalize_messages(
        [
            {"role": "user", "content": "look up iron"},
            {"role": "assistant", "content": content, "tool_calls": tool_calls},
            {"role": "tool", "tool_call_id": "call_1", "content": "7.87"},
        ]
    )

    assert [message["role"] for message in normalized] == ["user", "assistant", "tool"]
    assert normalized[1]["content"] is None
    assert normalized[1]["tool_calls"] == tool_calls


def test_normalize_messages_fills_absent_content_for_tool_call_turns():
    """REQ-006-15: an absent content key becomes an explicit null."""
    normalized = normalize_messages(
        [{"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "x"}}]}]
    )

    assert normalized[0]["content"] is None


def test_normalize_embedding_input():
    assert normalize_embedding_input("text") == (["text"], True)
    assert normalize_embedding_input(["a", "b"]) == (["a", "b"], False)

    with pytest.raises(ValueError):
        normalize_embedding_input("")
    with pytest.raises(ValueError):
        normalize_embedding_input([])
    with pytest.raises(TypeError):
        normalize_embedding_input([1])  # type: ignore[list-item]


def test_sync_chat_method_uses_proxy():
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("large"))
        posted.append(json.loads(request.content))
        return _proxy_response(
            request,
            {
                "model": "resolved-large",
                "choices": [{"message": {"content": "analysis"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.large("Analyze this.", temperature=0)

    assert isinstance(response, ChatResponse)
    assert response.text == "analysis"
    assert response.model_alias == "large"
    assert response.provider_model == "resolved-large"
    assert response.usage == {"prompt_tokens": 2, "completion_tokens": 1}
    assert posted[0]["messages"] == [{"role": "user", "content": "Analyze this."}]
    assert posted[0]["temperature"] == 0


def test_disabled_mlflow_tracing_does_not_import_mlflow(monkeypatch):
    from prometheus_api.llm_client import tracing as tracing_module

    monkeypatch.setattr(tracing_module, "_MLFLOW_SETUP_DONE", False)
    for module_name in [
        "mlflow",
        "mlflow.litellm",
        "mlflow.entities",
        "mlflow.utils",
        "mlflow.utils.rest_utils",
    ]:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        return _proxy_response(request, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client("hello")

    assert response.text == "ok"
    assert "mlflow" not in sys.modules


def test_mlflow_tracing_sync_chat_records_span_and_protected_tags(monkeypatch, tmp_path):
    state = _install_fake_mlflow(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(MLFLOW_API_KEY_ENV, "mlflow-secret")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "prometheus-test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        return _proxy_response(
            request,
            {
                "model": "resolved-default",
                "choices": [{"message": {"content": "traced answer"}}],
                "usage": {"total_tokens": 7},
            },
        )

    client = LLMClient(
        config=LLMConfig(
            proxy_url="http://proxy",
            enable_mlflow_tracing=True,
            app_name="Configured Agent",
            mlflow_trace_tags={
                "review_status": "unreviewed",
                "app_name": "bad",
                "base_url": "bad",
                "model": "bad",
            },
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        trace_tags={"environment": "test"},
    )

    response = client("hello", trace_tags={"model": "bad-call", "use_case": "chat"})
    client("hello again")

    assert response.text == "traced answer"
    assert state.autolog_calls == 1
    assert state.experiments == ["prometheus-test"]
    assert state.trace_tags[0] == {
        "review_status": "unreviewed",
        "app_name": "Configured Agent",
        "base_url": "http://proxy",
        "model": "default",
        "environment": "test",
        "use_case": "chat",
    }
    assert state.spans[0].name == "llm_client.chat"
    assert state.spans[0].span_type == "CHAIN"
    assert state.spans[0].attributes == {
        "model_alias": "default",
        "provider_model": "default",
        "path": "proxy",
        "client": "sync",
    }
    assert state.spans[0].inputs == {"messages": [{"role": "user", "content": "hello"}]}
    assert state.spans[0].outputs == {
        "text": "traced answer",
        "model_alias": "default",
        "provider_model": "resolved-default",
        "usage": {"total_tokens": 7},
        "finish_reason": None,
    }


def test_enable_mlflow_x_api_key_injects_header(monkeypatch):
    state = _install_fake_mlflow(monkeypatch)
    monkeypatch.setenv(MLFLOW_API_KEY_ENV, "mlflow-secret")

    enable_mlflow_x_api_key()
    result = state.rest_utils.http_request(
        object(),
        "/api/2.0/mlflow/runs/log-batch",
        "POST",
        extra_headers={"Existing": "yes"},
    )

    assert result["kwargs"]["extra_headers"] == {
        "Existing": "yes",
        "X-Api-Key": "mlflow-secret",
    }


def test_enable_mlflow_x_api_key_logs_when_missing(monkeypatch, caplog):
    state = _install_fake_mlflow(monkeypatch)
    monkeypatch.delenv(MLFLOW_API_KEY_ENV, raising=False)

    with caplog.at_level(logging.WARNING, logger="prometheus_api.llm_client"):
        enable_mlflow_x_api_key()

    state.rest_utils.http_request(object(), "/api", "GET", headers={"Existing": "yes"})

    assert f"Warning: {MLFLOW_API_KEY_ENV} not found in environment." in caplog.text
    assert state.http_request_kwargs[0]["headers"] == {
        "Existing": "yes",
        "X-Api-Key": None,
    }


@pytest.mark.asyncio
async def test_async_chat_method_uses_proxy():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("medium"))
        return _proxy_response(
            request,
            {
                "model": "resolved-medium",
                "choices": [{"message": {"content": "async answer"}}],
                "usage": {"total_tokens": 3},
            },
        )

    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    response = await client.medium([{"role": "user", "content": "Analyze."}])

    assert response.text == "async answer"
    assert response.model_alias == "medium"
    assert response.provider_model == "resolved-medium"
    assert response.usage == {"total_tokens": 3}
    await client.aclose()


@pytest.mark.asyncio
async def test_mlflow_tracing_async_chat_records_span(monkeypatch, tmp_path):
    state = _install_fake_mlflow(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(MLFLOW_API_KEY_ENV, "mlflow-secret")
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("medium"))
        return _proxy_response(
            request,
            {
                "model": "resolved-medium",
                "choices": [{"message": {"content": "async traced"}}],
            },
        )

    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy", enable_mlflow_tracing=True),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        app_name="Async Agent",
    )

    response = await client.medium("Analyze.", trace_tags={"environment": "test"})

    assert response.text == "async traced"
    assert state.autolog_calls == 1
    assert state.trace_tags[0]["app_name"] == "Async Agent"
    assert state.trace_tags[0]["base_url"] == "http://proxy"
    assert state.trace_tags[0]["model"] == "medium"
    assert state.trace_tags[0]["environment"] == "test"
    assert state.spans[0].attributes["client"] == "async"
    assert state.spans[0].outputs["text"] == "async traced"
    await client.aclose()


def test_sync_embedding_method_uses_proxy():
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("embedding"))
        posted.append(json.loads(request.content))
        return _proxy_response(
            request,
            {
                "model": "resolved-embedding",
                "data": [{"embedding": [0.1, 0.2]}],
                "usage": {"total_tokens": 2},
            },
        )

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.embedding("bearing temperature rising")

    assert isinstance(response, EmbeddingResponse)
    assert response.embeddings == [[0.1, 0.2]]
    assert response.model_alias == "embedding"
    assert response.provider_model == "resolved-embedding"
    assert posted[0]["input"] == "bearing temperature rising"


@pytest.mark.asyncio
async def test_async_embedding_method_uses_proxy():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("embedding"))
        return _proxy_response(
            request,
            {
                "model": "resolved-embedding",
                "data": [{"embedding": [1, 2]}, {"embedding": [3, 4]}],
            },
        )

    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    response = await client.embedding(["pressure spike", "temperature drift"])

    assert response.embeddings == [[1.0, 2.0], [3.0, 4.0]]
    assert response.model_alias == "embedding"
    await client.aclose()


def test_proxy_unavailable_uses_fallback_sdk(monkeypatch, tmp_path):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("proxy down", request=request)

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return {
            "model": "openai/default-model",
            "choices": [{"message": {"content": "fallback answer"}}],
            "usage": {"total_tokens": 8},
        }

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", config_file=_fallback_yaml(tmp_path)),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client("Fallback please.")

    assert response.text == "fallback answer"
    assert response.model_alias == "default"
    assert response.provider_model == "openai/default-model"
    assert calls[0]["model"] == "openai/default-model"
    assert calls[0]["messages"] == [{"role": "user", "content": "Fallback please."}]


@pytest.mark.asyncio
async def test_async_proxy_unavailable_uses_fallback_sdk(monkeypatch, tmp_path):
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("proxy down", request=request)

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return {
            "model": "openai/medium-model",
            "choices": [{"message": {"content": "async fallback"}}],
        }

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy", config_file=_fallback_yaml(tmp_path)),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    response = await client.medium("Fallback async.")

    assert response.text == "async fallback"
    assert calls[0]["model"] == "openai/medium-model"
    await client.aclose()


def test_unknown_profile_raises_config_error():
    with pytest.raises(LLMConfigError) as exc_info:
        LLMConfig.from_env({"LLM_CONFIG_PROFILE": "genisis"})

    message = str(exc_info.value)
    assert "LLM_CONFIG_PROFILE" in message
    assert "'genisis'" in message
    assert "registry" in message
    assert isinstance(exc_info.value, ValueError)


def test_missing_config_file_raises_config_error(tmp_path):
    with pytest.raises(LLMConfigError, match="does not exist"):
        LLMConfig(config_file=tmp_path / "missing.yaml").load_fallback_models()


def test_unreachable_proxy_without_model_list_names_the_proxy():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy:4000", config_file=get_llm_config_path()),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMEndpointUnavailableError) as exc_info:
        client("Hello?")

    message = str(exc_info.value)
    assert "http://proxy:4000" in message
    assert "'registry'" in message
    assert "connection refused" in message


def test_unreachable_direct_endpoint_names_the_endpoint(monkeypatch, tmp_path):
    def fake_completion(**kwargs):
        request = httpx.Request("POST", "http://llm.example/v1/chat/completions")
        try:
            raise httpx.ConnectError("[Errno 61] Connection refused", request=request)
        except httpx.ConnectError as exc:
            raise RuntimeError("litellm.InternalServerError: Connection error.") from exc

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    config_path = tmp_path / "direct.yaml"
    config_path.write_text(
        "model_list:\n"
        "  - model_name: default\n"
        "    litellm_params:\n"
        "      model: openai/gpt-x\n"
        "      api_base: http://llm.example/v1\n",
        encoding="utf-8",
    )
    client = LLMClient(config=LLMConfig(config_file=config_path))

    with pytest.raises(LLMEndpointUnavailableError) as exc_info:
        client("Hello?")

    message = str(exc_info.value)
    assert "http://llm.example/v1" in message
    assert "'default'" in message
    assert "Connection refused" in message


@pytest.mark.asyncio
async def test_async_unreachable_direct_embedding_endpoint(monkeypatch, tmp_path):
    async def fake_aembedding(**kwargs):
        raise ConnectionRefusedError("[Errno 61] Connection refused")

    import litellm

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    client = AsyncLLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    with pytest.raises(LLMEndpointUnavailableError, match="'embedding'"):
        await client.embedding("pressure spike")
    await client.aclose()


def test_provider_error_is_not_reported_as_unreachable(monkeypatch, tmp_path):
    def fake_completion(**kwargs):
        raise RuntimeError("401 invalid api key")

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    with pytest.raises(RuntimeError, match="401 invalid api key") as exc_info:
        client("Hello?")
    assert exc_info.value.__cause__ is None


def test_reachable_proxy_rejection_does_not_fallback(monkeypatch, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        return _proxy_response(request, {"error": "bad request"}, status_code=400)

    def fake_completion(**kwargs):
        raise AssertionError("fallback should not be called")

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", config_file=_fallback_yaml(tmp_path)),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client("Do not fallback.")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "bad request"
    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


def test_proxy_error_reports_status_endpoint_and_provider_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        body = {
            "error": {
                "message": "Invalid API key; Authorization: Bearer sk-live-123",
                "type": "auth_error",
                "code": 401,
            }
        }
        return _proxy_response(request, body, status_code=401)

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", config_file=_fallback_yaml(tmp_path)),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMProviderError) as exc_info:
        client("Hello?")

    message = str(exc_info.value)
    assert message.startswith("LLM request failed: 401 Unauthorized")
    assert "http://proxy/v1/chat/completions" in message
    assert "type=auth_error, code=401" in message
    assert "sk-live-123" not in message
    assert exc_info.value.alias == "default"


@pytest.mark.asyncio
async def test_async_proxy_models_error_is_a_provider_error(tmp_path):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable", request=request)

    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy", config_file=_fallback_yaml(tmp_path)),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMProviderError, match="503 Service Unavailable") as exc_info:
        await client.medium("Hello?")
    assert exc_info.value.endpoint == "http://proxy/v1/models"
    assert exc_info.value.detail == "upstream unavailable"
    await client.aclose()


class _FakeLiteLLMError(Exception):
    def __init__(self, message, status_code, body=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body


def test_direct_html_error_page_is_summarized(monkeypatch, tmp_path):
    page = "<!DOCTYPE html><html><head><title>Access Denied</title></head>" + "x" * 5000

    def fake_completion(**kwargs):
        raise _FakeLiteLLMError(f"litellm.APIError: APIError: OpenAIException - {page}", 403, page)

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    with pytest.raises(LLMProviderError) as exc_info:
        client("Hello?")

    message = str(exc_info.value)
    assert "403 Forbidden" in message
    assert "'default' -> openai/default-model" in message
    assert "HTML page 'Access Denied'" in message
    assert len(message) < 600


@pytest.mark.asyncio
async def test_async_direct_embedding_error_strips_litellm_prefix(monkeypatch, tmp_path):
    async def fake_aembedding(**kwargs):
        raise _FakeLiteLLMError(
            "litellm.RateLimitError: RateLimitError: OpenAIException - Slow down", 429
        )

    import litellm

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    client = AsyncLLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    with pytest.raises(LLMProviderError) as exc_info:
        await client.embedding("pressure spike")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Slow down"
    assert exc_info.value.provider_model == "openai/text-embedding-model"
    await client.aclose()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"error": {"message": "Bad key", "type": "auth"}}, "Bad key (type=auth)"),
        ({"detail": "model not found"}, "model not found"),
        ({"error": "quota exceeded"}, "quota exceeded"),
        (b'{"error": {"message": "from bytes"}}', "from bytes"),
        ("", "empty response body"),
        ("api_key=sk-123 rejected", "api_key=[REDACTED] rejected"),
        ("y" * 1000, "y" * 299 + "…"),
    ],
)
def test_summarize_body(body, expected):
    from prometheus_api.llm_client.provider_errors import summarize_body

    assert summarize_body(body) == expected


def test_fallback_embedding_uses_litellm_sdk(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_embedding(**kwargs):
        calls.append(kwargs)
        return {
            "model": "openai/text-embedding-model",
            "data": [{"embedding": [0, 1]}, {"embedding": [2, 3]}],
        }

    import litellm

    monkeypatch.setattr(litellm, "embedding", fake_embedding)
    client = LLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    response = client.embedding(["a", "b"])

    assert response.embeddings == [[0.0, 1.0], [2.0, 3.0]]
    assert calls[0]["model"] == "openai/text-embedding-model"
    assert calls[0]["input"] == ["a", "b"]


def test_debug_logging_hides_prompt_content_by_default(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        return _proxy_response(
            request,
            {
                "model": "resolved-default",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"total_tokens": 3},
            },
        )

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.DEBUG, logger="prometheus_api.llm_client"):
        client("secret prompt text")

    assert "secret prompt text" not in caplog.text
    assert "message_count" in caplog.text
    assert "roles" in caplog.text
    assert "resolved-default" in caplog.text
    assert "total_tokens" in caplog.text


def test_opt_in_debug_logging_redacts_prompt_content(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        return _proxy_response(
            request,
            {"model": "resolved-default", "choices": [{"message": {"content": "ok"}}]},
        )

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", debug_log_messages=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with caplog.at_level(logging.DEBUG, logger="prometheus_api.llm_client"):
        client("api_key=abc123")

    assert "[REDACTED]" in caplog.text
    assert "abc123" not in caplog.text


def test_secret_redaction_recurses_through_common_secret_fields():
    payload = {
        "api_key": "one",
        "nested": {"authorization": "two", "safe": "ok"},
        "items": [{"access_token": "three"}],
        "text": "password: four",
    }

    redacted = redact_secrets(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["authorization"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "ok"
    assert redacted["items"][0]["access_token"] == "[REDACTED]"
    assert redacted["text"] == "password: [REDACTED]"


def test_config_api_key_is_sent_as_proxy_bearer_token():
    # REQ-007-05: a transient config key authenticates every proxy request.
    observed_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_headers.append(request.headers.get("authorization"))
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("default"))
        return _proxy_response(request, {"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy").with_api_key("proxy-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client("hello")

    assert observed_headers == ["Bearer proxy-key", "Bearer proxy-key"]


def _tool_call_payload(call_id="call_1", name="lookup", arguments='{"query": "iron"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def _tool_chat_payload(*, content=None, finish_reason="tool_calls", tool_calls=None):
    return {
        "model": "resolved-medium",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls if tool_calls is not None else [_tool_call_payload()],
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"total_tokens": 11},
    }


def _tool_handler(posted, alias="medium", payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models(alias))
        posted.append(json.loads(request.content))
        return _proxy_response(request, payload if payload is not None else _tool_chat_payload())

    return handler


def test_empty_tools_list_is_omitted_from_the_payload():
    """REQ-006-17: tools=[] behaves like tools=None instead of sending "tools": []."""
    posted: list[dict] = []
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted))),
    )

    client.medium("look up iron", tools=[])

    assert "tools" not in posted[0]
    assert "tool_choice" not in posted[0]


@pytest.mark.parametrize("tools", [None, []])
def test_tool_choice_without_tools_is_rejected_before_dispatch(tools):
    """REQ-006-17: tool_choice with no tools raises client-side, not as a backend 400."""
    posted: list[dict] = []
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted))),
    )

    with pytest.raises(LLMToolCallError, match="tool_choice requires"):
        client.medium("look up iron", tools=tools, tool_choice="auto")
    assert posted == []


def test_sync_chat_populates_tool_calls_from_proxy_dict():
    """REQ-014-02, BEH-014-01: a pure tool-call turn has empty text but a full signal."""
    posted: list[dict] = []
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted))),
    )

    response = client.medium("look up iron", tools=[ToolDefinition(name="lookup")])

    assert response.text == ""
    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"query": "iron"}


async def test_async_chat_populates_tool_calls_from_proxy_dict():
    """REQ-014-02, REQ-006-17: the async client returns the same normalized tool calls."""
    posted: list[dict] = []
    handler = _tool_handler(posted)

    async def async_handler(request: httpx.Request) -> httpx.Response:
        return handler(request)

    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(async_handler)),
    )

    response = await client.medium("look up iron", tools=[ToolDefinition(name="lookup")])
    await client.aclose()

    assert response.text == ""
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].arguments == {"query": "iron"}
    assert posted[0]["tools"][0]["function"]["name"] == "lookup"


def test_sync_chat_populates_tool_calls_from_litellm_object(monkeypatch, tmp_path):
    """REQ-014-02: the LiteLLM SDK object shape parses like the proxy dict shape."""

    class _Message:
        role = "assistant"
        content = None
        tool_calls = [
            SimpleNamespace(
                id="call_7",
                function=SimpleNamespace(name="lookup", arguments='{"query": "steel"}'),
            )
        ]

    def fake_completion(**kwargs):
        assert kwargs["tools"][0]["function"]["name"] == "lookup"
        return SimpleNamespace(
            model="anthropic/large-model",
            choices=[SimpleNamespace(message=_Message(), finish_reason="tool_calls")],
            usage=None,
        )

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    response = client.large("look up steel", tools=[ToolDefinition(name="lookup")])

    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].id == "call_7"
    assert response.tool_calls[0].arguments == {"query": "steel"}


async def test_async_chat_populates_tool_calls_from_litellm_object(monkeypatch, tmp_path):
    """REQ-014-02: async fallback parity, with arguments supplied as a mapping."""

    class _Message:
        role = "assistant"
        content = None
        tool_calls = [
            SimpleNamespace(
                id="call_8",
                function=SimpleNamespace(name="lookup", arguments={"query": "copper"}),
            )
        ]

    async def fake_acompletion(**kwargs):
        assert kwargs["tools"][0]["function"]["name"] == "lookup"
        return SimpleNamespace(
            model="anthropic/large-model",
            choices=[SimpleNamespace(message=_Message(), finish_reason="tool_calls")],
            usage=None,
        )

    import litellm

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    client = AsyncLLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    response = await client.large("look up copper", tools=[ToolDefinition(name="lookup")])
    await client.aclose()

    assert response.tool_calls[0].id == "call_8"
    assert response.tool_calls[0].arguments == {"query": "copper"}


def test_chat_forwards_tools_and_tool_choice_to_the_proxy_payload():
    """REQ-006-17: tools and tool_choice reach the OpenAI-compatible request body."""
    posted: list[dict] = []
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted))),
    )

    client.medium(
        "look up iron",
        tools=[ToolDefinition(name="lookup", description="Look up a material")],
        tool_choice="auto",
    )

    assert posted[0]["model"] == "medium"
    assert posted[0]["tool_choice"] == "auto"
    assert posted[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a material",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_chat_passes_hand_built_tool_schemas_through_unchanged():
    """REQ-006-17, REQ-014-09: existing callers keep a byte-identical wire payload."""
    posted: list[dict] = []
    handbuilt = {
        "type": "function",
        "function": {"name": "create_wall", "parameters": {"type": "object"}},
    }
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted))),
    )

    client.medium("build a wall", tools=[handbuilt], tool_choice="auto")

    assert posted[0]["tools"] == [handbuilt]


def test_chat_forwards_tools_to_litellm_fallback_kwargs(monkeypatch, tmp_path):
    """REQ-006-17: the LiteLLM SDK path receives the same converted schemas."""
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return {"model": "openai/medium-model", "choices": [{"message": {"content": "ok"}}]}

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    client = LLMClient(config=LLMConfig(config_file=_fallback_yaml(tmp_path)))

    client.medium("look up iron", tools=[ToolDefinition(name="lookup")], tool_choice="auto")

    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["tools"][0]["function"]["name"] == "lookup"


def test_flavor_methods_forward_the_tools_keyword():
    """REQ-006-17: tools binds through the flavor helpers without extra plumbing."""
    posted: list[dict] = []
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted, "large"))),
    )

    client.large("look up iron", tools=[ToolDefinition(name="lookup")], temperature=0)

    assert posted[0]["model"] == "large"
    assert posted[0]["temperature"] == 0
    assert posted[0]["tools"][0]["function"]["name"] == "lookup"


def test_chat_omits_tool_keys_when_no_tools_are_supplied():
    """REQ-006-17: a plain chat request is unchanged by the new parameters."""
    posted: list[dict] = []
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(_tool_handler(posted))),
    )

    client.medium("hello")

    assert "tools" not in posted[0]
    assert "tool_choice" not in posted[0]


def test_sync_chat_rejects_streaming_before_contacting_a_backend():
    """REQ-006-18, BEH-006-05: stream=True raises instead of silently returning nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent for a streaming call")

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMClientError, match="Streaming is not supported"):
        client.medium("hello", stream=True)


async def test_async_chat_rejects_streaming_before_contacting_a_backend():
    """REQ-006-18: the async client rejects streaming identically."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be sent for a streaming call")

    client = AsyncLLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMClientError, match="Streaming is not supported"):
        await client.medium("hello", stream=True)
    await client.aclose()


def test_sync_and_async_chat_signatures_match():
    """Spec 006 parity constraint: the two clients must not drift."""
    import inspect

    sync_params = inspect.signature(LLMClient.chat).parameters.values()
    async_params = inspect.signature(AsyncLLMClient.chat).parameters.values()
    assert [(p.name, p.kind, p.default) for p in sync_params] == [
        (p.name, p.kind, p.default) for p in async_params
    ]


def test_trace_outputs_include_redacted_tool_calls(monkeypatch):
    """REQ-007-13, BEH-007-04: model-authored arguments are redacted before they persist."""
    state = _install_fake_mlflow(monkeypatch)
    posted: list[dict] = []
    payload = _tool_chat_payload(tool_calls=[_tool_call_payload(arguments='{"api_key": "abc123"}')])
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", enable_mlflow_tracing=True),
        http_client=httpx.Client(
            transport=httpx.MockTransport(_tool_handler(posted, payload=payload))
        ),
    )

    client.medium("look up iron", tools=[ToolDefinition(name="lookup")])

    outputs = state.spans[0].outputs
    assert outputs["finish_reason"] == "tool_calls"
    assert outputs["tool_calls"] == [
        {"id": "call_1", "name": "lookup", "arguments": {"api_key": "[REDACTED]"}}
    ]
    # REQ-007-13: span inputs carry tool names only, never full JSON schemas.
    assert state.spans[0].inputs["tools"] == ["lookup"]
    assert "parameters" not in json.dumps(state.spans[0].inputs)


def test_trace_outputs_omit_tool_keys_without_tool_calls(monkeypatch):
    """REQ-007-11, BEH-007-05: text-only traces add finish_reason but no tool keys."""
    state = _install_fake_mlflow(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _proxy_response(request, _proxy_models("medium"))
        return _proxy_response(
            request,
            {
                "model": "resolved-medium",
                "choices": [{"message": {"content": "plain answer"}, "finish_reason": "length"}],
            },
        )

    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", enable_mlflow_tracing=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.medium("hello")

    outputs = state.spans[0].outputs
    assert set(outputs) == {"text", "model_alias", "provider_model", "usage", "finish_reason"}
    assert outputs["finish_reason"] == "length"
    assert set(state.spans[0].inputs) == {"messages"}


def test_debug_logging_omits_tool_arguments_by_default(caplog):
    """REQ-007-14: developer-authored tool names log; model-authored arguments do not."""
    posted: list[dict] = []
    payload = _tool_chat_payload(
        tool_calls=[_tool_call_payload(arguments='{"query": "top-secret-material"}')]
    )
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(_tool_handler(posted, payload=payload))
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="prometheus_api.llm_client"):
        client.medium("look up iron", tools=[ToolDefinition(name="lookup")], tool_choice="auto")

    assert "top-secret-material" not in caplog.text
    assert "'tool_names': ['lookup']" in caplog.text
    assert "'tool_count': 1" in caplog.text
    assert "'tool_call_count': 1" in caplog.text
    assert "'finish_reason': 'tool_calls'" in caplog.text


def test_opt_in_debug_logging_redacts_tool_arguments(caplog):
    """REQ-007-14: opting in still redacts secrets inside tool-call arguments."""
    posted: list[dict] = []
    payload = _tool_chat_payload(tool_calls=[_tool_call_payload(arguments='{"api_key": "abc123"}')])
    client = LLMClient(
        config=LLMConfig(proxy_url="http://proxy", debug_log_messages=True),
        http_client=httpx.Client(
            transport=httpx.MockTransport(_tool_handler(posted, payload=payload))
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="prometheus_api.llm_client"):
        client.medium("look up iron", tools=[ToolDefinition(name="lookup")])

    assert "tool_call_arguments" in caplog.text
    assert "abc123" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_tools_module_has_no_runtime_dependency_on_the_client_module():
    """REQ-014-12: tools.py must stay importable without the client, avoiding a cycle."""
    import ast
    from pathlib import Path as _Path

    from prometheus_api.llm_client import tools as tools_module

    source = _Path(tools_module.__file__).read_text(encoding="utf-8")

    def runtime_modules(node, guarded=False):
        found: list[str] = []
        for child in ast.iter_child_nodes(node):
            child_guarded = guarded
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                child_guarded = True
            if isinstance(child, ast.ImportFrom) and not child_guarded:
                base = child.module or ""
                found.append(base)
                found.extend(f"{base}.{alias.name}" for alias in child.names)
            elif isinstance(child, ast.Import) and not child_guarded:
                found.extend(alias.name for alias in child.names)
            found.extend(runtime_modules(child, child_guarded))
        return found

    assert not [m for m in runtime_modules(ast.parse(source)) if m.rsplit(".", 1)[-1] == "client"]


def test_llm_client_exports_tool_symbols():
    """REQ-014-11: the tool-calling surface is importable from the package root."""
    import prometheus_api.llm_client as package

    expected = {
        "ToolCall",
        "ToolDefinition",
        "LLMToolCallError",
        "parse_tool_calls",
        "parse_finish_reason",
        "assistant_message",
        "tool_result_message",
        "require_tool_calls",
        "tool_schemas",
        "call_tool",
        "acall_tool",
    }

    assert expected <= set(package.__all__)
    assert all(hasattr(package, name) for name in expected)
