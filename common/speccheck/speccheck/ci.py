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

"""The GitHub Actions context of a run: where it ran, and links to its run and job.

See plan/design.md, "Job links" and "Job names". Everything here comes from environment variables.
The workflow sets `SPECCHECK_PRODUCER` and `SPECCHECK_JOB_ID` (from `${{ job.check_run_id }}`).
The rest are GitHub's own `GITHUB_*` variables. A job's display name isn't among them; the final
job looks those up (`--job-names`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PRODUCER_VAR = "SPECCHECK_PRODUCER"
"""The producer this run reports as."""
JOB_ID_VAR = "SPECCHECK_JOB_ID"
"""The job's numeric check run ID, from `${{ job.check_run_id }}`; optional."""

SERVER = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?$")
"""A server URL safe to build links from: https, a host name, an optional port, nothing else."""
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
"""`owner/name`."""
DIGITS = re.compile(r"^[1-9][0-9]{0,19}$")
"""A positive run, attempt or job ID."""
SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
"""A full SHA-1 or SHA-256 commit hash."""


PROVIDER = "github"
"""The `ci.provider` value of a GitHub Actions run, the only CI provider so far."""


def in_github_actions(env: Mapping[str, str]) -> bool:
    """Whether this is a GitHub Actions run."""
    return env.get("GITHUB_ACTIONS") == "true"


def _number(value: Any) -> int | None:
    """A positive integer from a string or an int, or None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and DIGITS.match(value):
        return int(value)
    return None


def context(env: Mapping[str, str]) -> dict[str, Any] | None:
    """The `ci` block of a results file header, or None outside GitHub Actions."""
    if not in_github_actions(env):
        return None
    block: dict[str, Any] = {
        "provider": PROVIDER,
        "server": env.get("GITHUB_SERVER_URL", ""),
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "workflow": env.get("GITHUB_WORKFLOW", ""),
        "job": env.get("GITHUB_JOB", ""),
        "run_id": _number(env.get("GITHUB_RUN_ID")),
        "run_attempt": _number(env.get("GITHUB_RUN_ATTEMPT")) or 1,
        "job_id": _number(env.get(JOB_ID_VAR)),
        "sha": env.get("GITHUB_SHA", ""),
        "ref": env.get("GITHUB_REF", ""),
        "event": env.get("GITHUB_EVENT_NAME", ""),
    }
    block["run_url"] = run_url(block)
    block["job_url"] = job_url(block)
    return block


def run_url(ci: Mapping[str, Any]) -> str:
    """The run attempt's URL, or "" when the parts aren't safe to build a link from."""
    server, repository = ci.get("server"), ci.get("repository")
    run_id, attempt = _number(ci.get("run_id")), _number(ci.get("run_attempt"))
    if not (isinstance(server, str) and SERVER.match(server)):
        return ""
    if not (isinstance(repository, str) and REPOSITORY.match(repository)) or run_id is None:
        return ""
    url = f"{server}/{repository}/actions/runs/{run_id}"
    return f"{url}/attempts/{attempt}" if attempt else url


def repository_url(env: Mapping[str, str]) -> str:
    """`<server>/<owner>/<repo>` from this run's `GITHUB_SERVER_URL` and `GITHUB_REPOSITORY`, or "".

    The only base a report links to: a results file's own URLs are not trusted to name the host.
    """
    server, repository = env.get("GITHUB_SERVER_URL", ""), env.get("GITHUB_REPOSITORY", "")
    if not (SERVER.fullmatch(server) and REPOSITORY.fullmatch(repository)):
        return ""
    return f"{server}/{repository}"


def job_url(ci: Mapping[str, Any]) -> str:
    """The job's own URL when its ID is known, else the run's URL, else ""."""
    run = run_url(ci)
    job_id = _number(ci.get("job_id"))
    if not run or job_id is None:
        return run
    # A job URL has no attempt in it: each attempt's job has its own ID.
    base = run.split("/attempts/", 1)[0]
    return f"{base}/job/{job_id}"


def commit_url(env: Mapping[str, str]) -> str:
    """`<server>/<owner>/<repo>/blob/<sha>`, where this run's files are browsed, or "" outside CI.

    Built from this run's own variables only, never a results file's, as `repository_url` is.
    """
    base, sha = repository_url(env), env.get("GITHUB_SHA", "")
    return f"{base}/blob/{sha}" if base and SHA.fullmatch(sha) else ""


def repository_root(start: Path, env: Mapping[str, str]) -> Path | None:
    """The repository's root folder: `GITHUB_WORKSPACE` in CI, else the nearest folder above `start`
    with a `.git`, else None. Found without running git."""
    workspace = env.get("GITHUB_WORKSPACE", "")
    if workspace:
        return Path(workspace).resolve()
    for folder in (start.resolve(), *start.resolve().parents):
        if (folder / ".git").exists():
            return folder
    return None


def from_root(path: Path, root: Path | None) -> str | None:
    """`path` as a path from the repository's root (`.` for the root itself), or None when it isn't under it."""
    if root is None:
        return None
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
