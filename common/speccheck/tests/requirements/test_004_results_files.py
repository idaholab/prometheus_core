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

"""specs/004-results-files.md: the files a real pytest run writes, and what speccheck accepts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import speccheck
from tests.requirements.conftest import Project

OUTCOMES = """\
import pytest

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")

@pytest.fixture
def broken_setup():
    raise RuntimeError("setup")

@pytest.mark.covers("T-REQ-001-01")
def test_passes():
    pass

@pytest.mark.covers("T-REQ-001-01")
def test_fails():
    assert False

@pytest.mark.covers("T-REQ-001-01")
def test_skipped():
    pytest.skip("no")

@pytest.mark.covers("T-REQ-001-01")
@pytest.mark.skipif(True, reason="never")
def test_skipped_in_setup():
    pass

@pytest.mark.covers("T-REQ-001-01")
@pytest.mark.xfail(reason="known")
def test_xfailed():
    assert False

@pytest.mark.covers("T-REQ-001-01")
@pytest.mark.xfail(reason="known")
def test_xpassed():
    pass

@pytest.mark.covers("T-REQ-001-01")
def test_setup_errors(broken_setup):
    pass

@pytest.mark.covers("T-REQ-001-01")
def test_teardown_errors(broken_teardown):
    pass

@pytest.mark.covers("T-REQ-001-01")
def test_deselected():
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
}
"""The outcome each claiming test must be written with."""

SCHEMA = Path(speccheck.__file__).parent / "schema" / "speccheck-results-1.schema.json"
"""The JSON Schema shipped with the package."""


def outcomes(project: Project, name: str) -> dict[str, str]:
    """Test name -> outcome, from a results file the run wrote."""
    return {line["test"].split("::", 1)[1]: line["outcome"] for line in project.results_lines(name)[1:]}


@pytest.mark.covers("SPC-REQ-004-01")
def test_a_run_writes_json_lines_with_a_versioned_header(project: Project):
    """A header, then one line per claiming test, each matching the shipped schema's shape."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n')
    project.pytest("--speccheck-results=r.jsonl")
    header, result = project.results_lines("r.jsonl")
    schema = json.loads(SCHEMA.read_text())
    assert header["schema"] == schema["$defs"]["header"]["properties"]["schema"]["const"] == "speccheck-results/1"
    assert header["runner"].startswith("pytest ") and header["producer"] == "local"
    assert set(header) <= set(schema["$defs"]["header"]["properties"])
    assert set(result) <= set(schema["$defs"]["result"]["properties"])
    assert set(schema["$defs"]["result"]["required"]) <= set(result)
    assert result == {
        "test": "test_project.py::test_a",
        "file": "test_project.py",
        "line": 2,  # pytest's location of a decorated test: its first decorator, here the claim itself
        "covers": ["T-REQ-001-01"],
        "outcome": "passed",
    }


@pytest.mark.covers("SPC-REQ-004-02")
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "speccheck-results/2"}, "this speccheck reads only 'speccheck-results/1'"),
        ({"extra": 1}, "unknown header key `extra`"),
        ({"producer": 3}, "`producer` must be a string"),
    ],
)
def test_a_bad_header_rejects_the_whole_file(project: Project, change: dict, message: str):
    """Its passing results don't count: the requirement stays unproven."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", **change}
    line = {"test": "t", "covers": ["T-REQ-001-01"], "outcome": "passed"}
    project.write("r.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    run = project.speccheck("verify", "r.jsonl", "--json")
    assert run.code == 1
    assert any(message in p["message"] and p["path"] == "r.jsonl" for p in run.json()["problems"])
    assert run.json()["requirements"][0]["status"] != "passed"


@pytest.mark.covers("SPC-REQ-004-02")
@pytest.mark.parametrize(
    ("line", "message"),
    [
        ({"test": "t", "covers": ["T-REQ-001-01"], "outcome": "ok"}, "`outcome` is 'ok'"),
        ({"test": "t", "covers": ["T-REQ-001-01"], "outcome": "passed", "x": 1}, "unknown result key `x`"),
        ({"test": "t", "covers": "T-REQ-001-01", "outcome": "passed"}, "`covers` must be a list"),
    ],
)
def test_a_bad_result_line_rejects_the_whole_file(project: Project, line: dict, message: str):
    """One bad line, even after a good one, and nothing in the file counts."""
    project.spec("- T-REQ-001-01: One.")
    good = {"test": "good", "covers": ["T-REQ-001-01"], "outcome": "passed"}
    header = {"schema": "speccheck-results/1", "producer": "unit"}
    project.write("r.jsonl", "\n".join(json.dumps(x) for x in (header, good, line)) + "\n")
    run = project.speccheck("verify", "r.jsonl")
    assert run.code == 1
    assert f"r.jsonl:3: not a valid speccheck-results/1 line: {message}" in run.err


@pytest.mark.covers("SPC-REQ-004-03", "SPC-REQ-004-04")
def test_every_outcome_and_deselected_tests_are_written(project: Project):
    """Setup, call and teardown merged into one outcome; skipped and deselected claims are written; unclaimed tests aren't."""
    project.tests(OUTCOMES)
    project.pytest("--speccheck-results=r.jsonl", "-k", "not test_deselected and not claims_nothing")
    assert outcomes(project, "r.jsonl") == EXPECTED


@pytest.mark.covers("SPC-REQ-004-04")
def test_collect_only_writes_collected(project: Project):
    """Nothing runs, so every claim is `collected`."""
    project.tests(OUTCOMES)
    project.pytest("--collect-only", "-q", "--speccheck-results=c.jsonl")
    assert set(outcomes(project, "c.jsonl").values()) == {"collected"}
    assert len(outcomes(project, "c.jsonl")) == len(EXPECTED)


@pytest.mark.covers("SPC-REQ-004-05")
def test_a_file_only_when_asked(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Nothing by default; the option or SPECCHECK_RESULTS (relative to where pytest started) asks for one."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n')
    project.pytest()
    assert not list(project.root.rglob("*.jsonl"))
    monkeypatch.setenv("SPECCHECK_RESULTS", "out/env.jsonl")
    project.pytest()
    assert (project.root / "out" / "env.jsonl").is_file()


@pytest.mark.covers("SPC-REQ-004-05")
def test_an_interrupted_session_leaves_no_file(project: Project):
    """A KeyboardInterrupt mid-run (in a separate process, as a real one would be) writes nothing."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    raise KeyboardInterrupt\n')
    run = project.pytest("--speccheck-results=r.jsonl", subprocess=True)
    assert run.ret == pytest.ExitCode.INTERRUPTED
    assert not (project.root / "r.jsonl").exists()
    assert not [p for p in project.root.iterdir() if p.name.startswith(".r.jsonl")]


@pytest.mark.covers("SPC-REQ-004-06")
def test_xdist_writes_one_file_with_every_workers_results(project: Project):
    """Two workers: one file, written by the controller, with each test's real outcome."""
    project.tests(OUTCOMES)
    project.pytest(
        "-p",
        "xdist",
        "-n",
        "2",
        "--speccheck-results=x.jsonl",
        "-k",
        "not test_deselected and not claims_nothing",
        subprocess=True,
    )
    assert outcomes(project, "x.jsonl") == EXPECTED
    assert [p.name for p in project.root.glob("*.jsonl")] == ["x.jsonl"]


@pytest.mark.covers("SPC-REQ-004-07")
def test_limits_and_symlinks(project: Project, tmp_path_factory: pytest.TempPathFactory):
    """An over-long line is refused, and a symlink in a results folder is not followed."""
    project.spec("- T-REQ-001-01: One.")
    header = json.dumps({"schema": "speccheck-results/1", "producer": "unit"})
    project.write(
        "r/long.jsonl",
        header + "\n" + json.dumps({"test": "x" * 70_000, "covers": ["T-REQ-001-01"], "outcome": "passed"}) + "\n",
    )
    outside = tmp_path_factory.mktemp("outside")
    (outside / "good.jsonl").write_text(
        header + "\n" + json.dumps({"test": "t", "covers": ["T-REQ-001-01"], "outcome": "passed"}) + "\n"
    )
    (project.root / "r" / "link.jsonl").symlink_to(outside / "good.jsonl")
    (project.root / "r" / "dir").symlink_to(outside, target_is_directory=True)
    run = project.speccheck("verify", "r", "--json")
    assert any(
        "r/long.jsonl:2: line longer than 65536 bytes" == f"{p['path']}:{p['line']}: {p['message']}"
        for p in run.json()["problems"]
    )
    assert run.json()["producers"]["reported"] == []
    assert run.json()["requirements"][0]["status"] == "not run"


@pytest.mark.covers("SPC-REQ-004-08")
def test_the_ci_context(project: Project, monkeypatch: pytest.MonkeyPatch):
    """In GitHub Actions the header says where the run was; outside it, `ci` is null."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n')
    project.pytest("--speccheck-results=local.jsonl")
    assert project.results_lines("local.jsonl")[0]["ci"] is None
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_WORKFLOW": "test",
        "GITHUB_JOB": "unit",
        "GITHUB_RUN_ID": "9",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": "c" * 40,
        "SPECCHECK_LEG": "3.12",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    project.pytest("--speccheck-results=ci.jsonl")
    ci = project.results_lines("ci.jsonl")[0]["ci"]
    assert (ci["server"], ci["repository"], ci["workflow"], ci["job"], ci["leg"]) == (
        "https://github.com",
        "o/r",
        "test",
        "unit",
        "3.12",
    )
    assert (ci["run_id"], ci["run_attempt"], ci["sha"]) == (9, 2, "c" * 40)
