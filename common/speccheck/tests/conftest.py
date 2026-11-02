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

"""Fixtures shared by every test, and the rule that keeps the two kinds of test apart.

- `tests/unit/` tests one module at a time, mirrors `speccheck/`, and is the only suite run under
  coverage. Its tests claim nothing.
- `tests/requirements/` proves speccheck's own specs (`specs/`), one file per spec, through what a
  user sees: the command line, a real pytest run, the files written. Every test there claims the
  requirements it proves with `covers`, and none of it counts toward coverage.
"""

from __future__ import annotations

import io
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from speccheck import cli, results

SPECCHECK_VARS = ("SPECCHECK_RESULTS", "SPECCHECK_PRODUCER", "SPECCHECK_LEG", "SPECCHECK_JOB_ID")
"""The variables the CI job sets for the outer run, which must not leak into a test's inner runs."""
GITHUB_VARS = (
    "GITHUB_ACTIONS",
    "GITHUB_SERVER_URL",
    "GITHUB_REPOSITORY",
    "GITHUB_WORKFLOW",
    "GITHUB_JOB",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_SHA",
    "GITHUB_REF",
    "GITHUB_EVENT_NAME",
)
"""GitHub's variables, cleared so a test sees only the CI context it sets itself."""

CONFIG = """\
specs = "specs"
id-prefix = "T"

[producers.unit]
specs = "all"
workflows = ["ci"]
"""
"""The config most tests start from: prefix `T`, one producer `unit` that may claim everything."""

INDEX = "# Index\n\n- [001](001-thing.md)\n"
"""An index that links the one spec most tests write."""


def spec(body: str, *, status: str = "draft", number: str = "001", title: str = "Thing") -> str:
    """A spec file with the header filled in and `body` as its Requirements section."""
    return f"# {number} - {title}\n\nstatus: {status}\n\n## Requirements\n\n{textwrap.dedent(body).strip()}\n"


TESTS = Path(__file__).resolve().parent
"""The tests folder."""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Fail collection on a unit test that claims a requirement, or a requirements test that claims none."""
    problems = []
    for item in items:
        path = Path(str(item.path)).resolve()
        if TESTS not in path.parents:
            continue  # a pytester inner run's tests
        part = path.relative_to(TESTS).parts[0]
        claims = item.get_closest_marker("covers") is not None
        if part == "unit" and claims:
            problems.append(f"{item.nodeid}: a unit test claims nothing; prove requirements in tests/requirements/")
        elif part == "requirements" and not claims:
            problems.append(f"{item.nodeid}: a requirements test claims what it proves with @pytest.mark.covers(...)")
    if problems:
        raise pytest.UsageError("\n".join(problems))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts outside CI, with no speccheck variables, whatever the outer run has."""
    for name in SPECCHECK_VARS + GITHUB_VARS:
        monkeypatch.delenv(name, raising=False)


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


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A fresh spec folder and config."""
    return Repo(tmp_path)
