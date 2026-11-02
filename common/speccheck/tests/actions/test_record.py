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

"""`speccheck record`, with a fake CI environment, and what verify makes of its file."""

from __future__ import annotations

import pytest

from speccheck import results
from tests.conftest import CONFIG, Repo

FAKE_CI = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "o/r",
    "GITHUB_WORKFLOW": "ci",
    "GITHUB_JOB": "publish",
    "GITHUB_RUN_ID": "11",
    "GITHUB_RUN_ATTEMPT": "1",
    "SPECCHECK_JOB_ID": "22",
}
"""A fake GitHub Actions job named `publish`."""


@pytest.fixture
def ci_repo(repo: Repo) -> Repo:
    """A repo whose config has a `[ci.publish]` job claiming one requirement."""
    repo.write("speccheck.toml", CONFIG + '\n[ci.publish]\ncovers = ["T-REQ-001-01"]\nworkflows = ["ci"]\n')
    repo.spec("- T-REQ-001-01: Published.\n- T-REQ-001-02: Tested. ⚠ untested")
    return repo


@pytest.mark.covers("SPC-REQ-007-01")
class TestRecord:
    """Writing a CI job's results."""

    def test_record_in_a_fake_ci_job(self, ci_repo: Repo):
        """One passed `ci` result per ID, with the job link; verify counts it."""
        run = ci_repo.run("record", env=FAKE_CI)
        assert run.code == 0, run.err
        assert run.out == "speccheck record: publish recorded T-REQ-001-01 in .speccheck/publish.jsonl\n"
        parsed, problems = results.read(ci_repo.root / ".speccheck" / "publish.jsonl")
        assert problems == []
        assert parsed.producer == "publish" and parsed.runner.startswith("speccheck record ")
        assert parsed.ci["job_url"] == "https://github.com/o/r/actions/runs/11/job/22"
        assert [r.to_json() for r in parsed.results] == [
            {"test": "publish", "covers": ["T-REQ-001-01"], "outcome": "passed", "kind": "ci"}
        ]
        verify = ci_repo.run("verify", ".speccheck", "--json")
        assert verify.json()["requirements"][0]["status"] == "passed"

    def test_job_and_output_options(self, ci_repo: Repo):
        """`--job` and `--output` win over the environment; SPECCHECK_RESULTS over the default."""
        assert ci_repo.run("record", "--job", "publish", "--output", "a.jsonl").code == 0
        assert (ci_repo.root / "a.jsonl").is_file()
        assert ci_repo.run("record", env={**FAKE_CI, "SPECCHECK_RESULTS": "b.jsonl"}).code == 0
        assert (ci_repo.root / "b.jsonl").is_file()

    def test_json(self, ci_repo: Repo):
        """The job, its IDs and the file written."""
        body = ci_repo.run("record", "--json", env=FAKE_CI).json()
        assert (body["job"], body["covers"]) == ("publish", ["T-REQ-001-01"])
        assert body["path"].endswith("publish.jsonl")

    @pytest.mark.parametrize(
        ("argv", "env", "message"),
        [
            (["record"], {}, "no job name: pass --job NAME"),
            (["record", "--job", "unit"], {}, "no [ci.unit] entry for this job (CI jobs: publish)"),
            (["record", "--job", "other"], {}, "no [ci.other] entry"),
        ],
    )
    def test_no_entry_is_exit_2(self, ci_repo: Repo, argv, env, message):
        """A job without a `[ci.<job>]` entry, or a test producer, can't record."""
        run = ci_repo.run(*argv, env=env)
        assert run.code == 2 and message in run.err

    def test_no_ci_jobs_at_all(self, repo: Repo):
        """The message says there are none."""
        assert "(CI jobs: none)" in repo.run("record", "--job", "x").err
