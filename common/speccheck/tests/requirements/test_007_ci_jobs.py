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

"""specs/007-ci-jobs.md: `record` in a fake CI job, and links in what a real run writes.

SPC-REQ-007-03 to 007-05 (the composite actions, end to end) are proven by the
`speccheck-self-check` job in speccheck.yml, which claims them in speccheck.toml, not here.
"""

from __future__ import annotations

import pytest

from tests.requirements.conftest import CONFIG, Project

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


@pytest.fixture
def ci_project(project: Project) -> Project:
    """A project whose `publish` CI job claims T-REQ-001-01."""
    project.write("speccheck.toml", CONFIG + '[ci.publish]\ncovers = ["T-REQ-001-01"]\nworkflows = ["ci"]\n')
    project.spec("- T-REQ-001-01: It publishes.\n- T-REQ-001-02: It is tested. ⚠ untested")
    return project


@pytest.mark.covers("SPC-REQ-007-01")
def test_record_writes_a_passed_ci_result_per_id(ci_project: Project):
    """In the job, record writes the file, and verify counts the requirement as proven by the job."""
    run = ci_project.speccheck("record", env=JOB)
    assert (run.code, run.out) == (0, "speccheck record: publish recorded T-REQ-001-01 in .speccheck/publish.jsonl\n")
    header, result = ci_project.results_lines(".speccheck/publish.jsonl")
    assert header["producer"] == "publish"
    assert result == {"test": "publish", "covers": ["T-REQ-001-01"], "outcome": "passed", "kind": "ci"}
    evidence = ci_project.speccheck("verify", ".speccheck", "--json").json()["requirements"][0]
    assert evidence["status"] == "passed" and evidence["evidence"][0]["kind"] == "ci"


@pytest.mark.covers("SPC-REQ-007-01")
def test_record_without_an_entry_is_exit_2(ci_project: Project):
    """A job the config doesn't list, or no job at all, writes nothing."""
    run = ci_project.speccheck("record", env={**JOB, "GITHUB_JOB": "build"})
    assert run.code == 2 and "no [ci.build] entry for this job (CI jobs: publish)" in run.err
    assert ci_project.speccheck("record").code == 2
    assert not (ci_project.root / ".speccheck").exists()


@pytest.mark.covers("SPC-REQ-007-02")
def test_a_ci_job_counts_only_for_its_own_ids(ci_project: Project):
    """A results file from the job that claims more than its entry lists: the extra claim is a problem."""
    ci_project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01", "T-REQ-001-02"], "passed")], kind="ci")
    run = ci_project.speccheck("verify", "p.jsonl", "--json")
    statuses = {r["id"]: r["status"] for r in run.json()["requirements"]}
    assert statuses == {"T-REQ-001-01": "passed", "T-REQ-001-02": "untested"}
    assert "T-REQ-001-02 isn't in `ci.publish.covers`, so job `publish` may not record it" in [
        p["message"] for p in run.json()["problems"]
    ]


@pytest.mark.covers("SPC-REQ-007-06")
def test_links_point_at_the_attempt_and_the_job(ci_project: Project, monkeypatch: pytest.MonkeyPatch):
    """A test run on attempt 3 links that attempt, and its job by check run ID; without one, the attempt."""
    for name, value in {**JOB, "GITHUB_JOB": "unit"}.items():
        monkeypatch.setenv(name, value)
    ci_project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n')
    ci_project.pytest("--speccheck-results=with-id.jsonl")
    ci = ci_project.results_lines("with-id.jsonl")[0]["ci"]
    assert ci["run_url"] == "https://github.com/o/r/actions/runs/11/attempts/3"
    assert ci["job_url"] == "https://github.com/o/r/actions/runs/11/job/22"
    monkeypatch.delenv("SPECCHECK_JOB_ID")
    ci_project.pytest("--speccheck-results=no-id.jsonl")
    assert ci_project.results_lines("no-id.jsonl")[0]["ci"]["job_url"] == ci["run_url"]
