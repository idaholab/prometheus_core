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

"""`speccheck verify`, through the CLI."""

from __future__ import annotations

from tests.conftest import CONFIG, Repo


def test_verify_names_reported_and_missing_producers(repo: Repo):
    """Problems on stderr, then the summary with who reported and who didn't."""
    repo.write("speccheck.toml", CONFIG + '\n[producers.docker]\nworkflows = ["ci"]\n')
    repo.spec("- T-REQ-001-01: It.")
    repo.results("r/unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = repo.run("verify", "--complete", "--workflow", "ci", "r")
    assert run.code == 1
    assert run.out == ""
    lines = run.err.splitlines()
    assert "producer `docker` didn't report" in lines[0]
    assert lines[-1] == "speccheck verify: 1 requirement: 1 passed; reported: unit; missing: docker; 1 problem"


def test_a_clean_verify_prints_one_line(repo: Repo):
    """On stdout, nothing on stderr; `--verbose` adds every status; `--quiet` prints nothing."""
    repo.spec("- T-REQ-001-01: It.")
    repo.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    run = repo.run("verify", "unit.jsonl")
    assert (run.code, run.err) == (0, "")
    assert run.out == "speccheck verify: 1 requirement: 1 passed; reported: unit\n"
    assert repo.run("verify", "unit.jsonl", "--verbose").out.startswith("T-REQ-001-01  passed\n")
    assert repo.run("--quiet", "verify", "unit.jsonl").out == ""


def test_verify_json(repo: Repo):
    """Every requirement with its status and evidence, and the problems, in one object."""
    repo.spec("- T-REQ-001-01: It.\n- T-REQ-001-02: Other.")
    ci = {"leg": "3.12", "job": "unit", "job_url": "https://github.com/o/r/actions/runs/1/job/2"}
    repo.results("unit.jsonl", "unit", [("tests/t.py::t", ["T-REQ-001-01"], "passed")], ci=ci)
    run = repo.run("verify", "unit.jsonl", "--json")
    body = run.json()
    assert run.code == 1 and run.err == ""
    assert (body["schema_version"], body["command"], body["ok"]) == (1, "verify", False)
    assert body["counts"]["passed"] == 1 and body["counts"]["unclaimed"] == 1
    first = body["requirements"][0]
    assert (first["id"], first["spec"], first["status"], first["text"]) == ("T-REQ-001-01", "001", "passed", "It.")
    assert first["evidence"] == [
        {
            "test": "tests/t.py::t",
            "kind": "test",
            "file": "tests/test_x.py",
            "line": 3,
            "outcome": "passed",
            "producer": "unit",
            "leg": "3.12",
            "job": "unit",
            "url": "https://github.com/o/r/actions/runs/1/job/2",
        }
    ]
    assert body["problems"][0]["message"].startswith("T-REQ-001-02 is not claimed")
    assert body["producers"] == {"reported": ["unit"], "missing": []}


def test_a_bad_results_file_is_a_problem_at_its_path(repo: Repo):
    """A broken file is reported where it is, relative to where speccheck runs."""
    repo.spec("- T-REQ-001-01: It. ⚠ untested")
    repo.write("r/bad.jsonl", '{"schema": "speccheck-results/9", "producer": "unit"}\n')
    run = repo.run("verify", "r", "missing.jsonl")
    assert run.code == 1
    assert "r/bad.jsonl:1: not a valid speccheck-results/1 line" in run.err
    assert "missing.jsonl: no such results file or folder" in run.err


def test_absolute_inputs(repo: Repo):
    """An absolute path works too; a path outside the folder is printed as given."""
    repo.spec("- T-REQ-001-01: It.")
    path = repo.results("unit.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    assert repo.run("verify", str(path)).code == 0
