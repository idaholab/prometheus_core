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

"""`speccheck lint`, through the CLI."""

from __future__ import annotations

from tests.conftest import Repo


def test_lint_text(repo: Repo):
    """0 and one line when clean; 1 and the problems on stderr otherwise."""
    repo.spec("- T-REQ-001-01: One.")
    assert repo.run("lint").out == "speccheck lint: 1 specs, 1 requirement\n"
    repo.spec("- T-REQ-1-1: One.")
    run = repo.run("lint")
    assert run.code == 1
    assert run.err.splitlines()[-1] == "speccheck lint: 1 specs, 0 requirements; 1 problem"


def test_lint_json(repo: Repo):
    """The specs and the problems, with control characters escaped by JSON."""
    repo.spec("- T-REQ-001-01: One.", status="implemented", title="Thing\x1b")
    repo.write("specs/Bad\n::error::x.md", "")
    run = repo.run("lint", "--json")
    body = run.json()
    assert run.code == 1 and run.err == ""
    assert body["specs"] == [{"number": "001", "title": "Thing\x1b", "status": "implemented", "requirements": 1}]
    assert "\\u001b" in run.out and "\n::error::" not in run.out
    assert body["problems"][0]["path"] == "specs/Bad\n::error::x.md"
