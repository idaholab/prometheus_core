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

"""``submit_answer``: the orchestrator's answer, checked before it is used.

The orchestrator writes the answer itself, from the analysis packages that
``read_top_candidates`` returns (``RunContext.analysis_packages``: one per
verified finding, numbered ``Paper N``). Code checks its length and that every
``Paper N`` names a package. Then a separate grader LLM, on the verifier
route, checks it against ``prompts/answer_grader.md``. The grader sees only
the question, the packages and the answer, never the orchestrator's
transcript, search results or abstracts, so it judges the answer by the
packages alone. It can ask for one revision (``MAX_ANSWER_ATTEMPTS``). A
code-check refusal does not use up that revision; it has its own limit
(``MAX_CODE_REFUSALS``).

Only an accepted answer is used. Otherwise the runner renders the verified
findings per paper. Every submitted answer is kept in
``RunContext.answer_drafts`` with its outcome, for the evaluation transcript.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

from research_agent import llm_steps
from research_agent.core.llm import chat_model
from research_agent.tools import progress
from research_agent.tools.context import RunContext

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
GRADER_PROMPT = (_PROMPTS_DIR / "answer_grader.md").read_text(encoding="utf-8")
# The grader gives one verdict per numbered criterion; a "satisfied" that
# accounts for fewer is refused.
RUBRIC_CRITERIA = len(re.findall(r"^\d+\. ", GRADER_PROMPT, re.MULTILINE))

# A graded draft and one graded revision.
MAX_ANSWER_ATTEMPTS = 2
# Code-check refusals (empty, too long, a citation with no package) allowed
# on top of those. They cost no grader call, but the orchestrator has no
# model-call limit of its own, so they are capped too.
MAX_CODE_REFUSALS = 3
# The prompt asks for less than the hard limit, so a slightly long answer is
# still accepted.
PROMPT_MAX_CHARS = 3000
MAX_ANSWER_CHARS = 4000
GRADER_TIMEOUT_S = 120.0

_CITATION = re.compile(r"Paper\s*(\d+)")

_DONE = (
    "The answer is accepted and final. Do not call submit_answer or "
    "read_top_candidates again; end with a one-line message."
)
_GIVE_UP = (
    "Do not call submit_answer again. End with a one-line message; the "
    "verified findings will be shown per paper instead."
)


class GraderError(ValueError):
    """The grader gave no usable verdict."""


def citations_valid(text: str, paper_count: int) -> bool:
    """True when the text cites at least one paper and every cited number is
    1..paper_count. Linkification and provenance depend on this numbering."""
    cited = {int(n) for n in _CITATION.findall(text)}
    return bool(cited) and all(1 <= n <= paper_count for n in cited)


def code_check(text: str, paper_count: int) -> Optional[str]:
    """Why code refuses the answer before grading it, or None."""
    if not text:
        return "the answer is empty"
    if len(text) > MAX_ANSWER_CHARS:
        return f"the answer is {len(text)} characters; keep it under {PROMPT_MAX_CHARS}"
    if not citations_valid(text, paper_count):
        return (
            "cite each factual paragraph or list item with `Paper N`, where N "
            f"is a package number from 1 to {paper_count}"
        )
    return None


def parse_verdict(text: str) -> Tuple[bool, List[str]]:
    """``(accepted, gaps)`` from the grader's JSON reply. Raises GraderError
    when the reply is not a usable verdict, so a bad reply never passes."""
    parsed = llm_steps.extract_json_from_text(text or "")
    if not isinstance(parsed, dict):
        raise GraderError("the grader did not reply with a JSON verdict")
    result, criteria = parsed.get("result"), parsed.get("criteria")
    if result not in ("satisfied", "needs_revision") or not isinstance(criteria, list):
        raise GraderError(f"the grader's verdict is not usable (result={result!r})")
    failed = [c for c in criteria if not (isinstance(c, dict) and c.get("passed") is True)]
    if result == "satisfied":
        if failed or len(criteria) < RUBRIC_CRITERIA:
            raise GraderError("the grader said satisfied without passing every criterion")
        return True, []
    gaps = [
        str(c.get("gap") or c.get("name"))
        for c in failed
        if isinstance(c, dict) and (c.get("gap") or c.get("name"))
    ]
    return False, gaps or [str(parsed.get("explanation") or "the grader gave no reason")]


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


def grader_input(question: str, packages: List[dict], answer: str) -> str:
    # The answer is the orchestrator's text, which has seen paper content:
    # it must not close its own tag and talk to the grader as the prompt.
    answer = answer.replace("</answer", "&lt;/answer")
    return (
        f"Research question:\n{question.strip()}\n\n"
        "Analysis packages (the only evidence; `Paper N` is the package whose "
        "`paper` is N):\n"
        f"{json.dumps(packages, indent=2)}\n\n"
        f"Answer to grade:\n<answer>\n{answer}\n</answer>"
    )


async def grade(ctx: RunContext, packages: List[dict], answer: str) -> Tuple[bool, List[str]]:
    """One grader call on the verifier route; see ``parse_verdict``."""
    from langchain_core.messages import HumanMessage, SystemMessage

    timeout = min(GRADER_TIMEOUT_S, ctx.seconds_left() - 10)
    if timeout <= 0:
        raise GraderError("no time left to grade the answer")
    model = chat_model(ctx.config, "verifier")
    reply = await asyncio.wait_for(
        model.ainvoke(
            [
                SystemMessage(content=GRADER_PROMPT),
                HumanMessage(content=grader_input(ctx.question, packages, answer)),
            ]
        ),
        timeout,
    )
    return parse_verdict(_text(reply.content))


def _rejected(problems: List[str], attempts_left: int, may_retry: bool = True) -> dict:
    instruction = (
        "Fix exactly these gaps, using only the packages, then call "
        "submit_answer once more with the full revised answer."
        if attempts_left and may_retry
        else _GIVE_UP
    )
    return {
        "accepted": False,
        "gaps": problems,
        "attempts_left": attempts_left if may_retry else 0,
        "instruction": instruction,
    }


def _short(text: str) -> str:
    return " ".join(text.split())[:300]


def _record(ctx: RunContext, answer: str, outcome: str, gaps: List[str]) -> None:
    ctx.answer_drafts.append({"answer": answer, "outcome": outcome, "gaps": list(gaps)})


async def submit(ctx: RunContext, answer: str) -> dict:
    """Check one submitted answer; see the module docstring."""
    packages = ctx.analysis_packages()
    if ctx.accepted_answer is not None and ctx.accepted_answer_papers == len(packages):
        return {"accepted": True, "instruction": _DONE}
    if not packages:
        return {
            "accepted": False,
            "error": "no analysis package was verified, so there is nothing to answer from",
            "instruction": "Do not call submit_answer without packages; read papers first, or end the run.",
        }
    if ctx.answer_attempts >= MAX_ANSWER_ATTEMPTS or ctx.code_refusals >= MAX_CODE_REFUSALS:
        return {"accepted": False, "error": "no answer attempts left", "instruction": _GIVE_UP}
    answer = str(answer or "").strip()

    problem = code_check(answer, len(packages))
    if problem:
        # Not a graded attempt: the grader's revision is still available.
        ctx.code_refusals += 1
        _record(ctx, answer, "refused by the code check", [problem])
        progress.emit(f"Answer refused by the code check: {problem}")
        return _rejected(
            [problem],
            MAX_ANSWER_ATTEMPTS - ctx.answer_attempts,
            may_retry=ctx.code_refusals < MAX_CODE_REFUSALS,
        )

    ctx.answer_attempts += 1
    attempts_left = MAX_ANSWER_ATTEMPTS - ctx.answer_attempts
    progress.emit(f"Grading the answer against {len(packages)} analysis package(s)...")
    try:
        accepted, gaps = await grade(ctx, packages, answer)
    except Exception as e:  # includes the timeout: fall back, never fail the run
        logger.warning("[answer] grader failed: %s", e)
        _record(ctx, answer, "not graded", [str(e) or type(e).__name__])
        progress.emit(
            f"The answer could not be graded ({_short(str(e) or type(e).__name__)}); "
            "the findings will be shown per paper"
        )
        ctx.answer_attempts = MAX_ANSWER_ATTEMPTS
        return {
            "accepted": False,
            "error": f"the answer could not be graded: {e}",
            "instruction": _GIVE_UP,
        }
    if accepted:
        ctx.accepted_answer = answer
        ctx.accepted_answer_papers = len(packages)
        _record(ctx, answer, "accepted", [])
        progress.emit("The grader accepted the answer")
        return {"accepted": True, "instruction": _DONE}
    _record(ctx, answer, "needs revision", gaps)
    progress.emit(f"The grader asked for a revision: {_short('; '.join(gaps))}")
    return _rejected(gaps, attempts_left)


def build_answer_tools(ctx: RunContext) -> List:
    from langchain_core.tools import tool

    @tool
    async def submit_answer(answer: str) -> str:
        """Submit the final answer to the research question, in Markdown,
        written from the analysis packages only and citing them as `Paper N`.
        Code checks the citations and length, then a separate grader checks
        the answer against the packages. Returns JSON {accepted, gaps,
        attempts_left, instruction}: follow the instruction."""
        return json.dumps(await submit(ctx, answer))

    return [submit_answer]
