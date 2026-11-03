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

"""What the requirements tests share: a project a user would have, run the way a user runs it.

A `Project` is a folder with `speccheck.toml`, a spec folder and test files. Its `pytest` runs a
real inner pytest session there, through `pytester`, and its `speccheck` runs the command line
there, so every assertion is about something a user sees: exit codes, printed lines, the JSON
object, the files written.
"""

from __future__ import annotations

import io
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from speccheck import cli, results
from speccheck.claims import Claim
from tests.conftest import CONFIG, INDEX, spec

OUTCOMES = """\
import pytest

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")

@pytest.fixture
def broken_setup():
    raise RuntimeError("setup")

@pytest.fixture
def skips_in_teardown():
    yield
    pytest.skip("teardown")

@pytest.mark.covers("T-REQ-001-01", "inner claim 1 of T-REQ-001-01")
def test_passes():
    pass

@pytest.mark.covers("T-REQ-001-01", "inner claim 2 of T-REQ-001-01")
def test_fails():
    assert False

@pytest.mark.covers("T-REQ-001-01", "inner claim 3 of T-REQ-001-01")
def test_skipped():
    pytest.skip("no")

@pytest.mark.covers("T-REQ-001-01", "inner claim 4 of T-REQ-001-01")
@pytest.mark.skipif(True, reason="never")
def test_skipped_in_setup():
    pass

@pytest.mark.covers("T-REQ-001-01", "inner claim 5 of T-REQ-001-01")
@pytest.mark.xfail(reason="known")
def test_xfailed():
    assert False

@pytest.mark.covers("T-REQ-001-01", "inner claim 6 of T-REQ-001-01")
@pytest.mark.xfail(reason="known")
def test_xpassed():
    pass

@pytest.mark.covers("T-REQ-001-01", "inner claim 7 of T-REQ-001-01")
def test_setup_errors(broken_setup):
    pass

@pytest.mark.covers("T-REQ-001-01", "inner claim 8 of T-REQ-001-01")
def test_teardown_errors(broken_teardown):
    pass

@pytest.mark.covers("T-REQ-001-01", "inner claim 9 of T-REQ-001-01")
def test_deselected():
    pass

@pytest.mark.covers("T-REQ-001-01", "inner claim 18 of T-REQ-001-01")
def test_teardown_skip_keeps_the_call(skips_in_teardown):
    pass

def test_claims_nothing():
    pass
"""
"""A project test file with one claiming test of every outcome."""

EXPECTED = {
    "test_passes": "passed",
    "test_fails": "failed",
    "test_skipped": "skipped",
    "test_skipped_in_setup": "skipped",
    "test_xfailed": "xfailed",
    "test_xpassed": "xpassed",
    "test_setup_errors": "error",
    "test_teardown_errors": "error",
    "test_deselected": "deselected",
    "test_teardown_skip_keeps_the_call": "passed",
}
"""The outcome each claiming test must be written with."""

CI = {
    "job": "unit",
    "job_id": 8,
    "sha": "d" * 40,
    "run_url": "https://github.com/o/r/actions/runs/7/attempts/2",
    "job_url": "https://github.com/o/r/actions/runs/7/job/8",
}
"""A results file's CI block, from a re-run with a job ID."""
ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""The run `report` is in: links must be under its server and repository."""


JOB = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "o/r",
    "GITHUB_WORKFLOW": "ci",
    "GITHUB_JOB": "publish",
    "GITHUB_RUN_ID": "11",
    "GITHUB_RUN_ATTEMPT": "3",
    "SPECCHECK_JOB_ID": "22",
}
"""A fake GitHub Actions job named `publish`, on its third attempt."""


@dataclass
class Run:
    """One CLI run's exit code and output."""

    code: int
    """The exit code."""
    out: str
    """stdout."""
    err: str
    """stderr."""

    def json(self) -> dict:
        """stdout parsed as the one JSON object."""
        return json.loads(self.out)


class Repo:
    """A throwaway folder with `speccheck.toml`, `specs/000-index.md`, and helpers to write and run."""

    def __init__(self, root: Path) -> None:
        """Write the default config and index under `root`."""
        self.root = root
        """The folder speccheck runs in."""
        self.write("speccheck.toml", CONFIG)
        self.write("specs/000-index.md", INDEX)

    def write(self, name: str, text: str) -> Path:
        """Write a file under the root and return its path."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def spec(self, body: str, **kwargs) -> Path:
        """Write spec 001 (or `number=`) with `body` as its requirements."""
        number = kwargs.get("number", "001")
        name = kwargs.pop("name", f"{number}-thing.md")
        return self.write(f"specs/{name}", spec(body, **kwargs))

    def results(self, name: str, producer: str, claims: list[tuple[str, list[str], str]], **header) -> Path:
        """Write a results file of `(test, covers, outcome)` claims; each ID's how names its test and ID."""
        results_file = results.ResultsFile(
            producer=producer,
            runner="test",
            ci=header.get("ci"),
            results=[
                results.Result(
                    test=t,
                    # One line and well under the limit, whatever the test name holds
                    covers=[Claim(id_, f"{' '.join(t.split())[:200]} proves {id_}") for id_ in c],
                    outcome=o,
                    file="tests/test_x.py",
                    line=3,
                    kind=header.get("kind", "test"),
                )
                for t, c, o in claims
            ],
        )
        path = self.root / name
        results.write(path, results_file)
        return path

    def run(self, *argv: str, env: dict[str, str] | None = None) -> Run:
        """Run the CLI here and return its exit code and output."""
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), env=env or {}, cwd=self.root, out=out, err=err)
        return Run(code, out.getvalue(), err.getvalue())


class Project(Repo):
    """A project with a config, a spec folder, and an inner pytest to run its tests."""

    def __init__(self, pytester: pytest.Pytester) -> None:
        """A project in pytester's folder, with the default config, index and pytest settings."""
        super().__init__(pytester.path)
        self.pytester = pytester
        """Runs the inner pytest sessions."""
        self.ini("")

    def ini(self, options: str, addopts: str = "") -> None:
        """The project's pytest settings: no cache plus `addopts`, and any other ini options."""
        self.write("pytest.ini", f"[pytest]\naddopts = -p no:cacheprovider {addopts}\n{options}")

    def tests(self, source: str, name: str = "test_project.py") -> None:
        """Write a test file."""
        self.write(name, textwrap.dedent(source))

    def pytest(self, *args: str, subprocess: bool = False) -> pytest.RunResult:
        """Run the project's tests: in this process, or (`subprocess`) as a separate `python -m pytest`."""
        if subprocess:
            return self.pytester.runpytest_subprocess(*args)
        return self.pytester.runpytest(*args)

    def speccheck(self, *argv: str, env: dict[str, str] | None = None) -> Run:
        """Run the speccheck command line in the project."""
        return self.run(*argv, env=env)

    def results_lines(self, name: str) -> list[dict]:
        """A results file, one parsed JSON object per line."""
        return [json.loads(line) for line in (self.root / name).read_text().splitlines()]


def outcomes(project: Project, name: str) -> dict[str, str]:
    """Test name -> outcome, from a results file the run wrote."""
    return {line["test"].split("::", 1)[1]: line["outcome"] for line in project.results_lines(name)[1:]}


@pytest.fixture
def reported(project: Project) -> Project:
    """A project with one passing, one failing and one unclaimed requirement, a Purpose, and a results file."""
    project.write(
        "specs/001-thing.md",
        spec(
            "- T-REQ-001-01: Passes.\n- T-REQ-001-02: Fails.\n- T-REQ-001-03: Nobody claims it.", title="The thing"
        ).replace("## Requirements", "## Purpose\n\nWhat the thing\npromises.\n\n## Requirements"),
    )
    project.results(
        "unit.jsonl",
        "unit",
        [("tests/t.py::test_ok", ["T-REQ-001-01"], "passed"), ("tests/t.py::test_bad", ["T-REQ-001-02"], "failed")],
        ci=CI,
    )
    return project


@pytest.fixture
def ci_project(project: Project) -> Project:
    """A project whose `publish` CI job claims T-REQ-001-01."""
    project.write(
        "speccheck.toml",
        CONFIG
        + '[ci.publish]\nworkflows = ["ci"]\n[ci.publish.covers]\n"T-REQ-001-01" = "the publish job pushes the image"\n',
    )
    project.spec("- T-REQ-001-01: It publishes.\n- T-REQ-001-02: It is tested. ⚠ untested")
    return project


@pytest.fixture
def project(pytester: pytest.Pytester) -> Project:
    """A fresh project."""
    return Project(pytester)


__all__ = ["CI", "CONFIG", "JOB", "ENV", "EXPECTED", "INDEX", "OUTCOMES", "Project", "outcomes", "spec"]
