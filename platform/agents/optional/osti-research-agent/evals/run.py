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

"""Evaluation runner: run each question through the agent and score the
results.

    # needs the agent's LLM profile in the env (LLM_CONFIG_PROFILE and its
    # key); Redis optional but required for the cache-repeat questions.
    uv run python -m evals run --report evals/report.json

For LangSmith traces set LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY before
running (the deep engine's astream is already instrumented by langgraph).

This module wires ResearchRunner to the offline metrics in ``evals.scoring``
and the LLM judge in ``evals.judge``, and writes the reports. Read 5
transcripts by hand as well: a model judge can be wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import redis
import yaml

from evals import judge
from evals import report as render
from evals import scoring
from evals.console import make_console, print_summary
from evals.progress import Progress, ProgressLogHandler
from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult, ProgressEvent
from research_agent.core.model_profile import apply_model_profile
from research_agent.core.runner import ResearchRunner


def _load_questions(path: Path) -> List[Dict[str, Any]]:
    data = yaml.safe_load(path.read_text())
    questions = data.get("questions", []) if isinstance(data, dict) else data
    if not questions:
        raise SystemExit(f"no questions found in {path}")
    return questions


def _select_questions(
    questions: List[Dict[str, Any]],
    ids: Optional[List[str]],
    categories: Optional[List[str]],
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    """Filter by id and category (both optional), then apply --limit."""
    if ids:
        known = {str(q.get("id")) for q in questions}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise SystemExit(f"unknown question id(s): {', '.join(unknown)}")
        questions = [q for q in questions if str(q.get("id")) in ids]
    if categories:
        questions = [q for q in questions if q.get("category") in categories]
    if limit:
        questions = questions[:limit]
    if not questions:
        raise SystemExit("no questions match the given filters")
    return questions


def _configured_agent_config(llm_config: Any) -> AgentConfig:
    """Resolve the same model profile the A2A agent uses."""
    return apply_model_profile(AgentConfig.from_env(), llm_config)


def _load_agent_config() -> AgentConfig:
    try:
        from prometheus_api.llm_client import LLMConfig
    except ImportError as exc:
        raise RuntimeError(
            "The parity evaluation must run in the OSTI agent runtime, "
            "where prometheus_api is installed."
        ) from exc

    return _configured_agent_config(LLMConfig.from_env())


def _redis_url_with_db(redis_url: str, db: int) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(redis_url)
    return urlunsplit(parsed._replace(path=f"/{db}"))


ENGINES = ("deepagent",)


def _require_empty_redis(config: AgentConfig, engine: str) -> None:
    client = redis.Redis.from_url(
        config.redis_url,
        password=config.redis_password,
        decode_responses=True,
    )
    try:
        size = client.dbsize()
    finally:
        client.close()
    if size:
        raise RuntimeError(
            f"Redis database selected for {engine} is not empty ({size} keys). "
            "Choose unused databases so engines cannot reuse prior answers."
        )


async def _run_one(
    config: AgentConfig,
    question: str,
    run_id: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> tuple[Optional[FinalResult], float, List[str]]:
    runner = ResearchRunner(config)
    final: Optional[FinalResult] = None
    log: List[str] = []
    start = time.monotonic()
    async for event in runner.run(question, run_id=run_id):
        if isinstance(event, ProgressEvent):
            log.append(f"+{time.monotonic() - start:.1f}s {event.message}")
            if on_progress is not None:
                on_progress(event.message)
        else:
            final = event
    return final, time.monotonic() - start, log


async def _run_engine(
    engine: str,
    questions: List[Dict[str, Any]],
    base: AgentConfig,
    workdir: Path,
    redis_db: Optional[int],
    on_record: Optional[Callable[[Dict[str, Any]], Any]] = None,
    progress: Optional[Progress] = None,
    judge_complete: Optional[judge.CompleteFn] = None,
) -> List[Dict[str, Any]]:
    updates: Dict[str, Any] = {"workdir": workdir / engine}
    if redis_db is not None:
        updates["redis_url"] = _redis_url_with_db(base.redis_url, redis_db)
    config = base.model_copy(update=updates)
    if redis_db is not None:
        _require_empty_redis(config, engine)

    records: List[Dict[str, Any]] = []
    for spec in questions:
        qid = spec["id"]
        if progress is not None:
            progress.begin(engine, qid, spec["question"])
        final, wall_s, log = await _run_one(
            config,
            spec["question"],
            f"eval-{engine}-{qid}",
            on_progress=progress.update if progress is not None else None,
        )
        result = (
            final.model_dump(mode="json")
            if final
            else {"status": "error", "answer": "no result"}
        )
        result["_engine"] = engine
        result["_wall_s"] = round(wall_s, 2)

        # Persist the full transcript for the manual spot-check.
        out_dir = workdir / engine / qid
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
        (out_dir / "progress.log").write_text("\n".join(log))

        record = scoring.score_result(result, spec)
        if judge_complete is not None:
            if progress is not None:
                progress.update("Judging the answer...")
            record.update(await judge.judge_result(result, spec, judge_complete))
        if progress is not None:
            progress.finish(record)
        records.append(record)
        if on_record is not None:
            on_record(record)
    return records


async def _main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--questions", default="evals/questions.yaml")
    # One engine today; kept as a list so reports keep their per-engine shape
    # if another engine is added.
    parser.add_argument(
        "--engines", nargs="+", choices=list(ENGINES), default=list(ENGINES)
    )
    parser.add_argument("--workdir", default="evals/out")
    parser.add_argument("--report", default="evals/report.json")
    parser.add_argument(
        "--limit", type=int, default=None, help="only the first N questions"
    )
    parser.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=None,
        help="only this question id (repeatable)",
    )
    parser.add_argument(
        "--category",
        dest="categories",
        action="append",
        default=None,
        help="only questions in this category (repeatable), e.g. core, uq",
    )
    parser.add_argument(
        "--markdown",
        default=None,
        help="Markdown report path (default: report.json's path with .md)",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="skip the LLM judge (groundedness, completeness, reference agreement)",
    )
    parser.add_argument("--no-redis", action="store_true")
    parser.add_argument(
        "--redis-db-base",
        type=int,
        default=None,
        help=(
            "first empty Redis database reserved for this evaluation; each engine "
            "uses the next database so cached answers cannot cross engines"
        ),
    )
    args = parser.parse_args(argv)

    questions = _select_questions(
        _load_questions(Path(args.questions)), args.ids, args.categories, args.limit
    )

    base = _load_agent_config()
    if args.no_redis:
        if args.redis_db_base is not None:
            parser.error("--no-redis and --redis-db-base cannot be used together")
        base = base.model_copy(update={"redis_url": None})
    elif args.redis_db_base is not None and base.redis_url is None:
        parser.error("--redis-db-base requires REDIS_URL")
    elif len(args.engines) > 1 and args.redis_db_base is None:
        parser.error(
            "--redis-db-base is required for multi-engine runs so cached answers "
            "cannot cross engines"
        )
    if args.redis_db_base is not None and args.redis_db_base < 0:
        parser.error("--redis-db-base must be non-negative")
    workdir = Path(args.workdir)

    report_path = Path(args.report)
    markdown_path = Path(args.markdown) if args.markdown else report_path.with_suffix(".md")
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    question_text = {str(q["id"]): str(q.get("question", "")) for q in questions}
    all_records: List[Dict[str, Any]] = []

    def write_reports(complete: bool) -> Dict[str, Any]:
        report = {
            "questions": len(questions),
            "engines": args.engines,
            "redis_db_base": args.redis_db_base,
            "started_at": started_at,
            "complete": complete,
            "records": all_records,
            "aggregate": scoring.aggregate(all_records),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render.markdown_report(
                report,
                transcripts_dir=os.path.relpath(workdir, markdown_path.parent),
                questions=question_text,
            )
        )
        return report

    def on_record(record: Dict[str, Any]) -> None:
        # Rewritten after every question so a long run that dies keeps its results.
        all_records.append(record)
        write_reports(complete=False)

    judge_complete = None if args.no_judge else judge.make_complete(base)
    out = make_console()
    err = make_console(stderr=True)
    progress = Progress(total=len(questions) * len(args.engines), console=err)
    log_handler = ProgressLogHandler(progress)
    root_logger = logging.getLogger()
    # The agent's own INFO logs would scroll the bar away; keep warnings.
    previous_handlers, previous_level = root_logger.handlers[:], root_logger.level
    root_logger.handlers = [log_handler]
    root_logger.setLevel(logging.WARNING)
    try:
        async with progress:
            for index, engine in enumerate(args.engines):
                redis_db = (
                    args.redis_db_base + index
                    if args.redis_db_base is not None
                    else None
                )
                await _run_engine(
                    engine,
                    questions,
                    base,
                    workdir,
                    redis_db,
                    on_record=on_record,
                    progress=progress,
                    judge_complete=judge_complete,
                )
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Ctrl+C: asyncio.run cancels this task. Keep what finished and stop
        # cleanly instead of re-raising into a traceback.
        report = write_reports(complete=False)
        err.print(
            f"\n[bold yellow]Interrupted[/] after {len(all_records)} of "
            f"{len(questions) * len(args.engines)} question(s)."
        )
        if all_records:
            print_summary(out, report)
        err.print(f"\nPartial report: {report_path}, {markdown_path}", markup=False)
        return INTERRUPTED_EXIT
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    report = write_reports(complete=True)
    print_summary(out, report)
    err.print(
        f"\nWrote {report_path}, {markdown_path} and transcripts under {workdir}/",
        markup=False,
    )
    return 0


# The shell's exit code for a process stopped by Ctrl+C (128 + SIGINT).
INTERRUPTED_EXIT = 130


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return asyncio.run(_main(argv if argv is not None else sys.argv[1:]))
    except KeyboardInterrupt:
        # A second Ctrl+C while the partial report is being written.
        print("\nInterrupted.", file=sys.stderr)
        return INTERRUPTED_EXIT


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
