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

"""Prompt rendering for the deep-agent engine.

The paper-analyzer's output schema is generated from ``core.events.Finding``
rather than hand-copied into ``analyzer.md``, so the prompt cannot drift from
the model the runner parses (``test_prompt_contract`` guards this).
"""

from __future__ import annotations

from pathlib import Path

from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

# One-line hint per Finding field, keyed by field name. Every field of Finding
# must appear here (enforced below) so a new field can't silently drop out of
# the analyzer's instructions.
_FINDING_FIELD_HINTS = {
    "source_id": "the paper's OSTI id (string)",
    "answer": "your answer to the question, from THIS paper only (string)",
    "evidence": "supporting data; cite the table/figure indices you used (string)",
    "excerpt": "a short exact quote from paper.md, or null",
    "artifacts": "paths of the artifact files you actually read (list of strings)",
    "match": '"exact" if the paper reports what was asked at the asked conditions, '
    '"nearest" if it reports only the closest data',
}

_missing = set(Finding.model_fields) - set(_FINDING_FIELD_HINTS)
if _missing:  # pragma: no cover - schema completeness check
    raise RuntimeError(
        f"analyzer prompt is missing hints for Finding fields: {sorted(_missing)}"
    )


def render_finding_schema() -> str:
    """A JSON skeleton of :class:`Finding`, one field per line, generated from
    the model so it stays in sync with what the runner parses."""
    names = list(Finding.model_fields)
    lines = ["{"]
    for i, name in enumerate(names):
        tail = "," if i < len(names) - 1 else ""
        lines.append(f'  "{name}": <{_FINDING_FIELD_HINTS[name]}>{tail}')
    lines.append("}")
    return "\n".join(lines)


def render_analyzer_prompt(config: AgentConfig) -> str:
    template = (_PROMPTS_DIR / "analyzer.md").read_text(encoding="utf-8")
    return template.format(
        finding_schema=render_finding_schema(),
        model_call_limit=config.analyzer_model_call_limit,
        tool_call_limit=config.analyzer_tool_call_limit,
    )


def render_verifier_prompt(model_call_limit: int, tool_call_limit: int) -> str:
    template = (_PROMPTS_DIR / "verifier.md").read_text(encoding="utf-8")
    return template.format(
        model_call_limit=model_call_limit,
        tool_call_limit=tool_call_limit,
    )


def render_orchestrator_prompt(config: AgentConfig) -> str:
    template = (_PROMPTS_DIR / "orchestrator.md").read_text(encoding="utf-8")
    budget_min = max(round(config.total_budget_s / 60), 1)
    return template.format(
        max_papers=config.max_papers_analyzed,
        max_osti_searches=config.max_osti_searches,
        max_scholarly_searches=config.max_scholarly_searches,
        budget_min=budget_min,
        parse_min="1-3",
    )
