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

"""`speccheck check`, through the CLI, on a real collect-only run."""

from __future__ import annotations

import pytest

from tests.conftest import Repo


@pytest.mark.covers("SPC-REQ-005-08")
def test_check_on_a_collect_only_run(repo: Repo, pytester: pytest.Pytester):
    """The local workflow from the README: collect, then check."""
    repo.root = pytester.path
    repo.__init__(pytester.path)
    repo.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    pytester.makeini("[pytest]\nspeccheck_producer = unit\n")
    pytester.makepyfile(test_a='import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    assert False\n')
    pytester.runpytest("--collect-only", "-q", "--speccheck-results=.speccheck/collect.jsonl")
    run = repo.run("check", ".speccheck/")
    assert run.code == 1
    assert run.err.splitlines() == [
        'specs/001-thing.md:8: T-REQ-001-02 is not claimed; add `@pytest.mark.covers("T-REQ-001-02")` to a test '
        "that proves it, or mark it `⚠ untested` in the spec",
        "speccheck check: 2 requirements: 1 unclaimed, 1 claimed; reported: unit; 1 problem",
    ]


@pytest.mark.covers("SPC-REQ-008-03")
def test_check_with_no_problems_exits_0(repo: Repo):
    """Exit code 0, with a summary line."""
    repo.spec("- T-REQ-001-01: One. ⚠ untested")
    run = repo.run("check")
    assert (run.code, run.out) == (0, "speccheck check: 1 requirement: 1 untested\n")
