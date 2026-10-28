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

"""Assemble the deep-agent orchestrator and its verified paper-analysis task."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from research_agent import llm_steps
from research_agent.core.config import AgentConfig
from research_agent.core.events import Finding
from research_agent.core.llm import chat_model
from research_agent.core.prompts import (
    render_analyzer_prompt,
    render_orchestrator_prompt,
    render_verifier_prompt,
)
from research_agent.tools import RunContext, build_tools, progress

PAPER_ANALYZER_NAME = "paper-analyzer"

logger = logging.getLogger(__name__)
_REGISTERED_PROFILE_KEYS: set[str] = set()


class PaperAnalysisTaskError(ValueError):
    """The orchestrator did not identify one parsed paper for analysis."""


class VerifierProtocolError(ValueError):
    """The verifier did not satisfy its structured-result contract."""


class VerifierModelLimitError(VerifierProtocolError):
    """The verifier exhausted its model-call budget before returning a verdict."""


class VerificationResult(BaseModel):
    """Internal structured response; the public Finding schema stays unchanged."""

    verdict: str
    source_id: str
    answer: str
    evidence: str
    excerpt: str
    artifacts: list[str]
    reason: str
    # Optional so older verifier replies stay valid; missing means the
    # candidate's label stands.
    match: str = ""


def _register_runtime_profiles(config: AgentConfig) -> None:
    """Disable Deep Agents' implicit general-purpose subagent for every role."""
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        register_harness_profile,
    )

    for role in ("orchestrator", "analyzer", "verifier"):
        route = config.model_route(role)
        profile_key = f"litellm:{route.model}"
        if profile_key in _REGISTERED_PROFILE_KEYS:
            continue
        register_harness_profile(
            profile_key,
            HarnessProfile(
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
            ),
        )
        _REGISTERED_PROFILE_KEYS.add(profile_key)


def _build_backend(run_workdir: Path):
    """Map the agent-visible ``/papers/`` tree onto one run's real workdir."""
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

    papers_root = Path(run_workdir) / "papers"
    papers_root.mkdir(parents=True, exist_ok=True)
    return CompositeBackend(
        default=StateBackend(),
        routes={"/papers/": FilesystemBackend(root_dir=str(papers_root))},
    )


def _read_only_paper_permissions():
    from deepagents.middleware.filesystem import FilesystemPermission

    return [
        FilesystemPermission(
            operations=["read"],
            paths=["/papers", "/papers/**"],
            mode="allow",
        ),
        FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]


def build_paper_analyzer(config: AgentConfig) -> dict:
    """Build the candidate analyzer specification used inside the verified task."""
    from langchain.agents.middleware import (
        ModelCallLimitMiddleware,
        ToolCallLimitMiddleware,
    )

    return {
        "name": PAPER_ANALYZER_NAME,
        "description": (
            "Analyze ONE parsed paper to answer a research question. Input: the "
            "research question and the paper's /papers/<id>/ directory. Returns a "
            'single Finding JSON (or {"answered": false, ...}).'
        ),
        "system_prompt": render_analyzer_prompt(config),
        "model": chat_model(config, "analyzer"),
        "tools": [],
        "permissions": _read_only_paper_permissions(),
        "middleware": [
            ToolCallLimitMiddleware(
                run_limit=config.analyzer_tool_call_limit,
                exit_behavior="continue",
            ),
            ModelCallLimitMiddleware(
                run_limit=config.analyzer_model_call_limit,
                exit_behavior="end",
            ),
        ],
    }


def build_paper_verifier(config: AgentConfig, backend) -> Any:
    """Compile a read-only verifier over the same per-run paper backend."""
    from deepagents import create_deep_agent
    from langchain.agents.middleware import (
        ModelCallLimitMiddleware,
        ToolCallLimitMiddleware,
    )

    return create_deep_agent(
        model=chat_model(config, "verifier"),
        tools=[],
        backend=backend,
        permissions=_read_only_paper_permissions(),
        system_prompt=render_verifier_prompt(
            config.verifier_model_call_limit,
            config.verifier_tool_call_limit,
        ),
        middleware=[
            ToolCallLimitMiddleware(
                run_limit=config.verifier_tool_call_limit,
                exit_behavior="continue",
            ),
            ModelCallLimitMiddleware(
                run_limit=config.verifier_model_call_limit,
                exit_behavior="end",
            ),
        ],
        name="paper-verifier",
    )


def _last_message_text(result: dict) -> str:
    for message in reversed(result.get("messages", []) or []):
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
            if text.strip():
                return text
    return ""


def _last_ai_message_text(result: dict) -> str:
    for message in reversed(result.get("messages", []) or []):
        if getattr(message, "type", None) != "ai":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
            if text.strip():
                return text
    return ""


def _parse_candidate(result: dict) -> tuple[Finding | None, str]:
    parsed = llm_steps.extract_json_from_text(_last_message_text(result))
    if not isinstance(parsed, dict):
        return None, "paper analyzer did not return a JSON object"
    if parsed.get("answered") is False:
        return None, str(parsed.get("reason") or "paper did not answer the question")
    try:
        finding = Finding.model_validate(parsed)
    except (TypeError, ValueError) as exc:
        return None, f"paper analyzer returned an invalid Finding: {exc}"
    if not finding.source_id or not finding.answer.strip():
        return None, "paper analyzer returned an incomplete Finding"
    return finding, ""


def _source_id_aliases(source_id: str) -> list[str]:
    """Return exact and OSTI DOI forms for one source identifier."""
    source_id = str(source_id).strip()
    aliases = [source_id]
    doi = source_id
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.casefold().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi_slug = doi.strip("/").replace("/", "_")
    if doi_slug and doi_slug not in aliases:
        aliases.append(doi_slug)

    prefix = "10.2172_"
    if doi_slug.casefold().startswith(prefix):
        osti_id = doi_slug[len(prefix) :]
        if osti_id.isdigit() and osti_id not in aliases:
            aliases.append(osti_id)
    elif source_id.isdigit():
        aliases.append(f"{prefix}{source_id}")
    return aliases


def _resolve_parsed_source_id(source_id: str, ctx: RunContext) -> str | None:
    parsed_by_casefold = {
        parsed_source_id.casefold(): parsed_source_id
        for parsed_source_id in ctx.parsed_papers
    }
    for alias in _source_id_aliases(source_id):
        resolved = parsed_by_casefold.get(alias.casefold())
        if resolved is not None:
            return resolved
    return None


def _parsed_paper_directory(source_id: str, ctx: RunContext) -> str:
    summary = ctx.parsed_papers.get(source_id)
    if not isinstance(summary, dict):
        raise PaperAnalysisTaskError(f"source {source_id!r} has not been parsed")

    raw_directory = summary.get("dir")
    if not isinstance(raw_directory, str) or not raw_directory.strip():
        raise PaperAnalysisTaskError(
            f"source {source_id!r} has no parsed paper directory"
        )

    visible_directory = PurePosixPath(raw_directory.rstrip("/"))
    if (
        visible_directory.parent != PurePosixPath("/papers")
        or not visible_directory.name
    ):
        raise PaperAnalysisTaskError(
            f"source {source_id!r} has invalid parsed directory {raw_directory!r}"
        )

    papers_root = (ctx.run_workdir / "papers").resolve()
    source_root = (papers_root / visible_directory.name).resolve()
    if not source_root.is_relative_to(papers_root) or not source_root.is_dir():
        raise PaperAnalysisTaskError(
            f"parsed directory {visible_directory} is unavailable"
        )
    return str(visible_directory)


def _analysis_description(question: str, paper_directory: str) -> str:
    # The nearest rule is in the system prompt too, but analyzers still declined
    # papers whose data sat outside the asked conditions; stating it with the
    # task, per paper, is what they act on.
    return (
        f"Research question:\n{question.strip()}\n\n"
        f"Parsed paper directory: {paper_directory}\n\n"
        "Analyze only this paper and return the required Finding JSON.\n\n"
        "If the paper reports the asked quantity for this material and the "
        "same phenomenon at ANY conditions - even far from those asked - do "
        'not answer `answered: false`: return a Finding with `match: "nearest"` '
        "holding the reported values closest to the asked conditions, and "
        "state the conditions they were reported at. Data on a different "
        "phenomenon (for example irradiation creep for a thermal-creep "
        "question) is not nearest data. Use `answered: false` only when the "
        "paper has no values of the asked quantity for this material and "
        "phenomenon at all."
    )


def _validated_artifacts(
    artifacts: list[str],
    paper_directory: str,
    ctx: RunContext,
    read_paths: set[str],
) -> list[str]:
    if not artifacts:
        raise VerifierProtocolError("accepted verification did not cite any artifact")

    visible_root = PurePosixPath(paper_directory)
    papers_root = (ctx.run_workdir / "papers").resolve()
    source_root = (papers_root / visible_root.name).resolve()
    validated = []
    for artifact in artifacts:
        visible_path = PurePosixPath(str(artifact))
        try:
            relative = visible_path.relative_to(visible_root)
        except ValueError as exc:
            raise VerifierProtocolError(
                f"artifact {artifact!r} is outside {paper_directory}"
            ) from exc
        if not relative.parts:
            raise VerifierProtocolError(f"artifact {artifact!r} does not name a file")
        if str(visible_path) not in read_paths:
            # meta.json is the paper's index (parse method, table and figure
            # captions), not evidence; verifiers copy the analyzer's citation
            # of it without reopening it. Drop it rather than lose the
            # finding. Every evidence file must still have been read.
            if relative.parts == ("meta.json",):
                continue
            raise VerifierProtocolError(f"verifier did not read artifact {artifact!r}")
        real_path = (source_root / Path(*relative.parts)).resolve()
        if not real_path.is_relative_to(source_root) or not real_path.is_file():
            raise VerifierProtocolError(f"artifact {artifact!r} does not exist")
        validated.append(str(visible_path))
    paper_path = str(visible_root / "paper.md")
    if paper_path not in read_paths:
        raise VerifierProtocolError("verifier did not independently read paper.md")
    if paper_path not in validated:
        raise VerifierProtocolError("accepted verification did not cite paper.md")
    return validated


def _read_file_paths(result: dict) -> set[str]:
    """Files whose text the verifier actually saw.

    ``read_file`` counts for its path. A ``grep`` in ``content`` mode counts
    too, for each file its result shows matching lines from: verifiers check a
    long paper.md by searching it for the claimed values rather than paging
    through it, and those matches are the file's own text. A grep that only
    listed file names, or matched nothing, shows no text and does not count."""
    paths = set()
    grep_calls = {}
    for message in result.get("messages", []) or []:
        for call in getattr(message, "tool_calls", None) or []:
            if not isinstance(call, dict):
                continue
            args = call.get("args", {})
            if not isinstance(args, dict):
                continue
            if call.get("name") == "read_file" and args.get("file_path"):
                paths.add(str(PurePosixPath(str(args["file_path"]))))
            elif call.get("name") == "grep" and args.get("output_mode") == "content":
                grep_calls[call.get("id")] = args
        if getattr(message, "type", None) == "tool" and message.tool_call_id in grep_calls:
            paths |= _grep_matched_files(_message_content(message))
    return paths


# deepagents formats content-mode grep output as a "/path/file.md:" header per
# file followed by indented "  12: <text>" match lines ("  12- <text>" for
# context lines). A file counts only when a matched line follows its header.
_GREP_FILE_HEADER = re.compile(r"^(/\S+):$")
_GREP_MATCH_LINE = re.compile(r"^\s+\d+:\s")


def _grep_matched_files(output: str) -> set[str]:
    files, current = set(), None
    for line in output.splitlines():
        header = _GREP_FILE_HEADER.match(line.rstrip())
        if header:
            current = str(PurePosixPath(header.group(1)))
        elif current and _GREP_MATCH_LINE.match(line):
            files.add(current)
    return files


def _message_content(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


def _verification_payload(result: dict) -> Any:
    if not isinstance(result, dict):
        raise VerifierProtocolError("verifier returned an invalid result state")

    structured = result.get("structured_response")
    if structured is not None:
        return structured

    text = _last_ai_message_text(result).strip()
    if text.startswith("Model call limits exceeded:"):
        raise VerifierModelLimitError(text)

    parsed = llm_steps.extract_json_from_text(text)
    if not isinstance(parsed, dict):
        raise VerifierProtocolError(
            "verifier returned neither a structured response nor a JSON verdict"
        )
    return parsed


def _validated_finding(
    raw_result: Any,
    candidate: Finding,
    paper_directory: str,
    ctx: RunContext,
    read_paths: set[str],
) -> tuple[Finding | None, str]:
    try:
        result = VerificationResult.model_validate(raw_result)
    except (TypeError, ValueError) as exc:
        raise VerifierProtocolError(
            "verifier returned an invalid VerificationResult"
        ) from exc
    verdict = result.verdict.strip().lower()
    if verdict == "rejected":
        return None, result.reason.strip() or "candidate was not supported"
    if verdict not in {"supported", "corrected"}:
        raise VerifierProtocolError(f"unknown verifier verdict {result.verdict!r}")
    if result.source_id != candidate.source_id:
        raise VerifierProtocolError("verifier changed the candidate source_id")
    if not result.answer.strip() or not result.evidence.strip():
        raise VerifierProtocolError("accepted verification omitted answer or evidence")

    match = (result.match or candidate.match).strip().lower()
    if match not in {"exact", "nearest"}:
        raise VerifierProtocolError(f"unknown verifier match {result.match!r}")
    return (
        Finding(
            source_id=result.source_id,
            answer=result.answer.strip(),
            evidence=result.evidence.strip(),
            excerpt=result.excerpt.strip() or None,
            match=match,
            artifacts=_validated_artifacts(
                result.artifacts,
                paper_directory,
                ctx,
                read_paths,
            ),
        ),
        result.reason.strip(),
    )


def _not_used(source_id: str, reason: str, ctx: RunContext, *, by: str) -> None:
    """Show and keep why a paper produced no finding, so a run that ends in
    no_results says which papers were read and why each was not used."""
    reason = " ".join(str(reason).split())[:300] or "no reason given"
    ctx.unused_papers[source_id] = {"by": by, "reason": reason}
    progress.emit(
        f"Paper {source_id} not used ({by}): {reason}",
        {"source_id": source_id, "not_used_by": by},
    )


def _operational_failure(
    *,
    source_id: str,
    kind: str,
    message: str,
    exc: Exception,
    ctx: RunContext,
    reason: str | None = None,
) -> dict:
    ctx.verification_errors.append(f"{source_id}: {kind}")
    # Running out of model calls is an expected budget outcome, not a bug:
    # one line, no traceback. Everything else keeps the traceback.
    logger.warning(
        "Paper analysis failed for source %s (%s): %s",
        source_id,
        kind,
        exc,
        exc_info=not isinstance(exc, VerifierModelLimitError),
    )
    progress.emit(
        message,
        {"source_id": source_id, "failure_kind": kind},
    )
    return {
        "answered": False,
        "reason": reason
        or f"{kind.replace('_', ' ')}; do not retry source {source_id}",
    }


def _verifier_failure_kind(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, VerifierModelLimitError):
        return (
            "verifier_model_limit",
            "Verifier model-call limit reached",
        )
    if isinstance(exc, VerifierProtocolError):
        return (
            "verifier_protocol_failure",
            "Verifier returned an invalid verdict",
        )
    return "verifier_provider_failure", "Verifier failed"


async def _analyze_and_verify(
    requested_source_id: str,
    question: str,
    paper_directory: str,
    *,
    analyzer,
    verifier,
    ctx: RunContext,
    runnable_config=None,
) -> dict:
    lock = ctx.paper_analysis_locks.setdefault(
        requested_source_id,
        asyncio.Lock(),
    )
    async with lock:
        cached = ctx.paper_analysis_results.get(requested_source_id)
        if cached is not None:
            progress.emit(
                f"Reusing paper-analysis result for source {requested_source_id}",
                {"source_id": requested_source_id},
            )
            return dict(cached)

        description = _analysis_description(question, paper_directory)
        try:
            analysis = await analyzer.ainvoke(
                {"messages": [{"role": "user", "content": description}]},
                config=runnable_config,
            )
        except Exception as exc:
            result = _operational_failure(
                source_id=requested_source_id,
                kind="analyzer_failure",
                message=f"Paper analyzer failed for source {requested_source_id}",
                exc=exc,
                ctx=ctx,
            )
            ctx.paper_analysis_results[requested_source_id] = result
            return dict(result)

        candidate, reason = _parse_candidate(analysis)
        if candidate is None:
            _not_used(requested_source_id, reason, ctx, by="analyzer")
            result = {"answered": False, "reason": reason}
            ctx.paper_analysis_results[requested_source_id] = result
            return dict(result)

        if candidate.source_id != requested_source_id:
            exc = PaperAnalysisTaskError(
                f"paper analyzer returned source {candidate.source_id!r} for "
                f"{requested_source_id!r}"
            )
            result = _operational_failure(
                source_id=requested_source_id,
                kind="task_source_mismatch",
                message=(
                    f"Paper analyzer returned the wrong source for "
                    f"{requested_source_id}"
                ),
                exc=exc,
                ctx=ctx,
            )
            ctx.paper_analysis_results[requested_source_id] = result
            return dict(result)

        progress.emit(
            f"Verifying evidence from source {candidate.source_id}",
            {"source_id": candidate.source_id},
        )
        try:
            verification = await verifier.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Original analysis task:\n{description}\n\n"
                                f"Parsed paper directory: {paper_directory}\n\n"
                                "Candidate Finding JSON:\n"
                                f"{candidate.model_dump_json()}"
                            ),
                        }
                    ]
                },
                config=runnable_config,
            )
            verified, reason = _validated_finding(
                _verification_payload(verification),
                candidate,
                paper_directory,
                ctx,
                _read_file_paths(verification),
            )
        except Exception as exc:
            kind, prefix = _verifier_failure_kind(exc)
            result = _operational_failure(
                source_id=requested_source_id,
                kind=kind,
                message=f"{prefix} for source {requested_source_id}",
                exc=exc,
                ctx=ctx,
            )
            ctx.paper_analysis_results[requested_source_id] = result
            return dict(result)

        if verified is None:
            logger.info(
                "Verifier rejected source %s: %s",
                candidate.source_id,
                reason,
            )
            progress.emit(
                f"Rejected unsupported finding from source {candidate.source_id}",
                {"source_id": candidate.source_id},
            )
            _not_used(candidate.source_id, reason, ctx, by="verifier")
            result = {"answered": False, "reason": reason}
            ctx.paper_analysis_results[requested_source_id] = result
            return dict(result)

        existing = next(
            (
                finding
                for finding in ctx.findings
                if finding.source_id == verified.source_id
            ),
            None,
        )
        if existing is None:
            ctx.findings.append(verified)
        else:
            verified = existing
        progress.emit(
            f"Verified evidence from source {verified.source_id}",
            {"source_id": verified.source_id},
        )
        result = verified.model_dump()
        ctx.paper_analysis_results[requested_source_id] = result
        return dict(result)


async def _analyze_paper(
    source_id: str,
    question: str,
    *,
    analyzer,
    verifier,
    ctx: RunContext,
    runnable_config=None,
) -> dict:
    source_id = str(source_id).strip()
    question = str(question).strip()
    request_key = json.dumps(
        {"source_id": source_id, "question": question},
        sort_keys=True,
    )
    cached_invalid = ctx.invalid_paper_analysis_results.get(request_key)
    if cached_invalid is not None:
        return dict(cached_invalid)

    try:
        if not source_id:
            raise PaperAnalysisTaskError("source_id is empty")
        if not question:
            raise PaperAnalysisTaskError("question is empty")
        resolved_source_id = _resolve_parsed_source_id(source_id, ctx)
        if resolved_source_id is None:
            progress.emit(
                f"Paper source {source_id!r} has not been parsed; "
                "download and parse it first",
                {"source_id": source_id, "failure_kind": "paper_not_parsed"},
            )
            return {
                "answered": False,
                "source_id": source_id,
                "reason": "paper has not been parsed",
                "required_action": (
                    "Call download_paper and parse_paper with this source_id, "
                    "then call analyze_paper again."
                ),
                "terminal": False,
            }
        if resolved_source_id != source_id:
            progress.emit(
                f"Resolved paper source {source_id!r} to " f"{resolved_source_id!r}",
                {
                    "source_id": resolved_source_id,
                    "requested_source_id": source_id,
                },
            )
        paper_directory = _parsed_paper_directory(resolved_source_id, ctx)
    except PaperAnalysisTaskError as exc:
        result = _operational_failure(
            source_id=source_id or "unknown",
            kind="task_path_failure",
            message=(
                f"Paper-analysis source {source_id!r} is not available "
                "as one parsed paper directory"
            ),
            exc=exc,
            ctx=ctx,
        )
        ctx.invalid_paper_analysis_results[request_key] = result
        return dict(result)

    return await _analyze_and_verify(
        resolved_source_id,
        question,
        paper_directory,
        analyzer=analyzer,
        verifier=verifier,
        ctx=ctx,
        runnable_config=runnable_config,
    )


def build_analyze_paper_tool(
    config: AgentConfig,
    ctx: RunContext,
    backend,
) -> Any:
    """Build the structured analyzer/verifier tool exposed to the orchestrator."""
    from deepagents import create_deep_agent
    from langchain_core.tools import tool

    _register_runtime_profiles(config)
    analyzer_spec = build_paper_analyzer(config)
    analyzer = create_deep_agent(
        model=analyzer_spec["model"],
        tools=analyzer_spec["tools"],
        backend=backend,
        permissions=analyzer_spec["permissions"],
        system_prompt=analyzer_spec["system_prompt"],
        middleware=analyzer_spec["middleware"],
        name="paper-analysis-candidate",
    )
    verifier = build_paper_verifier(config, backend)

    @tool
    async def analyze_paper(
        source_id: str,
        question: str,
        config: RunnableConfig,
    ) -> str:
        """Analyze and independently verify one parsed paper.

        Pass the exact source ID returned by search/parse and the research
        question. The runtime resolves the parsed paper directory.
        """
        result = await _analyze_paper(
            source_id,
            question,
            analyzer=analyzer,
            verifier=verifier,
            ctx=ctx,
            runnable_config=config,
        )
        if result.get("terminal") is False:
            return json.dumps(result)
        return json.dumps(
            {
                **result,
                "terminal": True,
                "instruction": (
                    "This source has a terminal paper-analysis result. Record it "
                    "and do not call analyze_paper for this source again."
                ),
            }
        )

    return analyze_paper


def build_research_agent(config: AgentConfig, ctx: RunContext) -> Any:
    """Compile the orchestrator with its mandatory verified paper tool."""
    from deepagents import create_deep_agent

    _register_runtime_profiles(config)
    backend = _build_backend(ctx.run_workdir)
    tools = build_tools(ctx)
    tools.append(build_analyze_paper_tool(config, ctx, backend))
    return create_deep_agent(
        model=chat_model(config, "orchestrator"),
        tools=tools,
        backend=backend,
        system_prompt=render_orchestrator_prompt(config),
    )
