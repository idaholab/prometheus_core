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

"""LLM judge for the evaluation: groundedness, completeness, and agreement with
each question's reviewer notes, scored 1-5 by a model on the verifier route.

The notes are the question's ``notes`` field minus its ``Access:`` tag; for the
UQ block that is the literature-review reference values ("Ref: ..."), for the
adversarial ones the expected behavior. ``reference_agreement`` is only scored
when a question has notes. A judge failure never fails the run: the record
gets ``judge_error`` and no scores.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from string import Template
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

PASS_SCORE = 4  # a judged question passes when every judged score is >= this
# A reply that can't be scored is asked for again once; the judge's replies
# vary, and one bad reply should not leave a question unjudged.
JUDGE_ATTEMPTS = 2
_SCORES = ("groundedness", "completeness", "reference_agreement")
_ACCESS_TAG = re.compile(r"\s*Access:.*$", re.DOTALL)
_PROMPT = Template((Path(__file__).with_name("judge_prompt.md")).read_text("utf-8"))
_MAX_ANSWER_CHARS = 6000
_MAX_FINDINGS_CHARS = 8000

CompleteFn = Callable[..., Awaitable[str]]


# Notes that say what a right answer is: reference values from the literature
# review, or the behavior expected. Other notes describe what a question is
# for ("exercises the arXiv path", "Duplicate of ...") and are not graded.
_GRADABLE_NOTES = re.compile(
    r"\bRef\b\s*(\(|:)|\bPinned anchor\b|\bexpect|\bpass (only )?if\b|\bfalse premise\b"
    r"|\ba good answer\b",
    re.IGNORECASE,
)


def reference_notes(spec: Dict[str, Any]) -> str:
    """The question's gradable notes without the source-access tag, or ''."""
    notes = _ACCESS_TAG.sub("", str(spec.get("notes") or "")).strip()
    return notes if _GRADABLE_NOTES.search(notes) else ""


def _findings_text(result: Dict[str, Any]) -> str:
    findings = [
        {
            "source_id": f.get("source_id"),
            "match": f.get("match") or "exact",
            "answer": f.get("answer"),
            "evidence": f.get("evidence"),
        }
        for f in result.get("findings") or []
        if isinstance(f, dict)
    ]
    text = json.dumps(findings, indent=1) if findings else "none"
    return text[:_MAX_FINDINGS_CHARS]


def build_prompt(result: Dict[str, Any], spec: Dict[str, Any]) -> str:
    return _PROMPT.substitute(
        question=str(spec.get("question", "")),
        status=str(result.get("status", "")),
        answer=str(result.get("answer") or "")[:_MAX_ANSWER_CHARS] or "(empty)",
        findings=_findings_text(result),
        notes=reference_notes(spec) or "none",
    )


def _score(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 1 <= value <= 5:
        return int(round(value))
    return None


def _lenient_fields(text: str) -> Dict[str, Any]:
    """Scores and rationale read field by field, for a reply that is almost
    JSON - most often a rationale with an unescaped quote in it."""
    data: Dict[str, Any] = {}
    for key in _SCORES:
        m = re.search(rf'"{key}"\s*:\s*(null|\d+)', text)
        if m:
            data[key] = None if m.group(1) == "null" else int(m.group(1))
    m = re.search(r'"rationale"\s*:\s*"(.*)"\s*\}?\s*$', text, re.DOTALL)
    if m:
        data["rationale"] = m.group(1).replace('\\"', '"')
    return data


def parse_verdict(text: str, *, has_notes: bool) -> Dict[str, Any]:
    """Parse the judge's JSON reply; raise ValueError when it is unusable."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("judge reply had no JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        data = _lenient_fields(match.group(0))
        if not data:
            raise ValueError(f"judge reply is not valid JSON: {e}") from e
    verdict = {key: _score(data.get(key)) for key in _SCORES}
    if verdict["groundedness"] is None or verdict["completeness"] is None:
        raise ValueError("judge reply is missing a 1-5 groundedness/completeness score")
    if not has_notes:
        verdict["reference_agreement"] = None
    elif verdict["reference_agreement"] is None:
        raise ValueError("judge reply is missing reference_agreement for a question with notes")
    verdict["rationale"] = str(data.get("rationale") or "").strip()[:500]
    return verdict


def judge_passed(record: Dict[str, Any]) -> Optional[bool]:
    """True/False when the record was judged, None when it was not."""
    scores = [record.get(f"judge_{key}") for key in _SCORES]
    judged = [s for s in scores if isinstance(s, int)]
    if not judged:
        return None
    return all(s >= PASS_SCORE for s in judged)


async def judge_result(
    result: Dict[str, Any], spec: Dict[str, Any], complete: CompleteFn
) -> Dict[str, Any]:
    """Judge one result; returns ``judge_*`` fields to merge into its record."""
    has_notes = bool(reference_notes(spec))
    prompt = build_prompt(result, spec)
    error: Optional[Exception] = None
    for attempt in range(JUDGE_ATTEMPTS):
        try:
            reply = await complete(prompt, max_tokens=600)
            verdict = parse_verdict(reply, has_notes=has_notes)
        except Exception as e:  # never fail the evaluation over the judge
            error = e
            logger.warning(
                "judge failed for %s (attempt %d/%d): %s",
                spec.get("id"), attempt + 1, JUDGE_ATTEMPTS, e,
            )
            continue
        return {f"judge_{key}": value for key, value in verdict.items()}
    return {"judge_error": str(error)[:300]}


def make_complete(config: Any) -> CompleteFn:
    """A completion function on the verifier model route of ``config``."""
    from research_agent.core.llm import LiteLLMClient

    route = config.model_route("verifier")
    return LiteLLMClient(route.base_url, route.api_key, route.model).complete
