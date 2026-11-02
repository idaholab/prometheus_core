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

import json
import textwrap

import pytest

from tests.conftest import CONFIG, INDEX, Repo, Run, spec


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
