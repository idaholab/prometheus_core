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

SPC-REQ-007-03, 007-04 and 007-06 (the composite actions, end to end) are proven by the
`speccheck-self-check` job in speccheck.yml, which claims them in speccheck.toml, not here.
"""

from __future__ import annotations

import pytest

from tests.requirements.conftest import CI, ENV, JOB, Project


@pytest.mark.covers(
    "SPC-REQ-007-01",
    "record in job publish writes a passed ci result for its ID, and verify counts the requirement as passed by that job",
)
def test_record_writes_a_passed_ci_result_per_id(ci_project: Project):
    """In the job, record writes the file, and verify counts the requirement as proven by the job."""
    run = ci_project.speccheck("record", env=JOB)
    assert (run.code, run.out) == (0, "speccheck record: publish recorded T-REQ-001-01 in .speccheck/publish.jsonl\n")
    header, result = ci_project.results_lines(".speccheck/publish.jsonl")
    assert header["producer"] == "publish"
    claim = {"id": "T-REQ-001-01", "how": "the publish job pushes the image"}
    assert result == {"test": "publish", "covers": [claim], "outcome": "passed", "kind": "ci"}
    evidence = ci_project.speccheck("verify", ".speccheck", "--json").json()["requirements"][0]
    assert evidence["status"] == "passed" and evidence["evidence"][0]["kind"] == "ci"
    assert evidence["evidence"][0]["how"] == "the publish job pushes the image"


@pytest.mark.covers(
    "SPC-REQ-007-01",
    "record in job build, which has no entry, and record outside any job both exit 2 and write nothing",
)
def test_record_without_an_entry_is_exit_2(ci_project: Project):
    """A job the config doesn't list, or no job at all, writes nothing."""
    run = ci_project.speccheck("record", env={**JOB, "GITHUB_JOB": "build"})
    assert run.code == 2 and "no [ci.build] entry for this job (CI jobs: publish)" in run.err
    assert ci_project.speccheck("record").code == 2
    assert not (ci_project.root / ".speccheck").exists()


@pytest.mark.covers(
    "SPC-REQ-007-02",
    "a publish results file also claiming T-REQ-001-02 counts only T-REQ-001-01, and the extra claim is a problem",
)
def test_a_ci_job_counts_only_for_its_own_ids(ci_project: Project):
    """A results file from the job that claims more than its entry lists: the extra claim is a problem."""
    ci_project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01", "T-REQ-001-02"], "passed")], kind="ci")
    run = ci_project.speccheck("verify", "p.jsonl", "--json")
    statuses = {r["id"]: r["status"] for r in run.json()["requirements"]}
    assert statuses == {"T-REQ-001-01": "passed", "T-REQ-001-02": "untested"}
    assert "T-REQ-001-02 isn't in `ci.publish.covers`, so job `publish` may not record it" in [
        p["message"] for p in run.json()["problems"]
    ]


@pytest.mark.covers(
    "SPC-REQ-007-05",
    "an inner run on attempt 3 with a check run ID links job 22, and without the ID links attempt 3",
)
@pytest.mark.covers(
    "SPC-REQ-007-07",
    "the run and job links an inner run builds from GitHub variables have the form runs/<id>/attempts/<n> and runs/<id>/job/<id>",
)
def test_links_point_at_the_attempt_and_the_job(ci_project: Project, monkeypatch: pytest.MonkeyPatch):
    """A test run on attempt 3 links that attempt, and its job by check run ID; without one, the attempt."""
    for name, value in {**JOB, "GITHUB_JOB": "unit"}.items():
        monkeypatch.setenv(name, value)
    ci_project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 1 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    ci_project.pytest("--speccheck-results=with-id.jsonl")
    ci = ci_project.results_lines("with-id.jsonl")[0]["ci"]
    assert ci["run_url"] == "https://github.com/o/r/actions/runs/11/attempts/3"
    assert ci["job_url"] == "https://github.com/o/r/actions/runs/11/job/22"
    monkeypatch.delenv("SPECCHECK_JOB_ID")
    ci_project.pytest("--speccheck-results=no-id.jsonl")
    assert ci_project.results_lines("no-id.jsonl")[0]["ci"]["job_url"] == ci["run_url"]


@pytest.mark.covers(
    "SPC-REQ-007-07",
    "a GitHub artifact URL of the run's repository is linked from the summary, and one missing its run segment is not",
)
def test_artifact_links_have_the_github_form(ci_project: Project):
    """`<server>/<owner>/<repo>/actions/runs/<id>/artifacts/<id>` is the one artifact form."""
    ci_project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
    for url, linked in (
        ("https://github.com/o/r/actions/runs/11/artifacts/5", True),
        ("https://github.com/o/r/actions/artifacts/5", False),
    ):
        ci_project.speccheck("verify", "r.jsonl", "--summary", "s.md", "--report-url", url, env=env)
        assert (f"[speccheck-report]({url})" in (ci_project.root / "s.md").read_text()) is linked, url
        (ci_project.root / "s.md").unlink()


@pytest.mark.parametrize(
    ("url", "env"),
    [
        pytest.param(
            "https://evil.example/o/r/actions/runs/11/artifacts/5",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "an artifact URL on another server is written as plain speccheck-report text"
            ),
            id="other-server",
        ),
        pytest.param(
            "https://github.com/evil/r/actions/runs/11/artifacts/5",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "an artifact URL in another repository is written as plain speccheck-report text"
            ),
            id="other-repository",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/11/artifacts/5",
            {},
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "outside CI an artifact URL is written as plain speccheck-report text"
            ),
            id="outside-ci",
        ),
    ],
)
def test_an_artifact_link_to_elsewhere_is_plain_text(ci_project: Project, url: str, env: dict):
    """The summary line still names the report, as text, with no URL in it."""
    ci_project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    ci_project.speccheck("verify", "r.jsonl", "--summary", "s.md", "--report-url", url, env=env)
    summary = (ci_project.root / "s.md").read_text()
    assert "evil" not in summary and "](" not in summary and "https://" not in summary


@pytest.mark.covers(
    "SPC-REQ-007-10",
    "a failing result whose job URL is on another server leaves that host out of both the verify --summary file and the report",
)
def test_the_summary_and_report_leave_out_a_foreign_job_url(project: Project):
    """Both markdown outputs, not only the report, leave the foreign URL out."""
    project.spec("- T-REQ-001-01: One.")
    foreign = "https://evil.example/o/r/actions/runs/7/job/8"
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "failed")], ci={**CI, "job_url": foreign})
    project.speccheck("verify", "r.jsonl", "--summary", "s.md", env=ENV)
    assert "evil" not in (project.root / "s.md").read_text()
    text = project.speccheck("report", "r.jsonl", env=ENV).out
    assert "evil" not in text


@pytest.mark.covers("SPC-REQ-007-05", "a result whose job URL is the run attempt's links runs/7/attempts/2")
def test_without_a_job_id_it_links_the_run(project: Project):
    """The fallback link is the run attempt."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": CI["run_url"]})
    text = project.speccheck("report", "u.jsonl", env=ENV).out
    assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/attempts/2)" in text


@pytest.mark.parametrize(
    ("url", "env"),
    [
        pytest.param(
            "https://evil.example/o/r/actions/runs/7/job/8",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "a job URL on another server than the run's isn't linked, and its host never appears in the report",
            ),
            id="other-server",
        ),
        pytest.param(
            "https://github.com/evil/r/actions/runs/7/job/8",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "a job URL on the run's server but in another repository isn't linked"
            ),
            id="other-repository",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/job/8\n",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "a job URL with a trailing newline isn't exactly a job link, so it isn't linked"
            ),
            id="trailing-newline",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/job/8",
            {},
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "outside CI there is no run to compare with, so a well-formed job URL isn't linked"
            ),
            id="outside-ci",
        ),
        *(
            pytest.param(
                url,
                ENV,
                marks=pytest.mark.covers(
                    "SPC-REQ-007-10", f"the job URL {url!r}, not of the run, job or attempt form, isn't linked"
                ),
                id=label,
            )
            for label, url in [
                ("extra-segment", "https://github.com/o/r/actions/runs/7/job/8/extra"),
                ("non-digit-job", "https://github.com/o/r/actions/runs/7/job/x"),
                ("zero-job", "https://github.com/o/r/actions/runs/7/job/0"),
                ("non-digit-run", "https://github.com/o/r/actions/runs/seven/job/8"),
                ("prefix-repository", "https://github.com/o/r2/actions/runs/7/job/8"),
                ("http", "http://github.com/o/r/actions/runs/7/job/8"),
                ("query", "https://github.com/o/r/actions/runs/7/job/8?x=1"),
                ("fragment", "https://github.com/o/r/actions/runs/7/job/8#x"),
            ]
        ),
        pytest.param(
            "javascript:x",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "a job URL using the javascript: scheme isn't linked, and the scheme never appears"
            ),
            id="javascript-scheme",
        ),
    ],
)
def test_only_this_runs_repository_is_linked(project: Project, url: str, env: dict):
    """A run or job URL on another host or repository isn't linked, and outside CI nothing is."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": url, "run_url": url})
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert "- ✅ passed in unit\n" in text and "- Runs: none" in text
    assert "evil" not in text and "javascript" not in text
