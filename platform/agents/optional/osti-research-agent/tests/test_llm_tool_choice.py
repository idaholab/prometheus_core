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

"""chat_model(..., forced_tool_choice=False) never sends a forced tool choice,
which Claude on Bedrock rejects ("tool_choice: type "tool" and "any" are not
supported for this model")."""

import pytest
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM

from research_agent.core.config import AgentConfig
from research_agent.core.llm import chat_model


@tool
def grader_response(result: str) -> str:
    """Structured output stand-in."""
    return result


def _bound_tool_choice(model, tool_choice):
    bound = model.bind_tools([grader_response], tool_choice=tool_choice)
    return bound.kwargs.get("tool_choice")


def _config():
    return AgentConfig(litellm_base_url="http://proxy:4000", litellm_api_key="k")


@pytest.mark.parametrize("forced", ["any", "required", True, "grader_response"])
def test_forced_choices_become_auto(forced):
    model = chat_model(_config(), "verifier", forced_tool_choice=False)

    assert _bound_tool_choice(model, forced) == "auto"


@pytest.mark.parametrize("choice", [None, "auto", "none"])
def test_unforced_choices_pass_through(choice):
    model = chat_model(_config(), "verifier", forced_tool_choice=False)

    assert _bound_tool_choice(model, choice) == choice


def test_default_model_still_forces_when_asked():
    model = chat_model(_config(), "verifier")

    assert type(model) is ChatLiteLLM
    assert _bound_tool_choice(model, "any") == "required"


def test_auto_model_keeps_the_route():
    model = chat_model(_config(), "verifier", forced_tool_choice=False)

    assert isinstance(model, ChatLiteLLM)
    assert (model.model, model.api_base) == ("medium", "http://proxy:4000")
