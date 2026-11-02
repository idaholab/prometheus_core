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
from tests.conftest import CONFIG, INDEX, spec


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
        """Write a results file of `(test, covers, outcome)` claims."""
        results_file = results.ResultsFile(
            producer=producer,
            runner="test",
            ci=header.get("ci"),
            results=[
                results.Result(
                    test=t, covers=c, outcome=o, file="tests/test_x.py", line=3, kind=header.get("kind", "test")
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


@pytest.fixture
def project(pytester: pytest.Pytester) -> Project:
    """A fresh project."""
    return Project(pytester)


__all__ = ["CONFIG", "INDEX", "Project", "spec"]
