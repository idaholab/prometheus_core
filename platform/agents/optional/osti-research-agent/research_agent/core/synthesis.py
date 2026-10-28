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

"""Cross-paper synthesis of verified findings, graded by ``RubricMiddleware``.

A small tool-less agent writes the answer from the verified findings only; a
grader on the verifier model route checks it against
``prompts/synthesis_rubric.md`` and can ask for one revision. The answer is
used only when the grader ends ``satisfied`` and the code checks below pass;
every other outcome returns ``None`` and the caller falls back to the
per-paper rendering.

The grader sees a transcript cut to ``_MAX_TRANSCRIPT_CHARS_PER_MESSAGE``
characters per message, so it reads the findings through
``read_verified_findings`` (tool results are not cut) and answers longer than
``MAX_ANSWER_CHARS`` are rejected outright: their tail would go ungraded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_agent.core.config import AgentConfig
from research_agent.core.llm import chat_model

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

SYNTHESIS_MAX_ITERATIONS = 2
# The prompt asks for less than the hard limit so a slightly long answer is
# still accepted; the hard limit leaves headroom under the grader's 4000.
PROMPT_MAX_CHARS = 3000
MAX_ANSWER_CHARS = 3800
SYNTHESIS_TIMEOUT_S = 120.0

_CITATION = re.compile(r"Paper\s*(\d+)")


def findings_payload(answers: List[Dict]) -> List[Dict[str, Any]]:
    """Number the findings the way the answer must cite them."""
    return [
        {
            "paper": index,
            "title": answer.get("title", ""),
            "answer": answer.get("answer", ""),
            "evidence": answer.get("evidence", ""),
            "excerpt": answer.get("excerpt", ""),
            "match": answer.get("match", "exact"),
        }
        for index, answer in enumerate(answers, 1)
    ]


def citations_valid(text: str, paper_count: int) -> bool:
    """True when the text cites at least one paper and every cited number is
    1..paper_count. Linkification and provenance depend on this numbering, so
    it is checked in code even after the grader passes."""
    cited = {int(n) for n in _CITATION.findall(text)}
    return bool(cited) and all(1 <= n <= paper_count for n in cited)


def _grader_class():
    """RubricMiddleware that also accepts a GraderResponse written as JSON text.

    The grader's model can't be forced to call the GraderResponse tool on
    Bedrock (it rejects forced tool choice), so with an "auto" choice it may
    answer in text instead. Those verdicts were lost as grader_error; a JSON
    reply is now parsed and validated like the structured one. Anything else
    still fails, so a bad reply never passes the grade."""
    from deepagents.middleware.rubric import GraderResponse, RubricMiddleware

    class TextTolerantRubricMiddleware(RubricMiddleware):
        @staticmethod
        def _extract_graded(result):
            if result.get("structured_response") is not None:
                return RubricMiddleware._extract_graded(result)
            graded = _graded_from_text(result)
            if graded is None:
                return RubricMiddleware._extract_graded(result)  # raises
            return GraderResponse.model_validate(graded)

    return TextTolerantRubricMiddleware


def _graded_from_text(result: Dict) -> Optional[Dict]:
    """The GraderResponse JSON object in the grader's last text reply, if any."""
    from research_agent import llm_steps

    text = _last_ai_text(result)
    parsed = llm_steps.extract_json_from_text(text) if text else None
    if isinstance(parsed, dict) and {"result", "criteria"} <= set(parsed):
        return parsed
    return None


def _build_synthesizer(config: AgentConfig, payload: List[Dict], on_evaluation):
    from langchain.agents import create_agent
    from langchain_core._api.beta_decorator import LangChainBetaWarning
    from langchain_core.tools import tool

    findings_json = json.dumps(payload, indent=2)

    @tool
    def read_verified_findings() -> str:
        """Return the complete verified findings, numbered as `paper`."""
        return findings_json

    system_prompt = (_PROMPTS_DIR / "synthesizer.md").read_text(encoding="utf-8")
    # RubricMiddleware is @beta and warns on every construction, i.e. every
    # answer; tests/test_synthesis.py pins the API it relies on instead.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LangChainBetaWarning)
        grader = _grader_class()(
            # The grader's structured GraderResponse would otherwise force a
            # tool call, which Claude on Bedrock rejects with a 400.
            model=chat_model(config, "verifier", forced_tool_choice=False),
            tools=[read_verified_findings],
            max_iterations=SYNTHESIS_MAX_ITERATIONS,
            on_evaluation=on_evaluation,
        )
    return create_agent(
        model=chat_model(config, "orchestrator"),
        tools=[],
        system_prompt=system_prompt.format(max_chars=PROMPT_MAX_CHARS),
        middleware=[grader],
        name="paper-synthesizer",
    )


def _last_ai_text(state: Dict) -> str:
    for message in reversed(state.get("messages", []) or []):
        if getattr(message, "type", None) != "ai":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


async def synthesize(
    question: str,
    answers: List[Dict],
    config: AgentConfig,
    *,
    seconds_left: float,
) -> Optional[str]:
    """Return a graded cross-paper answer, or None to use the fallback."""
    timeout = min(SYNTHESIS_TIMEOUT_S, seconds_left - 10)
    if not answers or timeout <= 0:
        return None

    payload = findings_payload(answers)
    evaluations: List[Dict] = []
    try:
        agent = _build_synthesizer(config, payload, evaluations.append)
        state = await asyncio.wait_for(
            agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Research question:\n{question.strip()}\n\n"
                                "Verified findings:\n"
                                f"{json.dumps(payload, indent=2)}"
                            ),
                        }
                    ],
                    "rubric": (_PROMPTS_DIR / "synthesis_rubric.md").read_text(
                        encoding="utf-8"
                    ),
                }
            ),
            timeout,
        )
    except Exception as e:  # includes the timeout: fall back, never fail the run
        logger.warning("[synthesis] failed, using per-paper answer: %s", e)
        return None

    last = evaluations[-1] if evaluations else {}
    if last.get("result") != "satisfied":
        gaps = [c.get("gap") for c in last.get("criteria", []) if not c.get("passed")]
        logger.info(
            "[synthesis] grader ended %s, using per-paper answer: %s",
            last.get("result"),
            gaps,
        )
        return None

    text = _last_ai_text(state)
    if len(text) > MAX_ANSWER_CHARS:
        logger.info(
            "[synthesis] answer too long to be fully graded (%d chars)", len(text)
        )
        return None
    if not citations_valid(text, len(answers)):
        logger.info("[synthesis] answer cites papers outside 1..%d", len(answers))
        return None
    return text
