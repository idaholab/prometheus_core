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
outcomes back in `workeroutput`. Only the controller writes the file. A worker that crashes sends no
`workeroutput`, so the controller also keeps the outcome of every test from the reports xdist relays
to it, and uses that for a test whose claims only a replacement worker, which didn't run it, sent.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from speccheck import ci, claims, results
from speccheck import config as config_module
from speccheck import specs as specs_module
from speccheck.evidence import claim_problem

MARKER = "covers"
"""The marker's name: `@pytest.mark.covers("SPC-REQ-001-01", "how the test proves it")`."""
RESULTS_VAR = "SPECCHECK_RESULTS"
"""The environment variable that asks for a results file, when `--speccheck-results` isn't given."""
WORKER_KEY = "speccheck"
"""The `workeroutput` key a worker sends its claims under."""
NO_WRITE = (pytest.ExitCode.INTERRUPTED, pytest.ExitCode.INTERNAL_ERROR, pytest.ExitCode.USAGE_ERROR)
"""Exit statuses after which no results file is written: the run didn't finish, so it proves nothing."""

CLAIMS = pytest.StashKey[dict]()
"""The session's claims, by node ID: `{"covers": [{"id", "how"}], "file", "line", "outcome"}`."""
WHERE_TO_PUT_IT = (
    "put the claim on each pytest.param(..., marks=...) of one @pytest.mark.parametrize, each with its own explanation"
)
"""What a misplaced mark's message says to do."""


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
        "markers", f"{MARKER}(id, how): the spec requirement this test proves, and how it proves it"
    )
    claims: dict[str, dict[str, Any]] = {}
    config.stash[CLAIMS] = claims
    workeroutput = getattr(config, "workeroutput", None)
    if workeroutput is not None:
        # xdist sends workeroutput when the worker finishes, so filling this dict in place is enough
        workeroutput[WORKER_KEY] = claims
    config.pluginmanager.register(Recorder(config), f"speccheck-recorder-{id(config)}")


def _argnames(mark: pytest.Mark) -> list[str]:
    """The argument names one `parametrize` mark sets: `"a, b"`, `("a", "b")` or `["a"]`."""
    names = mark.args[0] if mark.args else mark.kwargs.get("argnames", ())
    if isinstance(names, str):
        return [name.strip() for name in names.split(",") if name.strip()]
    return [str(name) for name in names]


def placement_problem(item: pytest.Item) -> str:
    """Why the test's `covers` marks are where a claim can't be, or "" (SPC-REQ-003-02, 003-12).

    A mark must land on exactly one test: a function that isn't parametrized, or one parameter of
    the test's single `parametrize`. Anywhere else, one explanation would stand for several tests.
    """
    callspec = getattr(item, "callspec", None)
    own = [id(mark) for mark in callspec.marks] if callspec is not None else []
    for node, mark in item.iter_markers_with_node(MARKER):
        if isinstance(node, pytest.Module):
            return f"`{MARKER}` is on the module (`pytestmark`); move it onto each test, each with its own explanation"
        if isinstance(node, pytest.Class):
            return f"`{MARKER}` is on class `{node.name}`; move it onto each test, each with its own explanation"
        if callspec is not None and id(mark) not in own:
            return f"`{MARKER}` is on the function of a parametrized test; {WHERE_TO_PUT_IT}"
    if callspec is None:
        return ""
    parametrizes = list(item.iter_markers("parametrize"))
    if len(parametrizes) > 1:
        return f"a claiming test has {len(parametrizes)} `parametrize` marks; {WHERE_TO_PUT_IT}"
    from_fixtures = sorted(set(callspec.params) - {name for mark in parametrizes for name in _argnames(mark)})
    if from_fixtures:
        names = ", ".join(f"`{name}`" for name in from_fixtures)
        return f"a claiming test uses the parametrized fixture {names}; {WHERE_TO_PUT_IT}"
    return ""


def shape_problem(mark: pytest.Mark) -> str:
    """Why one `covers` mark isn't `covers(ID, how)`, or "" (SPC-REQ-003-04)."""
    if mark.kwargs:
        return f"`{MARKER}` takes the ID and how the test proves it, not keywords ({', '.join(sorted(mark.kwargs))})"
    if len(mark.args) != 2:
        return f'`{MARKER}` takes two strings, the ID and how the test proves it, such as covers("T-REQ-001-01", "...")'
    if not all(isinstance(value, str) for value in mark.args):
        return f"`{MARKER}` takes two strings; got {', '.join(repr(value) for value in mark.args)}"
    if not mark.args[0]:
        return f"`{MARKER}` needs an ID"
    return ""


def name_problem(nodeid: str) -> str:
    """Why a claiming test's node ID is refused for its length: say how to shorten it."""
    return (
        f"the test's node ID is {len(nodeid)} characters; the limit is {results.MAX_TEST}. "
        "Shorten the test or class name, or give a long parameter a short id with `ids=`"
    )


def claims_of(item: pytest.Item) -> tuple[list[claims.Claim], list[str]]:
    """The test's claims in mark order, each explanation collapsed, and the problems with them.

    A claim with a problem is left out. Checks only what needs no specs: 003-04, 003-08, 003-10 and 003-16.
    """
    found: list[claims.Claim] = []
    problems: list[str] = []
    for mark in item.iter_markers(MARKER):
        bad = shape_problem(mark)
        if bad:
            problems.append(bad)
            continue
        claimed, how = mark.args[0], claims.collapse(mark.args[1])
        bad = claims.how_problem(claimed, how)
        if bad:
            problems.append(bad)
        elif any(claim.id == claimed for claim in found):
            problems.append(f"the test claims {claimed} more than once; give one explanation, or split the test")
        else:
            found.append(claims.Claim(claimed, how))
    return found, problems


def _where(item: pytest.Item) -> tuple[str, int]:
    """The test's file and 1-based line, from pytest's own location.

    The node ID is written as is, parametrize IDs included, into artifacts CI keeps for weeks.
    Nothing scrubs it, so the README tells projects to keep secrets out of parametrize IDs.
    """
    path, line, _ = item.location
    # pytest gives the OS separator, so a native-Windows run would write `tests\x.py`
    return Path(path).as_posix(), (line + 1 if line is not None else 0)


def _checker(config: pytest.Config):
    """A function giving why the specs don't allow a claim (or ""), or None without `speccheck_config`.

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

    def check(claim: claims.Claim) -> str:
        """Why the specs don't allow this claim (003-03, 003-09), or ""."""
        return claim_problem(claim.id, producer, spec_set) or claims.copied_problem(claim.id, claim.how, spec_set)

    return check


def _function_id(item: pytest.Item) -> str:
    """The test function's node ID without a parameter ID, so a problem with it is reported once."""
    name = getattr(item, "originalname", None) or item.name
    return f"{item.parent.nodeid}::{name}" if item.parent is not None and item.parent.nodeid else item.nodeid


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Record every claiming test, before `-k` or `-m` deselects any, and fail on a claim that isn't allowed.

    Does nothing unless the plugin is configured: `speccheck_config` is set, or the run asks for a
    results file, which can hold only well-formed claims (003-05).
    """
    if not configured(config):
        return
    recorded = config.stash[CLAIMS]
    checker = _checker(config)
    unique = claims.Unique()
    problems: list[str] = []
    for item in items:
        if not any(True for _ in item.iter_markers(MARKER)):
            continue
        path, line = _where(item)
        placed = placement_problem(item)
        if placed:
            problem = f"{path}:{line}: {_function_id(item)}: {placed}"
            if problem not in problems:
                problems.append(problem)
            continue
        if len(item.nodeid) > results.MAX_TEST:
            problems.append(f"{path}:{line}: {item.nodeid}: {name_problem(item.nodeid)}")
            continue
        found, bad = claims_of(item)
        problems += [f"{path}:{line}: {item.nodeid}: {why}" for why in bad]
        for claim in found:
            why = (checker(claim) if checker else "") or unique.add(item.nodeid, claim.id, claim.how)
            if why:
                problems.append(f"{path}:{line}: {item.nodeid}: {why}")
        if found:
            recorded[item.nodeid] = {
                "covers": [claim.to_json() for claim in found],
                "file": path,
                "line": line,
                "outcome": "collected",
            }
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
    if new is None:
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
        self.relayed: dict[str, str] = {}
        """Outcomes merged from the reports of tests this process has no claims for, by node ID: on the
        xdist controller, every test's, relayed from the worker that ran it."""

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
        else:
            self.relayed[report.nodeid] = merge(self.relayed.get(report.nodeid, "collected"), report)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: Any) -> None:
        """On the xdist controller, merge a finished worker's claims: every worker collects every test, one runs it."""
        for nodeid, claim in getattr(node, "workeroutput", {}).get(WORKER_KEY, {}).items():
            current = self.claims.get(nodeid)
            if current is None or RANK.get(current["outcome"], 2) < RANK.get(claim["outcome"], 2):
                self.claims[nodeid] = dict(claim)

    def apply_relayed(self) -> None:
        """Give a claim that no worker ran the outcome the controller saw relayed: its worker crashed (004-06)."""
        for nodeid, outcome in self.relayed.items():
            claim = self.claims.get(nodeid)
            if claim is not None and claim["outcome"] in RANK and outcome not in RANK:
                claim["outcome"] = outcome

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """Write the results file, from the controller only, unless the run was interrupted or never started."""
        if hasattr(self.config, "workerinput") or exitstatus in NO_WRITE:
            return
        path = results_path(self.config)
        if path is None:
            return
        self.apply_relayed()
        results_file = results.ResultsFile(
            producer=os.environ.get(ci.PRODUCER_VAR) or self.config.getini("speccheck_producer") or "local",
            runner=f"pytest {pytest.__version__}",
            ci=ci.context(os.environ),
            # `file` is relative to pytest's root, so say where that is in the repository
            root=ci.results_root(Path(self.config.rootpath), os.environ),
            started=self.started,
            results=[
                results.Result(
                    test=nodeid,
                    covers=[claims.Claim(c["id"], c["how"]) for c in claim["covers"]],
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


def configured(config: pytest.Config) -> bool:
    """Whether the project set `speccheck_config` or the run asked for a results file."""
    return bool(config.getini("speccheck_config")) or results_path(config) is not None


def results_path(config: pytest.Config) -> Path | None:
    """Where to write the results file, or None when nobody asked for one."""
    value = config.getoption("speccheck_results") or os.environ.get(RESULTS_VAR)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path(config.invocation_params.dir) / path
