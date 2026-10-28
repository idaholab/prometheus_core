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

from types import SimpleNamespace

from langchain_litellm import ChatLiteLLM

from research_agent.core.config import AgentConfig
from research_agent.core.llm import chat_model
from research_agent.core.model_profile import (
    apply_direct_model_profile,
    apply_model_profile,
)


def _model(alias, provider_model, api_base, api_key="provider-key"):
    return SimpleNamespace(
        alias=alias,
        provider_model=provider_model,
        litellm_params={
            "model": provider_model,
            "api_base": api_base,
            "api_key": api_key,
        },
    )


def test_direct_openai_compatible_profile_replaces_registry_routes():
    config = AgentConfig(
        litellm_base_url="http://litellm:4000",
        litellm_api_key="registry-key",
    )
    models = {
        "medium": _model(
            "medium",
            "openai/claude-sonnet",
            "https://litellm.example/v1",
        ),
        "embedding": _model(
            "embedding",
            "openai/text-embedding-3-large",
            "https://litellm.example/v1",
        ),
    }

    routed = apply_direct_model_profile(config, models)

    assert routed.model_route("orchestrator").model == "claude-sonnet"
    assert routed.model_route("analyzer").base_url == "https://litellm.example/v1"
    assert routed.model_route("verifier").model == "claude-sonnet"
    assert routed.model_route("embedding").model == "text-embedding-3-large"
    assert routed.model_route("orchestrator").api_key == "provider-key"


def test_registry_route_remains_the_default_without_direct_profile():
    config = AgentConfig(
        litellm_base_url="http://litellm:4000",
        litellm_api_key="registry-key",
    )

    route = config.model_route("orchestrator")

    assert route.base_url == "http://litellm:4000"
    assert route.api_key == "registry-key"
    assert route.model == "medium"
    assert config.model_route("verifier").model == "medium"


def test_registry_profile_replaces_environment_route():
    config = AgentConfig(
        litellm_base_url="http://stale-registry:4000",
        litellm_api_key="stale-key",
    )
    llm_config = SimpleNamespace(
        proxy_url="http://active-registry:4000",
        api_key="active-key",
    )

    routed = apply_model_profile(config, llm_config)

    route = routed.model_route("orchestrator")
    assert route.base_url == "http://active-registry:4000"
    assert route.api_key == "active-key"
    assert route.model == "medium"


def test_direct_profile_load_failure_is_not_hidden():
    class BrokenProfile:
        proxy_url = None

        @staticmethod
        def load_fallback_models():
            raise ValueError("invalid direct profile")

    config = AgentConfig(litellm_base_url="http://unused")

    try:
        apply_model_profile(config, BrokenProfile())
    except ValueError as exc:
        assert str(exc) == "invalid direct profile"
    else:
        raise AssertionError("direct-profile loading failure was hidden")


def _assert_tool_binding(model):
    bound = model.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search for evidence.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )

    assert bound.kwargs["tools"][0]["function"]["name"] == "search"


def test_registry_profile_builds_tool_capable_chat_litellm():
    config = AgentConfig(
        litellm_base_url="http://litellm:4000",
        litellm_api_key="registry-key",
    )

    model = chat_model(config, "orchestrator")

    assert isinstance(model, ChatLiteLLM)
    assert model.model == "medium"
    assert model.api_base == "http://litellm:4000"
    assert model.api_key == "registry-key"
    assert model.custom_llm_provider == "openai"
    assert model.temperature is None
    _assert_tool_binding(model)


def test_direct_openai_profile_builds_chat_litellm():
    config = AgentConfig(litellm_base_url="http://unused")
    routed = apply_direct_model_profile(
        config,
        {
            "medium": _model(
                "medium",
                "openai/claude-sonnet",
                "https://litellm.example/v1",
            ),
            "embedding": _model(
                "embedding",
                "openai/text-embedding-3-large",
                "https://litellm.example/v1",
            ),
        },
    )

    model = chat_model(routed, "analyzer")

    assert isinstance(model, ChatLiteLLM)
    assert model.model == "claude-sonnet"
    assert model.api_base == "https://litellm.example/v1"
    assert model.custom_llm_provider == "openai"
    assert model.temperature is None
    _assert_tool_binding(model)


def test_direct_anthropic_profile_builds_chat_litellm():
    config = AgentConfig(litellm_base_url="http://unused")
    routed = apply_direct_model_profile(
        config,
        {
            "medium": _model(
                "medium",
                "anthropic/claude-sonnet",
                "https://api.anthropic.com/v1",
            ),
            "embedding": _model(
                "embedding",
                "openai/text-embedding-3-large",
                "https://embeddings.example/v1",
            ),
        },
    )

    model = chat_model(routed, "verifier")

    assert isinstance(model, ChatLiteLLM)
    assert model.model == "claude-sonnet"
    assert model.api_base == "https://api.anthropic.com/v1"
    assert model.custom_llm_provider == "anthropic"
    assert model.temperature is None
    _assert_tool_binding(model)


def test_litellm_runtime_mcp_dependency_is_installed():
    from mcp.types import Tool

    assert Tool is not None
