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

"""Deep-agent engine: drive the ``create_deep_agent`` graph and translate its
LangGraph stream into the same ``AgentEvent`` stream the pipeline engine emits,
so the A2A executor and CLI are unchanged.

- ``custom`` stream chunks (emitted by the tools via ``get_stream_writer``)
  become ``ProgressEvent``s directly.
- ``updates`` chunks (node state deltas) are translated into human-readable
  tool-call statuses and todo updates. The ``analyze_paper`` tool returns only
  verified Findings, which are captured into ``ctx.findings`` so the
  runner can salvage a ``timeout_partial`` if the outer budget fires.
- The answer is the one the orchestrator submitted through ``submit_answer``
  and the grader accepted (``tools/answer.py``), written from the verified
  analysis packages; without one, the verified findings are rendered per
  paper. Either way the ``FinalResult`` gets linkified provenance.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from research_agent import citations, llm_steps
from research_agent.core.config import AgentConfig
from research_agent.core.deep_agent import build_research_agent
from research_agent.core.events import AgentEvent, FinalResult, Finding, ProgressEvent
from research_agent.core.llm import CompleteFn
from research_agent.tools import RunContext

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 80

# tool name -> human-readable status shown in the UI (matches the tone of the
# pipeline engine's emit() messages).
_TOOL_STATUS = {
    "search_osti": "Searching OSTI database...",
    "search_scholarly": "Searching open literature (OpenAlex/arXiv)...",
    "search_web": "Searching the web...",
    "rank_candidates": "Ranking search results against the question...",
    "read_top_candidates": "Reading the top-ranked papers...",
    "download_paper": "Downloading paper...",
    "parse_paper": "Parsing paper (tables + figures)...",
    "analyze_paper": "Analyzing and verifying paper...",
    "search_knowledge_base": "Checking knowledge base...",
    "store_facts": "Storing facts in knowledge base...",
    "write_todos": "Updating plan...",
    "record_abstract_evidence": "Checking a statement against an abstract...",
    "record_estimate": "Checking and computing a best-effort estimate...",
    "submit_answer": "Checking the answer against the analysis packages...",
}


def _tool_call_status(name: str, args: dict) -> str:
    base = _TOOL_STATUS.get(name, f"Running {name}...")
    query = args.get("query") if isinstance(args, dict) else None
    if query and name == "search_osti":
        return f"Searching OSTI for: {query}"
    if query and name == "search_scholarly":
        return f"Searching open literature for: {query}"
    if query and name == "search_web":
        return f"Searching the web for: {query}"
    return base


def _capture_finding(content: str, ctx: RunContext) -> None:
    """Capture the verified result returned by ``analyze_paper``."""
    parsed = llm_steps.extract_json_from_text(content)
    if not isinstance(parsed, dict):
        return
    if parsed.get("answered") is False:
        return
    if not parsed.get("source_id") or not parsed.get("answer"):
        return
    source_id = str(parsed["source_id"])
    if any(f.source_id == source_id for f in ctx.findings):
        return
    try:
        ctx.findings.append(
            Finding(
                source_id=source_id,
                answer=str(parsed.get("answer", "")),
                evidence=str(parsed.get("evidence", "") or ""),
                excerpt=parsed.get("excerpt"),
                artifacts=list(parsed.get("artifacts", []) or []),
            )
        )
    except (TypeError, ValueError) as e:
        logger.debug("[deep] could not coerce finding: %s", e)


def translate_update(chunk: Dict, ctx: RunContext) -> Iterator[ProgressEvent]:
    """Translate one ``updates`` chunk ({node: state_delta}) into ProgressEvents
    and capture any finding it carries."""
    if not isinstance(chunk, dict):
        return
    for node_out in chunk.values():
        if not isinstance(node_out, dict):
            continue
        todos = node_out.get("todos")
        if todos:
            yield ProgressEvent(
                kind="todo_update", message="Updated plan", detail={"todos": todos}
            )
        for msg in node_out.get("messages", []) or []:
            if isinstance(msg, AIMessage):
                for call in getattr(msg, "tool_calls", None) or []:
                    name = call.get("name", "") if isinstance(call, dict) else ""
                    args = call.get("args", {}) if isinstance(call, dict) else {}
                    yield ProgressEvent(
                        kind="tool_call",
                        message=_tool_call_status(name, args),
                        detail={"tool": name},
                    )
            elif isinstance(msg, ToolMessage):
                content = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
                if getattr(msg, "name", None) == "analyze_paper":
                    _capture_finding(content, ctx)


def _findings_to_answers(findings: List[Finding], search_hits: Dict) -> List[Dict]:
    """Shape findings like the pipeline's ``answers_found`` dicts so the existing
    provenance/linkify helpers work unchanged; titles/urls come from the search
    hits recorded when the paper was found."""
    answers = []
    for f in findings:
        hit = search_hits.get(f.source_id, {})
        url = hit.get("url", "")
        if not url and f.source_id.isdigit():
            url = f"https://www.osti.gov/biblio/{f.source_id}"
        answers.append(
            {
                "osti_id": f.source_id,
                "title": hit.get("title", ""),
                "url": url,
                "excerpt": (f.excerpt or f.evidence or "")[:500],
                "answer": f.answer,
                "evidence": f.evidence,
                "match": f.match,
            }
        )
    return answers


def _render_grounded_answer(answers: List[Dict]) -> str:
    """Render only claims already present in verified findings: each
    finding's answer (its values) and then its evidence (where they are in
    the paper). The verifier checked both against the paper."""
    sections = ["## Evidence-grounded findings"]
    for index, answer in enumerate(answers, 1):
        title = str(answer.get("title", "") or "").strip()
        heading = f"### Paper {index}"
        if title:
            heading += f": {title}"
        found = str(answer.get("answer", "") or "").strip()
        evidence = str(answer.get("evidence", "") or "").strip()
        grounded_text = " ".join(
            part for part in (found, f"Evidence: {evidence}" if evidence else "") if part
        )
        if answer.get("match") == "nearest":
            grounded_text = (
                "Nearest data reported (not at the exact conditions asked): "
                + grounded_text
            )
        sections.extend(
            [
                heading,
                f"{grounded_text} (Paper {index})",
            ]
        )

    limitation = (
        "The findings above are limited to what the analyzed papers report; "
        "no estimate or extrapolation was added to them."
    )
    if any(a.get("match") == "nearest" for a in answers):
        limitation += (
            " Findings marked as nearest data were reported at other conditions "
            "than those asked; they are not values at the asked conditions."
        )
    sections.extend(["## Limitations", limitation])
    return "\n\n".join(sections)


def _link(title: str, url: str, source_id: str) -> str:
    title = " ".join(str(title or source_id).split()).replace("[", "(").replace("]", ")")
    return f"[{title}]({url})" if url else title


def _render_weaker_evidence(ctx: RunContext) -> str:
    """Abstract evidence, estimates and the papers read without a finding,
    rendered after the verified findings and clearly labelled."""
    sections = []
    if ctx.abstract_evidence:
        sections.append(_render_abstract_evidence(ctx))
    for estimate in ctx.estimates:
        sections.append(_render_estimate(estimate, ctx))
    if ctx.unused_papers:
        sections.append(_render_unused_papers(ctx))
    return "\n\n".join(sections)


def _render_unused_papers(ctx: RunContext) -> str:
    """Each paper read without a usable finding and why, built by code so the
    answer itself stays on the verified packages. The reason is the
    analyzer's or verifier's, not checked against the paper again."""
    lines = [
        "## Papers read without a usable finding",
        "These papers were read but gave no verified finding. The reason is "
        "the analyzer's or verifier's summary, not checked evidence.",
    ]
    for source_id, item in ctx.unused_papers.items():
        lines.append(
            f"- {_source_label(ctx, source_id)} (not used by the {item['by']}): "
            f"{item['reason']}"
        )
    return "\n\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:])


def _render_abstract_evidence(ctx: RunContext) -> str:
    lines = [
        "## From abstracts (full text not available)",
        "These statements come only from the abstracts of papers whose full "
        "text could not be read. They were checked against the abstract text, "
        "not against the papers themselves.",
    ]
    for item in ctx.abstract_evidence:
        lines.append(
            f"- {item['statement']} - abstract of "
            f"{_link(item['title'], item['url'], item['source_id'])}: "
            f"\"{item['quote']}\""
        )
    return "\n\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:])


def _number(value: float) -> str:
    return f"{value:.3g}"


def _source_label(ctx: RunContext, source_id: str) -> str:
    hit = ctx.search_hits.get(source_id, {})
    url = hit.get("url") or (
        f"https://www.osti.gov/biblio/{source_id}" if source_id.isdigit() else ""
    )
    return _link(hit.get("title"), url, source_id)


def _render_estimate(estimate: Dict, ctx: RunContext) -> str:
    """An estimate, labelled as one, with its method, every cited input, the
    formulas and the assumptions, so a reader can check or redo it."""
    unit = f" {estimate['unit']}" if estimate["unit"] else ""
    lines = [
        "## Best-effort estimate (not reported by any source)",
        f"**{estimate['quantity']}: about {_number(estimate['value'])}{unit} "
        f"(plausible range {_number(estimate['low'])} to "
        f"{_number(estimate['high'])}{unit}).** This is a calculation from the "
        "cited values below, not a measured or reported value, and it may "
        "extrapolate beyond the conditions those values were measured at.",
        f"Method: {estimate['method']}",
        "Inputs:",
    ]
    for item in estimate["inputs"]:
        what = f" ({item['quantity']})" if item["quantity"] else ""
        unit_text = f" {item['unit']}" if item["unit"] else ""
        lines.append(
            f"- `{item['name']}` = {item['value']}{unit_text}{what} - from "
            f"{_source_label(ctx, item['source_id'])}"
        )
    formulas = estimate["formulas"]
    lines.append(
        f"Formula: `{formulas['formula']}`; range from `{formulas['low_formula']}` "
        f"to `{formulas['high_formula']}`."
    )
    lines.append("Assumptions:")
    lines.extend(f"- {a}" for a in estimate["assumptions"])
    return "\n\n".join(lines[:3]) + "\n\n" + "\n".join(lines[3:])


def _weaker_provenance(ctx: RunContext) -> List[Dict]:
    seen, out = set(), []
    for item in ctx.abstract_evidence:
        if item["source_id"] in seen:
            continue
        seen.add(item["source_id"])
        out.append(
            {
                "source": f"abstract: {item['source_id']}",
                "title": item["title"],
                "url": item["url"],
                "excerpt": item["quote"][:500],
                "evidence": "abstract",
            }
        )
    return out


async def build_final_result(question: str, ctx: RunContext) -> FinalResult:
    """Build the FinalResult from the verified findings, with linkified
    provenance. The answer is the orchestrator's graded one (``submit_answer``)
    when the grader accepted it and no finding was verified after it; otherwise
    the findings rendered per paper."""
    # Only engine-verified findings are authoritative: the orchestrator's own
    # messages are never parsed for evidence.
    findings = list(ctx.findings)
    answers = _findings_to_answers(findings, ctx.search_hits)
    if answers:
        graded = ctx.accepted_answer
        if graded is not None and ctx.accepted_answer_papers != len(answers):
            logger.info(
                "[answer] accepted answer covers %d of %d findings; using per-paper answer",
                ctx.accepted_answer_papers,
                len(answers),
            )
            graded = None
        answer_text = graded or _render_grounded_answer(answers)
        status = "completed"
    elif ctx.verification_errors:
        answer_text = (
            "The agent found candidate evidence, but source verification failed "
            "before any finding could be accepted."
        )
        status = "error"
    else:
        answer_text = (
            "No source-verified findings were available to answer the question."
        )
        status = "no_results"

    provenance, paper_to_provenance = citations.deduplicate_provenance_with_mapping(
        answers
    )
    answer_text = citations.linkify_paper_references(
        answer_text, provenance, paper_to_provenance
    )
    # Only the verified part is cached: later runs treat cached answers as
    # retrieval hints, and the weaker sections below must not become one.
    verified_answer = answer_text
    weaker = _render_weaker_evidence(ctx)
    if weaker:
        answer_text = f"{answer_text}\n\n{weaker}"
        provenance = provenance + _weaker_provenance(ctx)

    # From the verified findings only - not the rendered answer or search
    # titles - so a suggestion never builds on unverified material.
    suggested_queries = await llm_steps.suggest_followup_from_findings(
        question=question,
        findings=answers,
        complete=ctx.complete,
        limit=3,
    )

    if status == "completed" and ctx.knowledge is not None:
        # A retrieval hint for later runs (search_knowledge_base); those runs
        # still re-verify the sources before using any of it.
        await ctx.knowledge.cache_answer(question, verified_answer, provenance)

    return FinalResult(
        status=status,
        question=question,
        answer=answer_text,
        provenance=provenance,
        findings=findings,
        papers_analyzed=len(ctx.paper_analysis_results),
        facts_stored=ctx.facts_stored,
        suggested_queries=suggested_queries,
        searched_papers=dict(ctx.search_hits),
        answer_drafts=list(ctx.answer_drafts),
        question_topic=(
            {
                "subject": list(ctx.question_topic.subject),
                "quantity": list(ctx.question_topic.quantity),
            }
            if ctx.question_topic is not None
            else None
        ),
    )


# How many times a run that ends with no findings, while paper and time budget
# remain and downloadable results are unread, is sent back to read them. The
# orchestrator prompt asks for this too, but models stop early anyway.
MAX_NUDGES = 2
_NUDGE_RESULTS = 8


async def keep_going_nudge(ctx: RunContext) -> Optional[str]:
    """A follow-up instruction when the orchestrator stopped with nothing
    verified but could still read more, else None. Lists the unread results
    ``read_top_candidates`` would read, in its order
    (``RunContext.candidates_to_read``); with none, there is no nudge."""
    if ctx.findings or ctx.budget_reason() is not None:
        return None
    if not ctx.unread_hits():
        return None
    ranked, _ = await ctx.candidates_to_read()
    if not ranked:
        return None
    slots = ctx.config.max_papers_analyzed - ctx.papers_attempted
    lines = [
        f"You stopped with no verified findings, but {slots} paper slot(s) and "
        f"about {int(ctx.seconds_left() // 60)} minute(s) remain, and these "
        "search results are unread, most relevant to the question first:",
    ]
    for source_id, hit, _ in ranked[:_NUDGE_RESULTS]:
        title = " ".join(str(hit.get("title") or "").split())[:140]
        lines.append(f"- {source_id}: {title}")
    lines.append(
        "Call `read_top_candidates` now to read the next batch of them, in "
        "this order. A paper with the asked quantity for this material at any "
        'conditions is a useful `match: "nearest"` finding. Write and submit '
        "the answer only when it returns `stop: true`."
    )
    return "\n".join(lines)


# An estimate round needs time for one model turn plus the tool call.
_ESTIMATE_MIN_SECONDS = 60.0


def estimate_nudge(ctx: RunContext) -> Optional[str]:
    """A follow-up instruction when every finding is only nearest data, no
    estimate was made, and there is time left; else None.

    Models given nearest data (a creep rate at another temperature, a Norton
    exponent) stopped without trying record_estimate even when the inputs
    were in their own findings."""
    if not ctx.findings or ctx.estimates:
        return None
    if any(f.match == "exact" for f in ctx.findings):
        return None
    if ctx.seconds_left() < _ESTIMATE_MIN_SECONDS:
        return None
    sources = ", ".join(sorted({f.source_id for f in ctx.findings}))
    return (
        "Every verified finding is nearest data, not at the asked conditions "
        f"(sources: {sources}). If those findings give the inputs a standard "
        "relation needs - for example a rate at another temperature or stress "
        "plus a stress exponent and an activation energy, or coefficients of a "
        "fitted law - call record_estimate once now with the cited inputs, a "
        "low/high range, the method and every assumption, including how far "
        "it extrapolates. If they don't, do not estimate. Then finish as "
        "before: submit the answer if it was not accepted yet, else end with a "
        "one-line message. The estimate is shown in its own section, so leave "
        "it out of the answer."
    )


# A graded answer needs time for one model turn plus the grader call.
_ANSWER_MIN_SECONDS = 60.0


def answer_nudge(ctx: RunContext) -> Optional[str]:
    """A follow-up instruction when there are verified findings but no
    accepted answer covers all of them, an answer attempt is left, and there
    is time; else None. The packages are repeated so the answer can be
    written from this message alone."""
    from research_agent.tools.answer import MAX_ANSWER_ATTEMPTS, MAX_CODE_REFUSALS

    if not ctx.findings or ctx.answer_attempts >= MAX_ANSWER_ATTEMPTS:
        return None
    if ctx.code_refusals >= MAX_CODE_REFUSALS:
        return None
    if ctx.accepted_answer is not None and ctx.accepted_answer_papers == len(ctx.findings):
        return None
    if ctx.seconds_left() < _ANSWER_MIN_SECONDS:
        return None
    packages = ctx.analysis_packages()
    return (
        f"You stopped without an accepted answer, but {len(packages)} analysis "
        "package(s) are verified. Write the answer from these packages alone, "
        "as WRITING THE ANSWER says, and call submit_answer with it now:\n"
        f"{json.dumps(packages, indent=2)}"
    )


def _update_messages(chunk: Dict) -> List[Any]:
    out: List[Any] = []
    if isinstance(chunk, dict):
        for node_out in chunk.values():
            if isinstance(node_out, dict):
                out.extend(node_out.get("messages", []) or [])
    return out


async def run_deep(
    question: str,
    config: AgentConfig,
    run_id: str,
    *,
    complete: CompleteFn,
    redis_client=None,
    caches=None,
    pdf_cache=None,
    findings: Optional[List[Finding]] = None,
    search_hits: Optional[Dict[str, dict]] = None,
    deadline: Optional[float] = None,
) -> AsyncIterator[AgentEvent]:
    """Run the deep agent for one question, yielding ProgressEvents then a single
    FinalResult. ``findings`` (if given) is populated as papers are analyzed so a
    caller enforcing an outer budget can salvage partial results on timeout."""
    import time

    # One directory per turn: run_id is the conversation id, so two turns of
    # the same conversation must not share (or delete) each other's papers.
    run_workdir = config.workdir / f"{run_id}-{uuid.uuid4().hex[:8]}"
    try:
        ctx = RunContext(
            config=config,
            complete=complete,
            question=question,
            redis_client=redis_client,
            caches=caches,
            pdf_cache=pdf_cache,
            run_workdir=run_workdir,
            deadline=(
                deadline
                if deadline is not None
                else time.monotonic() + config.total_budget_s
            ),
        )
        # Embedding-backed fact/answer store over the same LiteLLM proxy and Redis
        # client. Degrades to empty results when redis_client is None.
        from research_agent.core.llm import LiteLLMEmbedder
        from research_agent.knowledge import RedisKnowledgeStore

        embedding_route = config.model_route("embedding")
        embedder = LiteLLMEmbedder(
            embedding_route.base_url,
            embedding_route.api_key,
            embedding_route.model,
        )
        ctx.knowledge = RedisKnowledgeStore(redis_client, embedder.embed)
        # The same embedder ranks search hits for rank_candidates and the nudge.
        ctx.embed_batch = embedder.embed_batch
        if findings is not None:
            ctx.findings = findings  # share the list so the runner can salvage it
        if search_hits is not None:
            ctx.search_hits = search_hits  # titles/urls for the salvaged partial

        agent = build_research_agent(config, ctx)

        # The graph has no checkpointer, so a follow-up round restarts from the
        # whole conversation so far plus the nudge.
        messages: List[Any] = [HumanMessage(content=question)]
        # Each kind of nudge has its own limit: keep-going MAX_NUDGES times,
        # the estimate and the answer nudge once each.
        keep_going_left, estimate_nudged, answer_nudged = MAX_NUDGES, False, False
        round_no = 0
        while True:
            round_messages: List[Any] = []
            async for mode, chunk in agent.astream(
                {"messages": messages},
                stream_mode=["updates", "custom"],
                config={
                    "recursion_limit": RECURSION_LIMIT,
                    "configurable": {"thread_id": f"{run_id}-{round_no}"},
                },
            ):
                if mode == "custom":
                    if isinstance(chunk, dict) and chunk.get("message"):
                        yield ProgressEvent(
                            message=chunk["message"], detail=chunk.get("detail")
                        )
                elif mode == "updates":
                    round_messages.extend(_update_messages(chunk))
                    for event in translate_update(chunk, ctx):
                        yield event
            round_no += 1
            nudge = await keep_going_nudge(ctx) if keep_going_left else None
            if nudge is not None:
                keep_going_left -= 1
                status = (
                    "No verified findings yet; reading unread results "
                    f"({ctx.config.max_papers_analyzed - ctx.papers_attempted} "
                    "paper slot(s) left)"
                )
            elif not estimate_nudged and (nudge := estimate_nudge(ctx)):
                estimate_nudged = True
                status = "Findings are only nearest data; asking for a cited estimate"
            elif not answer_nudged and (nudge := answer_nudge(ctx)):
                answer_nudged = True
                status = "No accepted answer yet; asking for one from the verified packages"
            else:
                break
            yield ProgressEvent(message=status)
            messages = [*messages, *round_messages, HumanMessage(content=nudge)]

        yield await build_final_result(question, ctx)
    finally:
        # Parsed papers are per-run scratch; durable state lives in Redis.
        shutil.rmtree(run_workdir, ignore_errors=True)
