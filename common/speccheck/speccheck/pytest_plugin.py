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

"""The pytest plugin: the `covers` marker, the collection check, and the results file.

Loaded by pytest through the `pytest11` entry point. It changes no test's outcome and does nothing
until asked:
- with `speccheck_config` in the ini options, collection fails on a claim the config doesn't allow;
- with `--speccheck-results=PATH` or `SPECCHECK_RESULTS`, the session writes a results file.

Under pytest-xdist each worker collects and runs its share of the tests and sends its claims and
outcomes back in `workeroutput`. Only the controller writes the file.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from speccheck import ci, results
from speccheck import config as config_module
from speccheck import specs as specs_module
from speccheck.evidence import claim_problem

MARKER = "covers"
"""The marker's name: `@pytest.mark.covers("SPC-REQ-001-01", ...)`."""
RESULTS_VAR = "SPECCHECK_RESULTS"
"""The environment variable that asks for a results file, when `--speccheck-results` isn't given."""
WORKER_KEY = "speccheck"
"""The `workeroutput` key a worker sends its claims under."""
NO_WRITE = (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERNAL_ERROR, pytest.ExitCode.USAGE_ERROR)
"""Exit statuses after which no results file is written: the run didn't finish, so it proves nothing."""

CLAIMS = pytest.StashKey[dict]()
"""The session's claims, by node ID: `{"covers", "file", "line", "outcome"}`."""


def pytest_addoption(parser: pytest.Parser) -> None:
    """`--speccheck-results`, and the `speccheck_config` and `speccheck_producer` ini options."""
    group = parser.getgroup("speccheck")
    group.addoption(
        "--speccheck-results",
        metavar="PATH",
        default=None,
        help=f"Write a speccheck results file here (default: ${RESULTS_VAR}; none when neither is set)",
    )
    parser.addini("speccheck_config", "speccheck.toml (or a pyproject.toml) whose claims collection checks")
    parser.addini("speccheck_producer", f"The producer the claims are checked against (default: ${ci.PRODUCER_VAR})")


def pytest_configure(config: pytest.Config) -> None:
    """Register the marker, and start the claims (shared with the controller on an xdist worker)."""
    config.addinivalue_line(
        "markers", f"{MARKER}(*ids): the spec requirements this test proves, such as SPC-REQ-001-01"
    )
    claims: dict[str, dict[str, Any]] = {}
    config.stash[CLAIMS] = claims
    workeroutput = getattr(config, "workeroutput", None)
    if workeroutput is not None:
        # xdist sends workeroutput when the worker finishes, so filling this dict in place is enough
        workeroutput[WORKER_KEY] = claims
    config.pluginmanager.register(Recorder(config), f"speccheck-recorder-{id(config)}")


def ids_of(item: pytest.Item) -> list[str]:
    """The IDs every `covers` mark on the test claims (function, class, module and parameter), each once."""
    found: list[str] = []
    for mark in item.iter_markers(MARKER):
        for value in mark.args:
            if value not in found:
                found.append(value)
    return found


def _bad_args(item: pytest.Item) -> str:
    """Why the test's `covers` marks are malformed, or ""."""
    for mark in item.iter_markers(MARKER):
        if mark.kwargs:
            return f"`{MARKER}` takes IDs only, not keywords ({', '.join(sorted(mark.kwargs))})"
        if not mark.args:
            return f"`{MARKER}` needs at least one ID"
        for value in mark.args:
            if not isinstance(value, str) or not value:
                return f'`{MARKER}` IDs are strings, such as "SPC-REQ-001-01"; got {value!r}'
    return ""


def _where(item: pytest.Item) -> tuple[str, int]:
    """The test's file and 1-based line, from pytest's own location.

    The node ID is written as is, parametrize IDs included, into artifacts CI keeps for weeks.
    Nothing scrubs it, so the README tells projects to keep secrets out of parametrize IDs.
    """
    path, line, _ = item.location
    return path, (line + 1 if line is not None else 0)


def _checker(config: pytest.Config):
    """A function giving the reason an ID may not be claimed (or ""), or None without `speccheck_config`.

    With `speccheck_config` a producer is required, from `SPECCHECK_PRODUCER` or `speccheck_producer`.
    """
    name = config.getini("speccheck_config")
    if not name:
        return None
    base = Path(config.inipath).parent if config.inipath else Path(config.rootpath)
    path = base / name
    try:
        loaded = config_module.load(path)
    except config_module.ConfigError as exc:
        raise pytest.UsageError(f"speccheck: {exc}") from None
    spec_set = specs_module.load(loaded.specs_dir, base, loaded.prefix, loaded.require_index)
    producer_name = os.environ.get(ci.PRODUCER_VAR) or config.getini("speccheck_producer")
    known = ", ".join(sorted(loaded.producers)) or "none"
    if not producer_name:
        # Without one, the check of which specs this run may claim would be skipped without a word
        raise pytest.UsageError(
            f"speccheck: no producer set; set `speccheck_producer` in the ini options or ${ci.PRODUCER_VAR} "
            f"(declared in {path}: {known})"
        )
    producer = loaded.producers.get(producer_name)
    if producer is None:
        raise pytest.UsageError(f"speccheck: producer `{producer_name}` isn't declared in {path} (declared: {known})")
    if producer.ci_job:
        raise pytest.UsageError(f"speccheck: `{producer_name}` is a [ci] job in {path}, not a test run")
    return lambda claimed: claim_problem(claimed, producer, spec_set)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Record every claiming test, before `-k` or `-m` deselects any, and fail on a claim that isn't allowed."""
    claims = config.stash[CLAIMS]
    checker = _checker(config)
    problems: list[str] = []
    for item in items:
        if not any(True for _ in item.iter_markers(MARKER)):
            continue
        path, line = _where(item)
        bad = _bad_args(item)
        if bad:
            problems.append(f"{path}:{line}: {item.nodeid}: {bad}")
            continue
        covers = ids_of(item)
        for claimed in covers if checker else ():
            why = checker(claimed)
            if why:
                problems.append(f"{path}:{line}: {item.nodeid}: {why}")
        claims[item.nodeid] = {"covers": covers, "file": path, "line": line, "outcome": "collected"}
    if problems:
        lines = "\n".join(specs_module.plain(p) for p in problems)
        raise pytest.UsageError(f"speccheck: {len(problems)} claim(s) the spec folder doesn't allow:\n{lines}")


def phase_outcome(report: pytest.TestReport) -> str | None:
    """What one phase's report says about the test, or None when it changes nothing (a passing setup or teardown)."""
    xfail = hasattr(report, "wasxfail")
    if report.when == "call":
        if report.passed:
            return "xpassed" if xfail else "passed"
        if report.skipped:
            return "xfailed" if xfail else "skipped"
        return "failed"
    if report.failed:
        return "error"
    if report.skipped:
        return "xfailed" if xfail else "skipped"
    return None


def merge(current: str, report: pytest.TestReport) -> str:
    """The outcome after one more phase: an error in setup or teardown wins over everything else."""
    new = phase_outcome(report)
    if new is None or current == "error":
        return current
    if report.when == "teardown" and new != "error":
        return current
    return new


RANK = {"collected": 0, "deselected": 1}
"""For merging workers' claims: any run outcome beats these, and deselected beats collected."""


class Recorder:
    """One session's hooks that need its claims: deselection, each phase's report, xdist workers, the file."""

    def __init__(self, config: pytest.Config) -> None:
        """Keep the config whose claims this records (pytester runs nested sessions in one process)."""
        self.config = config
        """The session's config."""
        self.claims: dict[str, dict[str, Any]] = config.stash[CLAIMS]
        """The session's claims, by node ID."""

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        """A deselected claiming test is written as `deselected`, so verify can say it didn't run."""
        for item in items:
            claim = self.claims.get(item.nodeid)
            if claim is not None:
                claim["outcome"] = "deselected"

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Merge each phase's report into the claiming test's outcome (on the process that ran it)."""
        claim = self.claims.get(report.nodeid)
        if claim is not None:
            claim["outcome"] = merge(claim["outcome"], report)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: Any) -> None:
        """On the xdist controller, merge a finished worker's claims: every worker collects every test, one runs it."""
        for nodeid, claim in getattr(node, "workeroutput", {}).get(WORKER_KEY, {}).items():
            current = self.claims.get(nodeid)
            if current is None or RANK.get(current["outcome"], 2) < RANK.get(claim["outcome"], 2):
                self.claims[nodeid] = dict(claim)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """Write the results file, from the controller only, unless the run was interrupted or never started."""
        if hasattr(self.config, "workerinput") or exitstatus in NO_WRITE:
            return
        path = results_path(self.config)
        if path is None:
            return
        results_file = results.ResultsFile(
            producer=os.environ.get(ci.PRODUCER_VAR) or self.config.getini("speccheck_producer") or "local",
            runner=f"pytest {pytest.__version__}",
            ci=ci.context(os.environ),
            started=self.started,
            results=[
                results.Result(
                    test=nodeid,
                    covers=claim["covers"],
                    outcome=claim["outcome"],
                    file=claim["file"],
                    line=claim["line"],
                )
                for nodeid, claim in sorted(self.claims.items())
            ],
        )
        try:
            results.write(path, results_file)
        except OSError as exc:
            raise pytest.UsageError(f"speccheck: can't write the results file: {exc}") from None

    started = ""
    """When the session started, ISO 8601 UTC; set by `pytest_sessionstart`."""

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        """Note when the session started."""
        self.started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def results_path(config: pytest.Config) -> Path | None:
    """Where to write the results file, or None when nobody asked for one."""
    value = config.getoption("speccheck_results") or os.environ.get(RESULTS_VAR)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path(config.invocation_params.dir) / path
