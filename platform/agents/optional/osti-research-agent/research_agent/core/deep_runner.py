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
- The orchestrator's final JSON is parsed into a ``FinalResult`` with linkified
  provenance, reusing ``citations`` and ``llm_steps`` from the pipeline engine.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from research_agent import citations, llm_steps
from research_agent.core import synthesis
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
    "download_paper": "Downloading paper...",
    "parse_paper": "Parsing paper (tables + figures)...",
    "analyze_paper": "Analyzing and verifying paper...",
    "search_knowledge_base": "Checking knowledge base...",
    "store_facts": "Storing facts in knowledge base...",
    "write_todos": "Updating plan...",
    "record_abstract_evidence": "Checking a statement against an abstract...",
    "record_estimate": "Checking and computing a best-effort estimate...",
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


def _message_text(msg) -> str:
    """Extract plain text from a message's ``content`` (str, or a list of content
    parts), independent of langchain_core version niceties like ``.text()``."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content or "")


def _last_ai_text(chunk: Dict) -> Optional[str]:
    """The most recent non-empty AI message text in an updates chunk, if any -
    tracked across the stream to recover the orchestrator's final message."""
    if not isinstance(chunk, dict):
        return None
    latest = None
    for node_out in chunk.values():
        if not isinstance(node_out, dict):
            continue
        for msg in node_out.get("messages", []) or []:
            if isinstance(msg, AIMessage):
                text = _message_text(msg).strip()
                if text:
                    latest = text
    return latest


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
    """Render only claims already present in paper-analyzer findings."""
    sections = ["## Evidence-grounded findings"]
    for index, answer in enumerate(answers, 1):
        title = str(answer.get("title", "") or "").strip()
        heading = f"### Paper {index}"
        if title:
            heading += f": {title}"
        evidence = str(answer.get("evidence", "") or "").strip()
        grounded_text = evidence or str(answer.get("answer", "")).strip()
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
    """Abstract evidence, rendered after the verified findings and clearly
    labelled; every line was checked in code (tools/evidence.py)."""
    sections = []
    if ctx.abstract_evidence:
        sections.append(_render_abstract_evidence(ctx))
    for estimate in ctx.estimates:
        sections.append(_render_estimate(estimate, ctx))
    return "\n\n".join(sections)


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


async def build_final_result(
    question: str, final_text: str, ctx: RunContext
) -> FinalResult:
    """Parse the orchestrator's final JSON into a FinalResult with linkified
    provenance. Falls back to ``status="error"`` (keeping the raw text) if the
    final message isn't parseable JSON."""
    parsed = llm_steps.extract_json_from_text(final_text or "")
    # The orchestrator now ends with {"findings": [...]}; "answer" is still
    # accepted from older prompts. Neither key's content is used below.
    if not isinstance(parsed, dict) or not ({"findings", "answer"} & set(parsed)):
        logger.warning("[deep] final message was not parseable result JSON")
        return FinalResult(
            status="error",
            question=question,
            answer=(final_text or "The agent did not produce a final answer.").strip(),
            findings=list(ctx.findings),
            papers_analyzed=len(ctx.paper_analysis_results),
            searched_papers=dict(ctx.search_hits),
        )

    # Only engine-verified findings are authoritative. The orchestrator's final
    # array is deliberately ignored because it can contain cached or invented
    # entries that never passed source-artifact verification.
    findings = list(ctx.findings)
    answers = _findings_to_answers(findings, ctx.search_hits)
    if answers:
        # A cross-paper synthesis is used only when its grader is satisfied
        # and the code checks pass; otherwise render the findings verbatim.
        synthesized = await synthesis.synthesize(
            question, answers, ctx.config, seconds_left=ctx.seconds_left()
        )
        answer_text = synthesized or _render_grounded_answer(answers)
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
    )


# How many times a run that ends with no findings, while paper and time budget
# remain and downloadable results are unread, is sent back to read them. The
# orchestrator prompt asks for this too, but models stop early anyway.
MAX_NUDGES = 2
_NUDGE_RESULTS = 8


def _unread_results(ctx: RunContext) -> List[tuple]:
    """Search hits that could still be read: not yet downloaded or failed,
    and downloadable (an OSTI id, or an allowed PDF link)."""
    unread = []
    for source_id, hit in ctx.search_hits.items():
        if source_id in ctx.pdf_paths or source_id in ctx.download_failures:
            continue
        if source_id in ctx.parse_failures or source_id in ctx.paper_analysis_results:
            continue
        osti = source_id.isdigit() or str(hit.get("origin") or "osti") == "osti"
        if osti or hit.get("oa_pdf_url"):
            unread.append((source_id, hit))
    return unread


def keep_going_nudge(ctx: RunContext) -> Optional[str]:
    """A follow-up instruction when the orchestrator stopped with nothing
    verified but could still read more, else None."""
    if ctx.findings or ctx.budget_reason() is not None:
        return None
    unread = _unread_results(ctx)
    if not unread:
        return None
    slots = ctx.config.max_papers_analyzed - ctx.papers_attempted
    lines = [
        f"You stopped with no verified findings, but {slots} paper slot(s) and "
        f"about {int(ctx.seconds_left() // 60)} minute(s) remain, and these "
        "search results are unread:",
    ]
    for source_id, hit in unread[:_NUDGE_RESULTS]:
        title = " ".join(str(hit.get("title") or "").split())[:140]
        lines.append(f"- {source_id}: {title}")
    lines.append(
        "Download, parse and analyze the most promising of them now. A paper "
        "with the asked quantity for this material at any conditions is a "
        'useful `match: "nearest"` finding. Emit the final JSON only when none '
        "of them could bear on the question or the paper budget is used."
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
        "it extrapolates. If they don't, do not estimate. Then emit the final "
        "JSON again."
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
        if findings is not None:
            ctx.findings = findings  # share the list so the runner can salvage it
        if search_hits is not None:
            ctx.search_hits = search_hits  # titles/urls for the salvaged partial

        agent = build_research_agent(config, ctx)

        final_text = ""
        # The graph has no checkpointer, so a follow-up round restarts from the
        # whole conversation so far plus the nudge.
        messages: List[Any] = [HumanMessage(content=question)]
        estimate_nudged = False
        for round_no in range(MAX_NUDGES + 1):
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
                    text = _last_ai_text(chunk)
                    if text:
                        final_text = text
                    for event in translate_update(chunk, ctx):
                        yield event
            if round_no == MAX_NUDGES:
                break
            nudge = keep_going_nudge(ctx)
            if nudge is not None:
                status = (
                    "No verified findings yet; reading unread results "
                    f"({ctx.config.max_papers_analyzed - ctx.papers_attempted} "
                    "paper slot(s) left)"
                )
            elif not estimate_nudged and (nudge := estimate_nudge(ctx)):
                estimate_nudged = True
                status = "Findings are only nearest data; asking for a cited estimate"
            else:
                break
            yield ProgressEvent(message=status)
            messages = [*messages, *round_messages, HumanMessage(content=nudge)]

        if ctx.findings:
            yield ProgressEvent(
                message="Synthesizing across papers and checking it against the findings..."
            )
        yield await build_final_result(question, final_text, ctx)
    finally:
        # Parsed papers are per-run scratch; durable state lives in Redis.
        shutil.rmtree(run_workdir, ignore_errors=True)
