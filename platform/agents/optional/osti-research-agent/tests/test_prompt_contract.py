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

"""Verify that the paper-analyzer prompt schema stays synchronized with
``core.events.Finding`` so the runner can parse the requested output.

These tests need no langchain - they exercise only the prompt rendering.
"""

from research_agent.core import prompts
from research_agent.core.events import Finding


def test_every_finding_field_is_in_the_rendered_schema():
    schema = prompts.render_finding_schema()
    for name in Finding.model_fields:
        assert f'"{name}"' in schema, f"Finding.{name} missing from rendered schema"
    assert "confidence" not in Finding.model_fields
    assert '"confidence"' not in schema


def test_analyzer_prompt_embeds_the_finding_schema():
    from research_agent.core.config import AgentConfig

    prompt = prompts.render_analyzer_prompt(
        AgentConfig(
            litellm_base_url="http://unused",
            analyzer_model_call_limit=7,
            analyzer_tool_call_limit=11,
        )
    )
    # Placeholder must have been substituted...
    assert "{finding_schema}" not in prompt
    assert "{model_call_limit}" not in prompt
    assert "{tool_call_limit}" not in prompt
    assert "at most 7 model turns and 11 filesystem calls" in " ".join(prompt.split())
    # ...and every Finding field must reach the analyzer's instructions.
    for name in Finding.model_fields:
        assert f'"{name}"' in prompt, f"Finding.{name} missing from analyzer prompt"
    # The "couldn't answer" alternative must survive .format() (escaped braces).
    assert '"answered": false' in prompt


def test_hint_guard_is_exhaustive():
    # The module-level guard in prompts.py raises if Finding gains a field with
    # no hint; if this import succeeded, the hint map already covers every field.
    assert set(prompts._FINDING_FIELD_HINTS) >= set(Finding.model_fields)


def test_orchestrator_prompt_renders_budget_placeholders():
    from research_agent.core.config import AgentConfig

    config = AgentConfig(
        litellm_base_url="http://unused", total_budget_s=600, max_papers_analyzed=4
    )
    prompt = prompts.render_orchestrator_prompt(config)
    assert "{max_papers}" not in prompt and "{budget_min}" not in prompt
    assert "4" in prompt  # max_papers_analyzed
    assert "10 minutes" in prompt  # round(600/60)


def test_orchestrator_requires_findings_only_grounding():
    from research_agent.core.config import AgentConfig

    prompt = prompts.render_orchestrator_prompt(
        AgentConfig(litellm_base_url="http://unused")
    )
    normalized_prompt = " ".join(prompt.split())

    assert "Search titles, abstracts, and snippets are triage signals" in prompt
    assert "Cached answers and facts are also triage signals" in prompt
    assert "Base every factual claim" in prompt
    assert "do not estimate, extrapolate, or" in prompt
    assert "analyze_paper(source_id=<original source id>" in prompt
    assert "`task` tool" not in prompt
    assert "paper's directory path" not in prompt
    assert "Never use placeholder or example search queries" in prompt
    assert (
        "record that result and do not call `analyze_paper` for that source again"
        in normalized_prompt
    )


def test_verifier_prompt_is_read_only_and_treats_artifacts_as_untrusted():
    prompt = prompts.render_verifier_prompt(6, 8)

    assert "at most 6 model turns and 8 filesystem calls" in " ".join(prompt.split())
    assert "untrusted data" in prompt
    assert "Do not search the web, execute commands, write files" in prompt
    assert "`supported`, `corrected`, or `rejected`" in prompt
    assert "confidence" not in prompt
