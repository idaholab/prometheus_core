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

"""`speccheck record`: the last step of a CI job that is itself evidence writes a passed result per ID it claims.

The job's IDs come from `[ci.<job>] covers = [...]` in the config, never from the command line, so
the claim is reviewed with the config. The step runs only when the steps before it succeeded.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from speccheck import ci, jsonout, results
from speccheck.config import ConfigError
from speccheck.context import Context

NAME = "record"
"""The command name."""
HELP = "Write a results file for this CI job's [ci.<job>] claims"
"""The one-line help."""
SECTION = "ci"
"""The `--help` section."""
ORDER = 20
"""Its place in the section."""

DEFAULT_DIR = ".speccheck"
"""Where the results file goes when neither `--output` nor SPECCHECK_RESULTS says."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The job name and where to write."""
    parser.add_argument("--job", metavar="NAME", help="The [ci.<job>] entry (default: $GITHUB_JOB)")
    parser.add_argument(
        "--output",
        metavar="FILE",
        help=f"The results file (default: $SPECCHECK_RESULTS, else {DEFAULT_DIR}/<job>.jsonl)",
    )


def run(ctx: Context, args: argparse.Namespace) -> int:
    """Write one `passed` result, of kind `ci`, for each ID the job claims."""
    config = ctx.config()
    job = args.job or ctx.env.get("GITHUB_JOB", "")
    if not job:
        raise ConfigError("no job name: pass --job NAME, or run inside a GitHub Actions job")
    producer = config.producers.get(job)
    if producer is None or not producer.ci_job:
        known = ", ".join(sorted(p.name for p in config.producers.values() if p.ci_job)) or "none"
        raise ConfigError(f"{config.path}: no [ci.{job}] entry for this job (CI jobs: {known})")
    output = args.output or ctx.env.get("SPECCHECK_RESULTS") or f"{DEFAULT_DIR}/{job}.jsonl"
    path = Path(output) if Path(output).is_absolute() else ctx.cwd / output
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results_file = results.ResultsFile(
        producer=job,
        runner=f"speccheck record {_version()}",
        ci=ci.context(ctx.env),
        started=started,
        results=[results.Result(test=job, covers=list(producer.covers), outcome="passed", kind="ci")],
    )
    results.write(path, results_file)
    if ctx.output.json_mode:
        body = jsonout.envelope(NAME, True, [], job=job, covers=list(producer.covers), path=str(path))
        jsonout.emit(body, ctx.output.out)
    ctx.output.summary(NAME, f"{job} recorded {', '.join(producer.covers)} in {output}", 0)
    return jsonout.EXIT_OK


def _version() -> str:
    """speccheck's version, for the results file's `runner`."""
    from speccheck import __version__

    return __version__
