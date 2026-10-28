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

"""Adapt resolved model profiles into core model routes."""

from collections.abc import Mapping
from typing import Any

from research_agent.core.config import AgentConfig, ModelRoute


def apply_model_profile(config: AgentConfig, llm_config: Any) -> AgentConfig:
    """Apply a registry or direct ``LLMConfig``-like profile to core config.

    This module deliberately accepts a structural object instead of importing
    ``prometheus_api`` so the research core keeps its transport boundary.
    """
    proxy_url = getattr(llm_config, "proxy_url", None)
    if proxy_url:
        return config.model_copy(
            update={
                "litellm_base_url": str(proxy_url),
                "litellm_api_key": getattr(llm_config, "api_key", None),
                "model_routes": {},
            }
        )

    return apply_direct_model_profile(
        config,
        llm_config.load_fallback_models(),
    )


def apply_direct_model_profile(
    config: AgentConfig,
    models: Mapping[str, Any],
) -> AgentConfig:
    """Use direct-profile endpoints instead of the local LiteLLM registry."""
    aliases = {
        "orchestrator": config.orchestrator_model,
        "analyzer": config.analyzer_model,
        "verifier": config.verifier_model,
        "vlm": config.vlm_model,
        "embedding": config.embedding_model,
    }
    routes = {role: _model_route(models[alias]) for role, alias in aliases.items()}
    return config.model_copy(update={"model_routes": routes})


def _model_route(model_config: Any) -> ModelRoute:
    params = model_config.litellm_params
    base_url = params.get("api_base") or params.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError(
            f"Direct model profile alias {model_config.alias!r} is missing api_base"
        )

    provider_model = str(model_config.provider_model)
    provider, separator, model = provider_model.partition("/")
    if separator and provider in {"openai", "hosted_vllm"}:
        langchain_provider = "openai"
    elif separator and provider == "anthropic":
        langchain_provider = "anthropic"
    elif provider_model.startswith("claude") and "anthropic.com" in base_url:
        langchain_provider = "anthropic"
        model = provider_model
    else:
        langchain_provider = "openai"
        model = provider_model

    api_key = params.get("api_key")
    return ModelRoute(
        provider=langchain_provider,
        base_url=base_url,
        api_key=str(api_key) if api_key else None,
        model=model,
    )
