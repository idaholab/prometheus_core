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

"""Local dev-loop entry point: research a question with only LLM credentials -
no A2A, prometheus_api, or Docker required.

    python -m research_agent "What is the creep rate of SS316 at 400C and 15 MPa?" \\
        --no-redis --workdir ./out
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from research_agent.core.config import AgentConfig
from research_agent.core.events import FinalResult, ProgressEvent
from research_agent.core.runner import ResearchRunner


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m research_agent")
    parser.add_argument("question", help="Research question to answer")
    parser.add_argument(
        "--no-redis",
        action="store_true",
        help="Run without Redis: skips the knowledge base and the PDF caches",
    )
    parser.add_argument(
        "--workdir", default=None, help="Where to write result.json (default: ./out)"
    )
    parser.add_argument("--run-id", default="cli", help="Run id used in logs")
    return parser.parse_args(argv)


async def _run(argv: Optional[List[str]]) -> int:
    args = _parse_args(argv)

    config = AgentConfig.from_env()
    updates = {"workdir": Path(args.workdir) if args.workdir else Path("./out")}
    if args.no_redis:
        updates["redis_url"] = None
    config = config.model_copy(update=updates)

    runner = ResearchRunner(config)
    final: Optional[FinalResult] = None

    async for event in runner.run(args.question, run_id=args.run_id):
        if isinstance(event, ProgressEvent):
            print(event.message, file=sys.stderr)
        else:
            final = event

    if final is None:
        print("No result produced.", file=sys.stderr)
        return 1

    config.workdir.mkdir(parents=True, exist_ok=True)
    result_path = config.workdir / "result.json"
    result_json = json.dumps(final.model_dump(mode="json"), indent=2, default=str)
    result_path.write_text(result_json)

    print(result_json)
    print(f"\nWrote {result_path}", file=sys.stderr)
    return 0 if final.status in ("completed", "no_results") else 1


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(_run(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
