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
"""Small LLM helpers shared by the deep-agent engine: lenient JSON
extraction from model replies, and follow-up query suggestions built from
verified findings."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from research_agent.core.llm import CompleteFn
from research_agent.prompt_templates import FOLLOWUP_FROM_FINDINGS_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


def extract_json_from_text(text: str) -> Optional[Any]:
    """Extract JSON from text that may contain markdown code blocks."""
    # Try to find JSON in code blocks first
    json_match = re.search(r"```json\s*(\[.*?\]|\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object or array
    json_match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


async def suggest_followup_from_findings(
    question: str,
    findings: List[Dict[str, Any]],
    complete: CompleteFn,
    limit: int = 3,
) -> List[Dict[str, str]]:
    """Generate follow-up queries from verified findings only.

    Returns no suggestions without findings: a follow-up should point past what
    the papers actually showed, not past an answer that has no evidence."""
    if not findings:
        return []
    prompt = FOLLOWUP_FROM_FINDINGS_PROMPT_TEMPLATE.format(
        question=question,
        findings_json=json.dumps(
            [
                {
                    "title": f.get("title", ""),
                    "answer": f.get("answer", ""),
                    "evidence": str(f.get("evidence", ""))[:800],
                }
                for f in findings[:10]
            ],
            indent=2,
        ),
        limit=limit,
    )
    return await _complete_suggestions(prompt, complete, limit)


async def _complete_suggestions(
    prompt: str, complete: CompleteFn, limit: int
) -> List[Dict[str, str]]:
    suggestions: List[Dict[str, str]] = []
    seen = set()

    try:
        response_text = await complete(prompt, max_tokens=512)
        parsed = extract_json_from_text(response_text)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    candidate = str(
                        item.get("suggested_query") or item.get("query") or ""
                    ).strip()
                else:
                    candidate = str(item or "").strip()
                if not candidate:
                    continue
                key = candidate.lower()
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append({"suggested_query": candidate})
                if len(suggestions) >= limit:
                    break
    except Exception as exc:
        logger.warning(f"Failed to generate follow-up suggestions via model: {exc}")

    return suggestions
