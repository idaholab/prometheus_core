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

"""Sync and async provider-agnostic LLM clients."""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Sequence
from typing import Any, Literal, Mapping, cast

import httpx

from .config import FallbackModelConfig, LLMConfig
from .exceptions import (
    LLMAliasError,
    LLMClientError,
    LLMEndpointUnavailableError,
    LLMProviderError,
    LLMToolCallError,
)
from .models import ChatResponse, EmbeddingResponse
from .provider_errors import format_provider_error, litellm_error_body, summarize_body
from .normalization import ChatInput, EmbeddingInput, normalize_embedding_input, normalize_messages
from .security import extract_llm_api_key_from_a2a_context, redact_secrets
from .tools import (
    ToolCall,
    ToolDefinition,
    _get,
    parse_finish_reason,
    parse_tool_calls,
    tool_schemas,
)

logger = logging.getLogger("prometheus_api.llm_client")

_Mode = Literal["proxy", "fallback"]


class _ProxyUnavailableError(RuntimeError):
    """Internal signal used to route to the fallback SDK path."""


def _missing_alias_error(alias: str, aliases: list[str]) -> LLMAliasError:
    available = ", ".join(sorted(aliases)) if aliases else "none"
    return LLMAliasError(
        f"LLM alias {alias!r} is not available. Available aliases: {available}.\n"
        "Configure it in LiteLLM or the selected LLM config file."
    )


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _connection_failure(exc: BaseException) -> BaseException | None:
    """Return the transport-level cause if ``exc`` means the endpoint was unreachable."""
    for item in reversed(_exception_chain(exc)):
        if isinstance(item, (httpx.TransportError, OSError)):
            return item
    return None


def _failure_reason(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def _plain_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return cast(dict[str, Any], value.model_dump())
    if hasattr(value, "dict"):
        return cast(dict[str, Any], value.dict())
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {"value": value}


def _chat_text(raw: Any) -> str:
    choices = _get(raw, "choices", []) or []
    if not choices:
        return ""
    choice = choices[0]
    message = _get(choice, "message", {}) or {}
    content = _get(message, "content", "")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def _embedding_vectors(raw: Any) -> list[list[float]]:
    vectors: list[list[float]] = []
    for item in _get(raw, "data", []) or []:
        embedding = _get(item, "embedding", []) or []
        vectors.append([float(value) for value in embedding])
    return vectors


def _provider_model(raw: Any, fallback: str | None = None) -> str | None:
    model = _get(raw, "model", None)
    return str(model) if model else fallback


def _usage(raw: Any) -> dict[str, Any] | None:
    return _plain_dict(_get(raw, "usage", None))


def _litellm() -> Any:
    try:
        return importlib.import_module("litellm")
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LLMClientError("LiteLLM is required for LLM fallback calls") from exc


def _extract_proxy_aliases(payload: Any) -> list[str]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    aliases: list[str] = []
    for item in data:
        alias = None
        if isinstance(item, dict):
            alias = item.get("id") or item.get("model_name") or item.get("model")
        else:
            alias = getattr(item, "id", None) or getattr(item, "model_name", None)
        if alias:
            aliases.append(str(alias))
    return sorted(set(aliases))


class _ClientMixin:
    config: LLMConfig

    @classmethod
    def from_a2a_context(cls, context: Any, config: LLMConfig | None = None, **kwargs: Any):
        """Create a client using an optional ``llm_api_key`` from structured A2A data."""
        resolved_config = config or LLMConfig.from_env()
        api_key = extract_llm_api_key_from_a2a_context(context)
        if api_key:
            resolved_config = resolved_config.with_api_key(api_key)
        return cls(config=resolved_config, **kwargs)  # type: ignore[call-arg]

    def _fallback_models(self) -> dict[str, FallbackModelConfig]:
        return self.config.load_fallback_models()

    def _fallback_aliases(self) -> list[str]:
        return sorted(self._fallback_models())

    def _select_fallback(self, alias: str) -> tuple[_Mode, str, FallbackModelConfig]:
        models = self._fallback_models()
        if alias not in models:
            raise _missing_alias_error(alias, sorted(models))
        return "fallback", models[alias].provider_model, models[alias]

    def _fallback_after_proxy_failure(
        self, alias: str, exc: _ProxyUnavailableError
    ) -> tuple[_Mode, str, FallbackModelConfig]:
        """Use the config's own model_list when the proxy is down, or fail clearly."""
        source = self.config.describe_source()
        if not self._fallback_models():
            raise LLMEndpointUnavailableError(
                f"Cannot reach the LLM proxy {self.config.proxy_url} ({source}): {exc}.\n"
                "Check that the LiteLLM proxy is running and that proxy_url (REGISTRY_URL "
                "for the registry profile) points at it."
            ) from exc
        logger.warning(
            "LLM proxy %s is unreachable (%s); using the model_list from %s",
            self.config.proxy_url,
            exc,
            source,
        )
        return self._select_fallback(alias)

    def _raise_if_unreachable(self, fallback_model: FallbackModelConfig, exc: Exception) -> None:
        """Translate a LiteLLM connection failure; leave every other error to the caller."""
        cause = _connection_failure(exc)
        if cause is None:
            return
        endpoint = fallback_model.litellm_params.get("api_base") or (
            f"the default endpoint for {fallback_model.provider_model}"
        )
        raise LLMEndpointUnavailableError(
            f"Cannot reach the LLM endpoint {endpoint} for alias {fallback_model.alias!r} "
            f"({self.config.describe_source()}): {_failure_reason(cause)}.\n"
            "Check that the endpoint is up and reachable from this host (VPN or proxy "
            "settings), or select another profile with LLM_CONFIG_PROFILE."
        ) from exc

    def _provider_error(
        self,
        *,
        status_code: int,
        body: Any,
        endpoint: str | None,
        alias: str | None,
        provider_model: str | None,
    ) -> LLMProviderError:
        detail = summarize_body(body)
        return LLMProviderError(
            format_provider_error(
                status_code=status_code,
                detail=detail,
                source=self.config.describe_source(),
                endpoint=endpoint,
                alias=alias,
                provider_model=provider_model,
            ),
            status_code=status_code,
            detail=detail,
            endpoint=endpoint,
            alias=alias,
            provider_model=provider_model,
        )

    def _check_proxy_response(self, response: httpx.Response, alias: str | None) -> None:
        """Raise ``LLMProviderError`` for a proxy HTTP error, with the proxy's own message."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._provider_error(
                status_code=response.status_code,
                body=response.content,
                endpoint=str(response.request.url),
                alias=alias,
                provider_model=None,
            ) from exc

    def _raise_if_provider_error(self, fallback_model: FallbackModelConfig, exc: Exception) -> None:
        """Translate a LiteLLM HTTP error; leave every other error to the caller."""
        status_code = getattr(exc, "status_code", None)
        if not isinstance(status_code, int) or status_code < 400:
            return
        raise self._provider_error(
            status_code=status_code,
            body=litellm_error_body(exc),
            endpoint=fallback_model.litellm_params.get("api_base"),
            alias=fallback_model.alias,
            provider_model=fallback_model.provider_model,
        ) from exc

    def _proxy_headers(self, api_key: Any = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = str(api_key).strip() if api_key else self.config.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _litellm_kwargs(
        self,
        fallback_model: FallbackModelConfig,
        call_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        params = {
            key: value
            for key, value in fallback_model.litellm_params.items()
            if key != "model" and value is not None
        }
        params.update(call_kwargs)
        if self.config.api_key and "api_key" not in call_kwargs:
            params["api_key"] = self.config.api_key
        return params

    def _prepare_chat_kwargs(
        self,
        call_kwargs: dict[str, Any],
        *,
        tools: Sequence[ToolDefinition | Mapping[str, Any]] | None,
        tool_choice: str | Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and shape per-call chat kwargs before they reach a backend."""
        if call_kwargs.get("stream"):
            raise LLMClientError(
                "Streaming is not supported by prometheus_api.llm_client. "
                "Remove stream=True; see specs/006 out-of-scope notes."
            )
        prepared = dict(call_kwargs)
        # An empty tools list is treated like no tools: backends 400 on `"tools": []`.
        schemas = tool_schemas(tools) if tools is not None else []
        if tool_choice is not None and not schemas:
            raise LLMToolCallError("tool_choice requires at least one tool in tools")
        if schemas:
            prepared["tools"] = schemas
        if tool_choice is not None:
            prepared["tool_choice"] = tool_choice
        return prepared

    def _build_chat_response(
        self,
        *,
        raw: Any,
        alias: str,
        provider_model: str,
    ) -> ChatResponse:
        """Build the normalized chat response from either backend payload shape."""
        return ChatResponse(
            text=_chat_text(raw),
            model_alias=alias,
            provider_model=_provider_model(raw, provider_model),
            usage=_usage(raw),
            raw=raw,
            tool_calls=parse_tool_calls(raw),
            finish_reason=parse_finish_reason(raw),
        )

    @staticmethod
    def _tool_names(call_kwargs: Mapping[str, Any]) -> list[str] | None:
        """Extract developer-authored tool names from prepared kwargs for logging."""
        tools = call_kwargs.get("tools")
        if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
            return None
        names: list[str] = []
        for schema in tools:
            function = _get(schema, "function", {}) or {}
            names.append(str(_get(function, "name", "") or ""))
        return names

    def _backend_base_url(
        self,
        *,
        mode: _Mode,
        fallback_model: FallbackModelConfig | None,
        call_kwargs: dict[str, Any],
    ) -> str:
        if mode == "proxy":
            return str(self.config.proxy_url or "unknown")

        base_url = call_kwargs.get("api_base") or call_kwargs.get("base_url")
        if not base_url and fallback_model is not None:
            base_url = fallback_model.litellm_params.get(
                "api_base"
            ) or fallback_model.litellm_params.get("base_url")
        return str(base_url).strip() if base_url else "litellm-provider-default"

    def _chat_trace_context(
        self,
        *,
        alias: str,
        mode: _Mode,
        provider_model: str,
        fallback_model: FallbackModelConfig | None,
        messages: list[dict[str, Any]],
        call_kwargs: dict[str, Any],
        trace_tags: Mapping[str, Any] | None,
        client_kind: str,
    ) -> Any:
        from .tracing import chat_trace

        tags = dict(self.config.mlflow_trace_tags)
        if trace_tags:
            tags.update(
                {str(key): str(value) for key, value in trace_tags.items() if value is not None}
            )

        selected_model = alias if mode == "proxy" else provider_model
        protected_tags = {
            "app_name": self.config.app_name or "prometheus_api",
            "base_url": self._backend_base_url(
                mode=mode,
                fallback_model=fallback_model,
                call_kwargs=call_kwargs,
            ),
            "model": selected_model,
        }
        tags.update(protected_tags)

        return chat_trace(
            enabled=self.config.enable_mlflow_tracing,
            tags=tags,
            attributes={
                "model_alias": alias,
                "provider_model": provider_model,
                "path": mode,
                "client": client_kind,
            },
            inputs=self._chat_trace_inputs(messages, call_kwargs),
        )

    @staticmethod
    def _chat_trace_inputs(
        messages: list[dict[str, Any]],
        call_kwargs: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build span inputs, adding tool names only when tools were supplied."""
        inputs: dict[str, Any] = {"messages": messages}
        tool_names = _ClientMixin._tool_names(call_kwargs)
        if tool_names is not None:
            inputs["tools"] = tool_names
        return inputs

    def _set_chat_trace_outputs(self, span: Any | None, response: ChatResponse) -> None:
        if span is None:
            return
        outputs: dict[str, Any] = {
            "text": response.text,
            "model_alias": response.model_alias,
            "provider_model": response.provider_model,
            "usage": response.usage,
            # Always emitted so truncation (`"length"`) is visible on ordinary chat too.
            "finish_reason": response.finish_reason,
        }
        if response.tool_calls:
            # Traces persist remotely and arguments are model-authored, so redact them.
            outputs["tool_calls"] = [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": redact_secrets(call.arguments),
                }
                for call in response.tool_calls
            ]
        span.set_outputs(outputs)

    def _log_chat_request(
        self,
        *,
        alias: str,
        mode: _Mode,
        messages: list[dict[str, Any]],
        tool_names: list[str] | None = None,
        tool_choice: Any = None,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        payload: dict[str, Any] = {
            "alias": alias,
            "path": mode,
            "message_count": len(messages),
            "roles": [str(message.get("role", "")) for message in messages],
        }
        if tool_names is not None:
            payload["tool_count"] = len(tool_names)
            payload["tool_names"] = tool_names
        if tool_choice is not None:
            payload["tool_choice"] = redact_secrets(tool_choice)
        if self.config.debug_log_messages:
            payload["messages"] = redact_secrets(messages)
        logger.debug("LLM chat request: %s", payload)

    def _log_embedding_request(
        self,
        *,
        alias: str,
        mode: _Mode,
        inputs: list[str],
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        payload: dict[str, Any] = {
            "alias": alias,
            "path": mode,
            "embedding_input_count": len(inputs),
        }
        if self.config.debug_log_messages:
            payload["embedding_inputs"] = redact_secrets(inputs)
        logger.debug("LLM embedding request: %s", payload)

    def _log_response(
        self,
        *,
        operation: str,
        alias: str,
        mode: _Mode,
        provider_model: str | None,
        usage: dict[str, Any] | None,
        latency_seconds: float,
        tool_calls: tuple[ToolCall, ...] = (),
        finish_reason: str | None = None,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        payload: dict[str, Any] = {
            "alias": alias,
            "path": mode,
            "provider_model": provider_model,
            "usage": usage,
            "latency_seconds": round(latency_seconds, 6),
        }
        if finish_reason is not None:
            payload["finish_reason"] = finish_reason
        if tool_calls:
            payload["tool_call_count"] = len(tool_calls)
            payload["tool_call_names"] = [call.name for call in tool_calls]
            if self.config.debug_log_messages:
                payload["tool_call_arguments"] = redact_secrets(
                    [call.arguments for call in tool_calls]
                )
        logger.debug("LLM %s response: %s", operation, payload)


class LLMClient(_ClientMixin):
    """Synchronous provider-agnostic LLM client."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        http_client: httpx.Client | None = None,
        *,
        app_name: str | None = None,
        trace_tags: Mapping[str, Any] | None = None,
    ):
        self.config = (config or LLMConfig.from_env()).with_trace_options(
            app_name=app_name,
            trace_tags=trace_tags,
        )
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._proxy_aliases_cache: list[str] | None = None

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._http_client is not None and self._owns_http_client:
            self._http_client.close()

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self.config.timeout)
        return self._http_client

    def list_models(self) -> list[str]:
        """List configured aliases from the proxy, falling back only when unreachable."""
        if self.config.proxy_url:
            try:
                return self._list_proxy_models()
            except _ProxyUnavailableError:
                return self._fallback_aliases()
        return self._fallback_aliases()

    def resolve_model(self, alias: str) -> str:
        """Resolve an alias to the model name sent to the active backend."""
        _, provider_model, _ = self._select_model(alias)
        return provider_model

    def __call__(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return self.chat(text_or_messages, **kwargs)

    def chat(
        self,
        text_or_messages: ChatInput,
        model: str | None = None,
        trace_tags: Mapping[str, Any] | None = None,
        *,
        tools: Sequence[ToolDefinition | Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Run a chat-completion call."""
        kwargs = self._prepare_chat_kwargs(kwargs, tools=tools, tool_choice=tool_choice)
        tool_names = self._tool_names(kwargs)
        alias = str(model or "default")
        messages = normalize_messages(text_or_messages)
        start = time.perf_counter()
        mode, provider_model, fallback_model = self._select_model(alias)
        self._log_chat_request(
            alias=alias,
            mode=mode,
            messages=messages,
            tool_names=tool_names,
            tool_choice=tool_choice,
        )

        try:
            with self._chat_trace_context(
                alias=alias,
                mode=mode,
                provider_model=provider_model,
                fallback_model=fallback_model,
                messages=messages,
                call_kwargs=kwargs,
                trace_tags=trace_tags,
                client_kind="sync",
            ) as span:
                if mode == "proxy":
                    raw = self._proxy_chat(alias, messages, kwargs)
                else:
                    raw = self._fallback_chat(fallback_model, messages, kwargs)
                response = self._build_chat_response(
                    raw=raw, alias=alias, provider_model=provider_model
                )
                self._set_chat_trace_outputs(span, response)
        except _ProxyUnavailableError as exc:
            mode, provider_model, fallback_model = self._fallback_after_proxy_failure(alias, exc)
            self._log_chat_request(
                alias=alias,
                mode=mode,
                messages=messages,
                tool_names=tool_names,
                tool_choice=tool_choice,
            )
            with self._chat_trace_context(
                alias=alias,
                mode=mode,
                provider_model=provider_model,
                fallback_model=fallback_model,
                messages=messages,
                call_kwargs=kwargs,
                trace_tags=trace_tags,
                client_kind="sync",
            ) as span:
                raw = self._fallback_chat(fallback_model, messages, kwargs)
                response = self._build_chat_response(
                    raw=raw, alias=alias, provider_model=provider_model
                )
                self._set_chat_trace_outputs(span, response)

        self._log_response(
            operation="chat",
            alias=alias,
            mode=mode,
            provider_model=response.provider_model,
            usage=response.usage,
            latency_seconds=time.perf_counter() - start,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
        )
        return response

    def small(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return self.chat(text_or_messages, model="small", **kwargs)

    def medium(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return self.chat(text_or_messages, model="medium", **kwargs)

    def large(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return self.chat(text_or_messages, model="large", **kwargs)

    def vision(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return self.chat(text_or_messages, model="vision", **kwargs)

    def embedding(self, text_or_texts: EmbeddingInput, **kwargs: Any) -> EmbeddingResponse:
        alias = str(kwargs.pop("model", "embedding"))
        return self.embed(text_or_texts, model=alias, **kwargs)

    def embed(
        self,
        text_or_texts: EmbeddingInput,
        model: str = "embedding",
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Run an embedding call."""
        alias = str(model)
        inputs, single_input = normalize_embedding_input(text_or_texts)
        provider_input: str | list[str] = inputs[0] if single_input else inputs
        start = time.perf_counter()
        mode, provider_model, fallback_model = self._select_model(alias)
        self._log_embedding_request(alias=alias, mode=mode, inputs=inputs)

        try:
            if mode == "proxy":
                raw = self._proxy_embedding(alias, provider_input, kwargs)
            else:
                raw = self._fallback_embedding(fallback_model, provider_input, kwargs)
        except _ProxyUnavailableError as exc:
            mode, provider_model, fallback_model = self._fallback_after_proxy_failure(alias, exc)
            self._log_embedding_request(alias=alias, mode=mode, inputs=inputs)
            raw = self._fallback_embedding(fallback_model, provider_input, kwargs)

        usage = _usage(raw)
        resolved_model = _provider_model(raw, provider_model)
        self._log_response(
            operation="embedding",
            alias=alias,
            mode=mode,
            provider_model=resolved_model,
            usage=usage,
            latency_seconds=time.perf_counter() - start,
        )
        return EmbeddingResponse(
            embeddings=_embedding_vectors(raw),
            model_alias=alias,
            provider_model=resolved_model,
            usage=usage,
            raw=raw,
        )

    def _select_model(self, alias: str) -> tuple[_Mode, str, FallbackModelConfig | None]:
        if self.config.proxy_url:
            try:
                aliases = self._list_proxy_models()
            except _ProxyUnavailableError as exc:
                return self._fallback_after_proxy_failure(alias, exc)
            if alias not in aliases:
                raise _missing_alias_error(alias, aliases)
            return "proxy", alias, None
        return self._select_fallback(alias)

    def _list_proxy_models(self) -> list[str]:
        if self._proxy_aliases_cache is not None:
            return list(self._proxy_aliases_cache)
        assert self.config.proxy_url is not None
        url = f"{self.config.proxy_url.rstrip('/')}/v1/models"
        try:
            response = self.http_client.get(url, headers=self._proxy_headers())
        except httpx.RequestError as exc:
            raise _ProxyUnavailableError(str(exc)) from exc
        self._check_proxy_response(response, None)
        aliases = _extract_proxy_aliases(response.json())
        self._proxy_aliases_cache = aliases
        return list(aliases)

    def _proxy_chat(
        self,
        alias: str,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> Any:
        assert self.config.proxy_url is not None
        request_kwargs = dict(kwargs)
        api_key = request_kwargs.pop("api_key", None)
        payload = {"model": alias, "messages": messages, **request_kwargs}
        try:
            response = self.http_client.post(
                f"{self.config.proxy_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=self._proxy_headers(api_key),
            )
        except httpx.RequestError as exc:
            raise _ProxyUnavailableError(str(exc)) from exc
        self._check_proxy_response(response, alias)
        return response.json()

    def _proxy_embedding(
        self,
        alias: str,
        provider_input: str | list[str],
        kwargs: dict[str, Any],
    ) -> Any:
        assert self.config.proxy_url is not None
        request_kwargs = dict(kwargs)
        api_key = request_kwargs.pop("api_key", None)
        payload = {"model": alias, "input": provider_input, **request_kwargs}
        try:
            response = self.http_client.post(
                f"{self.config.proxy_url.rstrip('/')}/v1/embeddings",
                json=payload,
                headers=self._proxy_headers(api_key),
            )
        except httpx.RequestError as exc:
            raise _ProxyUnavailableError(str(exc)) from exc
        self._check_proxy_response(response, alias)
        return response.json()

    def _fallback_chat(
        self,
        fallback_model: FallbackModelConfig | None,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> Any:
        if fallback_model is None:
            raise LLMClientError("Fallback model was not selected")
        try:
            return _litellm().completion(
                model=fallback_model.provider_model,
                messages=messages,
                **self._litellm_kwargs(fallback_model, kwargs),
            )
        except Exception as exc:
            self._raise_if_unreachable(fallback_model, exc)
            self._raise_if_provider_error(fallback_model, exc)
            raise

    def _fallback_embedding(
        self,
        fallback_model: FallbackModelConfig | None,
        provider_input: str | list[str],
        kwargs: dict[str, Any],
    ) -> Any:
        if fallback_model is None:
            raise LLMClientError("Fallback model was not selected")
        try:
            return _litellm().embedding(
                model=fallback_model.provider_model,
                input=provider_input,
                **self._litellm_kwargs(fallback_model, kwargs),
            )
        except Exception as exc:
            self._raise_if_unreachable(fallback_model, exc)
            self._raise_if_provider_error(fallback_model, exc)
            raise


class AsyncLLMClient(_ClientMixin):
    """Asynchronous provider-agnostic LLM client."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        app_name: str | None = None,
        trace_tags: Mapping[str, Any] | None = None,
    ):
        self.config = (config or LLMConfig.from_env()).with_trace_options(
            app_name=app_name,
            trace_tags=trace_tags,
        )
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._proxy_aliases_cache: list[str] | None = None

    async def __aenter__(self) -> "AsyncLLMClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._http_client

    async def list_models(self) -> list[str]:
        """List configured aliases from the proxy, falling back only when unreachable."""
        if self.config.proxy_url:
            try:
                return await self._list_proxy_models()
            except _ProxyUnavailableError:
                return self._fallback_aliases()
        return self._fallback_aliases()

    async def resolve_model(self, alias: str) -> str:
        """Resolve an alias to the model name sent to the active backend."""
        _, provider_model, _ = await self._select_model(alias)
        return provider_model

    async def __call__(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return await self.chat(text_or_messages, **kwargs)

    async def chat(
        self,
        text_or_messages: ChatInput,
        model: str | None = None,
        trace_tags: Mapping[str, Any] | None = None,
        *,
        tools: Sequence[ToolDefinition | Mapping[str, Any]] | None = None,
        tool_choice: str | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Run a chat-completion call."""
        kwargs = self._prepare_chat_kwargs(kwargs, tools=tools, tool_choice=tool_choice)
        tool_names = self._tool_names(kwargs)
        alias = str(model or "default")
        messages = normalize_messages(text_or_messages)
        start = time.perf_counter()
        mode, provider_model, fallback_model = await self._select_model(alias)
        self._log_chat_request(
            alias=alias,
            mode=mode,
            messages=messages,
            tool_names=tool_names,
            tool_choice=tool_choice,
        )

        try:
            with self._chat_trace_context(
                alias=alias,
                mode=mode,
                provider_model=provider_model,
                fallback_model=fallback_model,
                messages=messages,
                call_kwargs=kwargs,
                trace_tags=trace_tags,
                client_kind="async",
            ) as span:
                if mode == "proxy":
                    raw = await self._proxy_chat(alias, messages, kwargs)
                else:
                    raw = await self._fallback_chat(fallback_model, messages, kwargs)
                response = self._build_chat_response(
                    raw=raw, alias=alias, provider_model=provider_model
                )
                self._set_chat_trace_outputs(span, response)
        except _ProxyUnavailableError as exc:
            mode, provider_model, fallback_model = self._fallback_after_proxy_failure(alias, exc)
            self._log_chat_request(
                alias=alias,
                mode=mode,
                messages=messages,
                tool_names=tool_names,
                tool_choice=tool_choice,
            )
            with self._chat_trace_context(
                alias=alias,
                mode=mode,
                provider_model=provider_model,
                fallback_model=fallback_model,
                messages=messages,
                call_kwargs=kwargs,
                trace_tags=trace_tags,
                client_kind="async",
            ) as span:
                raw = await self._fallback_chat(fallback_model, messages, kwargs)
                response = self._build_chat_response(
                    raw=raw, alias=alias, provider_model=provider_model
                )
                self._set_chat_trace_outputs(span, response)

        self._log_response(
            operation="chat",
            alias=alias,
            mode=mode,
            provider_model=response.provider_model,
            usage=response.usage,
            latency_seconds=time.perf_counter() - start,
            tool_calls=response.tool_calls,
            finish_reason=response.finish_reason,
        )
        return response

    async def small(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return await self.chat(text_or_messages, model="small", **kwargs)

    async def medium(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return await self.chat(text_or_messages, model="medium", **kwargs)

    async def large(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return await self.chat(text_or_messages, model="large", **kwargs)

    async def vision(self, text_or_messages: ChatInput, **kwargs: Any) -> ChatResponse:
        return await self.chat(text_or_messages, model="vision", **kwargs)

    async def embedding(self, text_or_texts: EmbeddingInput, **kwargs: Any) -> EmbeddingResponse:
        alias = str(kwargs.pop("model", "embedding"))
        return await self.embed(text_or_texts, model=alias, **kwargs)

    async def embed(
        self,
        text_or_texts: EmbeddingInput,
        model: str = "embedding",
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Run an embedding call."""
        alias = str(model)
        inputs, single_input = normalize_embedding_input(text_or_texts)
        provider_input: str | list[str] = inputs[0] if single_input else inputs
        start = time.perf_counter()
        mode, provider_model, fallback_model = await self._select_model(alias)
        self._log_embedding_request(alias=alias, mode=mode, inputs=inputs)

        try:
            if mode == "proxy":
                raw = await self._proxy_embedding(alias, provider_input, kwargs)
            else:
                raw = await self._fallback_embedding(fallback_model, provider_input, kwargs)
        except _ProxyUnavailableError as exc:
            mode, provider_model, fallback_model = self._fallback_after_proxy_failure(alias, exc)
            self._log_embedding_request(alias=alias, mode=mode, inputs=inputs)
            raw = await self._fallback_embedding(fallback_model, provider_input, kwargs)

        usage = _usage(raw)
        resolved_model = _provider_model(raw, provider_model)
        self._log_response(
            operation="embedding",
            alias=alias,
            mode=mode,
            provider_model=resolved_model,
            usage=usage,
            latency_seconds=time.perf_counter() - start,
        )
        return EmbeddingResponse(
            embeddings=_embedding_vectors(raw),
            model_alias=alias,
            provider_model=resolved_model,
            usage=usage,
            raw=raw,
        )

    async def _select_model(self, alias: str) -> tuple[_Mode, str, FallbackModelConfig | None]:
        if self.config.proxy_url:
            try:
                aliases = await self._list_proxy_models()
            except _ProxyUnavailableError as exc:
                return self._fallback_after_proxy_failure(alias, exc)
            if alias not in aliases:
                raise _missing_alias_error(alias, aliases)
            return "proxy", alias, None
        return self._select_fallback(alias)

    async def _list_proxy_models(self) -> list[str]:
        if self._proxy_aliases_cache is not None:
            return list(self._proxy_aliases_cache)
        assert self.config.proxy_url is not None
        url = f"{self.config.proxy_url.rstrip('/')}/v1/models"
        try:
            response = await self.http_client.get(url, headers=self._proxy_headers())
        except httpx.RequestError as exc:
            raise _ProxyUnavailableError(str(exc)) from exc
        self._check_proxy_response(response, None)
        aliases = _extract_proxy_aliases(response.json())
        self._proxy_aliases_cache = aliases
        return list(aliases)

    async def _proxy_chat(
        self,
        alias: str,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> Any:
        assert self.config.proxy_url is not None
        request_kwargs = dict(kwargs)
        api_key = request_kwargs.pop("api_key", None)
        payload = {"model": alias, "messages": messages, **request_kwargs}
        try:
            response = await self.http_client.post(
                f"{self.config.proxy_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=self._proxy_headers(api_key),
            )
        except httpx.RequestError as exc:
            raise _ProxyUnavailableError(str(exc)) from exc
        self._check_proxy_response(response, alias)
        return response.json()

    async def _proxy_embedding(
        self,
        alias: str,
        provider_input: str | list[str],
        kwargs: dict[str, Any],
    ) -> Any:
        assert self.config.proxy_url is not None
        request_kwargs = dict(kwargs)
        api_key = request_kwargs.pop("api_key", None)
        payload = {"model": alias, "input": provider_input, **request_kwargs}
        try:
            response = await self.http_client.post(
                f"{self.config.proxy_url.rstrip('/')}/v1/embeddings",
                json=payload,
                headers=self._proxy_headers(api_key),
            )
        except httpx.RequestError as exc:
            raise _ProxyUnavailableError(str(exc)) from exc
        self._check_proxy_response(response, alias)
        return response.json()

    async def _fallback_chat(
        self,
        fallback_model: FallbackModelConfig | None,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> Any:
        if fallback_model is None:
            raise LLMClientError("Fallback model was not selected")
        try:
            return await _litellm().acompletion(
                model=fallback_model.provider_model,
                messages=messages,
                **self._litellm_kwargs(fallback_model, kwargs),
            )
        except Exception as exc:
            self._raise_if_unreachable(fallback_model, exc)
            self._raise_if_provider_error(fallback_model, exc)
            raise

    async def _fallback_embedding(
        self,
        fallback_model: FallbackModelConfig | None,
        provider_input: str | list[str],
        kwargs: dict[str, Any],
    ) -> Any:
        if fallback_model is None:
            raise LLMClientError("Fallback model was not selected")
        try:
            return await _litellm().aembedding(
                model=fallback_model.provider_model,
                input=provider_input,
                **self._litellm_kwargs(fallback_model, kwargs),
            )
        except Exception as exc:
            self._raise_if_unreachable(fallback_model, exc)
            self._raise_if_provider_error(fallback_model, exc)
            raise
