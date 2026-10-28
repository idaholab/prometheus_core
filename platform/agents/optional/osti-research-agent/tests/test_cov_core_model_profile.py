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

"""Coverage tests for direct-profile route resolution in core/model_profile.py."""

from types import SimpleNamespace

import pytest

from research_agent.core.config import AgentConfig
from research_agent.core.model_profile import apply_direct_model_profile

_CONFIG = AgentConfig(litellm_base_url="http://registry:4000")


def _model(alias, provider_model, params):
    return SimpleNamespace(alias=alias, provider_model=provider_model, litellm_params=params)


def _models(medium, embedding=None):
    return {"medium": medium, "embedding": embedding or medium}


def test_missing_api_base_raises_with_alias_name():
    broken = _model("medium", "openai/gpt", {"api_base": "   "})

    with pytest.raises(ValueError, match="'medium' is missing api_base"):
        apply_direct_model_profile(_CONFIG, _models(broken))


def test_anthropic_prefixed_model_routes_to_anthropic_provider():
    model = _model(
        "medium", "anthropic/claude-sonnet", {"base_url": "https://api.anthropic.com"}
    )

    routed = apply_direct_model_profile(_CONFIG, _models(model))

    route = routed.model_route("orchestrator")
    assert route.provider == "anthropic"
    assert route.model == "claude-sonnet"
    assert route.base_url == "https://api.anthropic.com"
    assert route.api_key is None


def test_bare_claude_model_on_anthropic_host_keeps_full_name():
    model = _model(
        "medium",
        "claude-3-opus",
        {"api_base": "https://api.anthropic.com/v1", "api_key": "ak"},
    )

    route = apply_direct_model_profile(_CONFIG, _models(model)).model_route("verifier")

    assert route.provider == "anthropic"
    assert route.model == "claude-3-opus"
    assert route.api_key == "ak"


def test_unknown_provider_falls_back_to_openai_with_full_model_name():
    model = _model("medium", "bedrock/some-model", {"api_base": "https://gw.example"})

    route = apply_direct_model_profile(_CONFIG, _models(model)).model_route("analyzer")

    assert route.provider == "openai"
    assert route.model == "bedrock/some-model"
