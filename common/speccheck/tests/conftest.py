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

"""What every test shares, and the rule that keeps the kinds of test apart.

- `tests/unit/` tests one module at a time, mirrors `speccheck/`, and is the only suite run under
  coverage. Its tests build their inputs in memory, call the module directly, and claim nothing.
- `tests/requirements/` proves speccheck's own specs (`specs/`), one file per spec, through what a
  user sees: the command line, a real pytest run, the files written. Every test there claims the
  requirements it proves with `covers`, and none of it counts toward coverage.
- `tests/rules/` checks the code base itself (docstrings, headers, the test layout). It claims
  nothing and isn't measured.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

SPECCHECK_VARS = ("SPECCHECK_RESULTS", "SPECCHECK_PRODUCER", "SPECCHECK_LEG", "SPECCHECK_JOB_ID", "SPECCHECK_ROOT")
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

CI_ENV = {"GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""A GitHub Actions run of repository `o/r`: the least a report or summary needs to link anything.

Links are written only inside CI (SPC-REQ-007-10), which is `GITHUB_ACTIONS=true` and a safe server and
repository, so a test that expects a link starts from this and adds what else it needs."""

INDEX = "# Index\n\n- [001](001-thing.md)\n"
"""An index that links the one spec most tests write."""


def spec(body: str, *, status: str = "draft", number: str = "001", title: str = "Thing") -> str:
    """A spec file with the header filled in and `body` as its Requirements section."""
    return f"# {number} - {title}\n\nstatus: {status}\n\n## Requirements\n\n{textwrap.dedent(body).strip()}\n"


TESTS = Path(__file__).resolve().parent
"""The tests folder."""


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Fail collection on a unit or rules test that claims a requirement, or a requirements test that claims none."""
    problems = []
    for item in items:
        path = Path(str(item.path)).resolve()
        if TESTS not in path.parents:
            continue  # a pytester inner run's tests
        part = path.relative_to(TESTS).parts[0]
        claims = item.get_closest_marker("covers") is not None
        if part in ("unit", "rules") and claims:
            problems.append(f"{item.nodeid}: a {part} test claims nothing; prove requirements in tests/requirements/")
        elif part == "requirements" and not claims:
            problems.append(f"{item.nodeid}: a requirements test claims what it proves with @pytest.mark.covers(...)")
    if problems:
        raise pytest.UsageError("\n".join(problems))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts outside CI, with no speccheck variables, whatever the outer run has."""
    for name in SPECCHECK_VARS + GITHUB_VARS:
        monkeypatch.delenv(name, raising=False)
