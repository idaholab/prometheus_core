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

from tests.requirements.conftest import CI, CONFIG, ENV, JOB, Project


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
    "record in a job whose entry lists two IDs writes a single result claiming both with their own explanations",
)
def test_record_claims_each_id_in_one_result(project: Project):
    """One result for the job, not one per ID, and each ID keeps its own explanation."""
    project.write(
        "speccheck.toml",
        CONFIG
        + '[ci.publish]\nworkflows = ["ci"]\n[ci.publish.covers]\n'
        + '"T-REQ-001-01" = "the publish job pushes the image"\n'
        + '"T-REQ-001-02" = "the publish job tags the release"\n',
    )
    project.spec("- T-REQ-001-01: It publishes.\n- T-REQ-001-02: It tags.")
    assert project.speccheck("record", env=JOB).code == 0
    lines = project.results_lines(".speccheck/publish.jsonl")
    assert len(lines) == 2, "a header and one result"
    assert lines[1]["covers"] == [
        {"id": "T-REQ-001-01", "how": "the publish job pushes the image"},
        {"id": "T-REQ-001-02", "how": "the publish job tags the release"},
    ]
    assert (lines[1]["outcome"], lines[1]["kind"]) == ("passed", "ci")
    statuses = {
        r["id"]: r["status"] for r in project.speccheck("verify", ".speccheck", "--json").json()["requirements"]
    }
    assert statuses == {"T-REQ-001-01": "passed", "T-REQ-001-02": "passed"}


@pytest.mark.covers(
    "SPC-REQ-007-05",
    "record in job publish on attempt 3 with check run ID 22 writes a header linking job 22 and run attempt 3, and without the ID links run attempt 3 as the job",
)
def test_record_writes_the_job_and_run_links(ci_project: Project):
    """The header `record` writes carries the same links a test run's does."""
    assert ci_project.speccheck("record", env=JOB).code == 0
    ci = ci_project.results_lines(".speccheck/publish.jsonl")[0]["ci"]
    assert ci["job_url"] == "https://github.com/o/r/actions/runs/11/job/22"
    assert ci["run_url"] == "https://github.com/o/r/actions/runs/11/attempts/3"
    no_id = {k: v for k, v in JOB.items() if k != "SPECCHECK_JOB_ID"}
    assert ci_project.speccheck("record", "--output", "no-id.jsonl", env=no_id).code == 0
    assert ci_project.results_lines("no-id.jsonl")[0]["ci"]["job_url"] == ci["run_url"]


@pytest.mark.covers(
    "SPC-REQ-007-05",
    "a report of a result from job 8 of run 7 attempt 2 links that job, and a re-run's job 9 links its own",
)
def test_a_report_links_each_attempts_own_job(project: Project):
    """The same test run twice, once per attempt: each result opens the job of the attempt that produced it."""
    project.spec("- T-REQ-001-01: One.")
    first = {**CI, "job_id": 8, "job_url": "https://github.com/o/r/actions/runs/7/job/8"}
    second = {
        **CI,
        "run_url": "https://github.com/o/r/actions/runs/7/attempts/3",
        "job_id": 9,
        "job_url": "https://github.com/o/r/actions/runs/7/job/9",
    }
    project.results("a.jsonl", "unit", [("t", ["T-REQ-001-01"], "failed")], ci=first)
    project.results("b.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=second)
    text = project.speccheck("report", "a.jsonl", "b.jsonl", env=ENV).out
    assert "- ❌ failed in [unit](https://github.com/o/r/actions/runs/7/job/8)" in text
    assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/job/9)" in text


@pytest.mark.covers(
    "SPC-REQ-007-01",
    "record in job build, which has no entry, and record outside any job both exit 2 with their own message and write nothing",
)
def test_record_without_an_entry_is_exit_2(ci_project: Project):
    """A job the config doesn't list, or no job at all, writes nothing."""
    run = ci_project.speccheck("record", env={**JOB, "GITHUB_JOB": "build"})
    assert run.code == 2 and "no [ci.build] entry for this job (CI jobs: publish)" in run.err
    run = ci_project.speccheck("record")
    assert run.code == 2 and "no job name: pass --job NAME, or run inside a GitHub Actions job" in run.err
    assert not (ci_project.root / ".speccheck").exists()


@pytest.mark.covers(
    "SPC-REQ-007-01",
    "record in job unit, a test producer that does exist in the config but is no CI job, exits 2 naming publish as the only CI job",
)
def test_record_for_a_test_producer_is_exit_2(ci_project: Project):
    """A name in the config isn't enough: only a `[ci.<job>]` entry makes a job one `record` can speak for."""
    run = ci_project.speccheck("record", env={**JOB, "GITHUB_JOB": "unit"})
    assert run.code == 2 and run.out == ""
    assert "no [ci.unit] entry for this job (CI jobs: publish)" in run.err
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
    "SPC-REQ-007-02",
    "a results file from publish whose results are of kind test, not ci, still counts only T-REQ-001-01 and flags its claim of T-REQ-001-02",
)
def test_a_ci_job_counts_only_for_its_own_ids_whatever_the_kind(ci_project: Project):
    """The entry limits the job, not the kind its results are written with."""
    ci_project.results("p.jsonl", "publish", [("t", ["T-REQ-001-01", "T-REQ-001-02"], "passed")], kind="test")
    run = ci_project.speccheck("verify", "p.jsonl", "--json")
    requirements = {r["id"]: r for r in run.json()["requirements"]}
    assert requirements["T-REQ-001-01"]["status"] == "passed"
    assert requirements["T-REQ-001-01"]["evidence"][0]["kind"] == "test"
    assert requirements["T-REQ-001-02"]["status"] == "untested"
    assert requirements["T-REQ-001-02"]["evidence"] == []
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
    "an inner run in a fake GitHub job writes provider, server, repository, workflow, job, run, attempt, job ID, commit, ref and event from the GITHUB_* variables",
)
def test_the_context_comes_from_the_github_variables(project: Project, monkeypatch: pytest.MonkeyPatch):
    """Every field of the `ci` block, each from its own variable."""
    env = {
        **JOB,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_REF": "refs/pull/365/merge",
        "GITHUB_EVENT_NAME": "pull_request",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "inner claim 20 of T-REQ-001-01")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl")
    ci = project.results_lines("r.jsonl")[0]["ci"]
    assert ci == {
        "provider": "github",
        "server": "https://github.com",
        "repository": "o/r",
        "workflow": "ci",
        "job": "publish",
        "run_id": 11,
        "run_attempt": 3,
        "job_id": 22,
        "sha": "a" * 40,
        "ref": "refs/pull/365/merge",
        "event": "pull_request",
        "run_url": "https://github.com/o/r/actions/runs/11/attempts/3",
        "job_url": "https://github.com/o/r/actions/runs/11/job/22",
    }


@pytest.mark.parametrize(
    ("kind", "url", "linked"),
    [
        pytest.param(
            "job",
            "https://github.com/o/r/actions/runs/7/job/8",
            True,
            marks=pytest.mark.covers("SPC-REQ-007-07", "a job URL with the run and no attempt is linked"),
            id="job",
        ),
        pytest.param(
            "job",
            "https://github.com/o/r/actions/runs/7/attempts/2/job/8",
            False,
            marks=pytest.mark.covers("SPC-REQ-007-07", "a job URL with an attempt segment is not linked"),
            id="job-with-attempt",
        ),
        pytest.param(
            "job",
            "https://github.com/o/r/actions/runs/7/attempts/2",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-007-07", "a run attempt URL, the fallback when no job is known, is linked"
            ),
            id="run-attempt",
        ),
        pytest.param(
            "job",
            "https://github.com/o/r/actions/runs/7",
            True,
            marks=pytest.mark.covers("SPC-REQ-007-07", "a run URL without an attempt is linked"),
            id="run-without-attempt",
        ),
        pytest.param(
            "artifact",
            "https://github.com/o/r/actions/runs/7/artifacts/5",
            True,
            marks=pytest.mark.covers("SPC-REQ-007-07", "an artifact URL with the run and no attempt is linked"),
            id="artifact",
        ),
        pytest.param(
            "artifact",
            "https://github.com/o/r/actions/runs/7/attempts/2/artifacts/5",
            False,
            marks=pytest.mark.covers("SPC-REQ-007-07", "an artifact URL with an attempt segment is not linked"),
            id="artifact-with-attempt",
        ),
        pytest.param(
            "artifact",
            "https://github.com/o/r/actions/runs/7",
            False,
            marks=pytest.mark.covers("SPC-REQ-007-07", "a run URL is not accepted as an artifact link"),
            id="run-as-artifact",
        ),
        pytest.param(
            "job",
            "https://github.com/o/r/actions/runs/7/artifacts/5",
            False,
            marks=pytest.mark.covers("SPC-REQ-007-07", "an artifact URL is not accepted as a job link"),
            id="artifact-as-job",
        ),
    ],
)
def test_each_kind_of_link_has_its_github_form(project: Project, kind: str, url: str, linked: bool):
    """Job links through `report`, artifact links through `verify --summary`: the form decides, not the host."""
    project.spec("- T-REQ-001-01: One.")
    if kind == "job":
        project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": url})
        text = project.speccheck("report", "u.jsonl", env=ENV).out
        assert (f"[unit]({url})" in text) is linked, text
    else:
        project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
        project.speccheck("verify", "u.jsonl", "--summary", "s.md", "--report-url", url, env=ENV)
        assert (f"[speccheck-report]({url})" in (project.root / "s.md").read_text()) is linked


@pytest.mark.covers(
    "SPC-REQ-007-07",
    "a GitHub artifact URL of the run's repository is linked from the summary, and one missing its run segment is not",
)
def test_artifact_links_have_the_github_form(ci_project: Project):
    """`<server>/<owner>/<repo>/actions/runs/<id>/artifacts/<id>` is the one artifact form."""
    ci_project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    env = ENV
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
                "SPC-REQ-007-10", "an artifact URL on another server leaves the summary with no report link and no URL"
            ),
            id="other-server",
        ),
        pytest.param(
            "https://github.com/evil/r/actions/runs/11/artifacts/5",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "an artifact URL in another repository leaves the summary with no report link and no URL",
            ),
            id="other-repository",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/11/artifacts/5",
            {},
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "outside CI an artifact URL leaves the summary with no report link and no URL"
            ),
            id="outside-ci",
        ),
        pytest.param(
            "http://github.com/o/r/actions/runs/11/artifacts/5",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "an artifact URL using http rather than https leaves the summary with no report link and no URL",
            ),
            id="http-scheme",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/11/artifacts/5?x=1",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "an artifact URL followed by a query string leaves the summary with no report link and no URL",
            ),
            id="query-string",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/11/artifacts/5\n",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "an artifact URL followed by a newline leaves the summary with no report link and no URL",
            ),
            id="trailing-newline",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/11/artifacts/5/extra",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "an artifact URL with a further path segment leaves the summary with no report link and no URL",
            ),
            id="extra-segment",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/11/artifacts/0",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "an artifact URL whose artifact ID is zero leaves the summary with no report link and no URL",
            ),
            id="zero-id",
        ),
    ],
)
def test_an_artifact_link_to_elsewhere_is_plain_text(ci_project: Project, url: str, env: dict):
    """The summary line is just the counts: no "Full report" clause, no link, no URL."""
    ci_project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    ci_project.speccheck("verify", "r.jsonl", "--summary", "s.md", "--report-url", url, env=env)
    summary = (ci_project.root / "s.md").read_text()
    assert "evil" not in summary and "](" not in summary and "https://" not in summary
    assert "Full report" not in summary


@pytest.mark.covers(
    "SPC-REQ-007-05",
    "a result with an empty job URL, and one with no job URL key, are each linked to runs/7/attempts/2, the run attempt",
)
def test_without_a_job_id_it_links_the_run(project: Project):
    """The fallback link is the run attempt."""
    project.spec("- T-REQ-001-01: One.")
    without_key = {k: v for k, v in CI.items() if k != "job_url"}
    for n, ci in enumerate(({**CI, "job_url": ""}, without_key)):
        project.results(f"u{n}.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=ci)
        text = project.speccheck("report", f"u{n}.jsonl", env=ENV).out
        assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/attempts/2)" in text, ci


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


@pytest.mark.parametrize(
    "flag",
    [
        pytest.param(
            flag,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                f"with a good server and repository but GITHUB_ACTIONS {what}, no job, run, source or report link is written",
            ),
            id=label,
        )
        for label, flag, what in (
            ("false", "false", "=false"),
            ("empty", "", "empty"),
            ("capitalised", "True", "=True rather than true"),
            ("unset", None, "not set"),
        )
    ],
)
def test_nothing_is_linked_unless_github_actions_is_true(project: Project, flag: str | None):
    """The server and repository variables alone don't make a run: `GITHUB_ACTIONS` must be exactly `true`."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=CI)
    env = {**ENV, "GITHUB_SHA": "a" * 40, "GITHUB_WORKSPACE": str(project.root)}
    if flag is None:
        del env["GITHUB_ACTIONS"]
    else:
        env["GITHUB_ACTIONS"] = flag
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert "- ✅ passed in unit\n" in text and "- Runs: none" in text and "/blob/" not in text
    report_url = "https://github.com/o/r/actions/runs/7/artifacts/5"
    project.speccheck("verify", "u.jsonl", "--summary", "s.md", "--report-url", report_url, env=env)
    summary = (project.root / "s.md").read_text()
    assert "Full report" not in summary and "https://" not in summary


@pytest.mark.covers(
    "SPC-REQ-007-10",
    "with GITHUB_ACTIONS=true and the same good server and repository, the same results file links job, run, source and report",
)
def test_in_github_actions_the_same_run_is_linked(project: Project):
    """The control for the test above: only the flag differs."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=CI)
    env = {**ENV, "GITHUB_SHA": "a" * 40, "GITHUB_WORKSPACE": str(project.root.parent)}
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert f"[unit]({CI['job_url']})" in text and f"[7/attempts/2]({CI['run_url']})" in text
    assert "/blob/" in text
    report_url = "https://github.com/o/r/actions/runs/7/artifacts/5"
    project.speccheck("verify", "u.jsonl", "--summary", "s.md", "--report-url", report_url, env=env)
    assert f"Full report: [speccheck-report]({report_url})" in (project.root / "s.md").read_text()


@pytest.mark.covers(
    "SPC-REQ-007-10",
    "a results file whose run URL is really a job URL gets no link on the Runs line, while its result line links the job URL given as the job's",
)
def test_a_job_url_is_not_a_run_link(project: Project):
    """The run position needs the run form (or an attempt); a job-form URL there is left out, though a job may be linked."""
    project.spec("- T-REQ-001-01: One.")
    job = "https://github.com/o/r/actions/runs/7/job/8"
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "run_url": job, "job_url": job})
    text = project.speccheck("report", "u.jsonl", env=ENV).out
    assert "- Runs: none" in text
    assert f"- ✅ passed in [unit]({job})" in text


@pytest.mark.covers(
    "SPC-REQ-007-10",
    "a result whose job URL is the run attempt's own URL is linked there, and a run attempt URL in the run position is listed",
)
def test_a_run_url_is_a_run_link_and_may_stand_for_a_job(project: Project):
    """Where the job is unknown, the run attempt is the link (007-05), and the Runs line lists it."""
    project.spec("- T-REQ-001-01: One.")
    run = "https://github.com/o/r/actions/runs/7/attempts/2"
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "run_url": run, "job_url": run})
    text = project.speccheck("report", "u.jsonl", env=ENV).out
    assert f"- Runs: [7/attempts/2]({run})" in text
    assert f"- ✅ passed in [unit]({run})" in text


@pytest.mark.parametrize(
    ("server", "repository", "linked"),
    [
        pytest.param(
            "https://github.com",
            "o/r",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "with a well-formed https server and owner/name repository, the same run has job, run, report and source links",
            ),
            id="well-formed",
        ),
        pytest.param(
            "http://github.com",
            "o/r",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10",
                "a server given as http:// is not a base to link under, so the run has no links at all",
            ),
            id="http-server",
        ),
        pytest.param(
            "https://github.com/",
            "o/r",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "a server with a trailing slash is not a base to link under, so the run has no links"
            ),
            id="server-trailing-slash",
        ),
        pytest.param(
            "https://github.com/enterprise",
            "o/r",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-007-10", "a server carrying a path is not a base to link under, so the run has no links"
            ),
            id="server-with-path",
        ),
        *(
            pytest.param(
                "https://github.com",
                repository,
                False,
                marks=pytest.mark.covers(
                    "SPC-REQ-007-10", f"the repository {repository!r}, not of the form owner/name, gets no links"
                ),
                id=label,
            )
            for label, repository in [
                ("owner-only", "o"),
                ("three-parts", "o/r/x"),
                ("space", "o r"),
                ("empty-repository", ""),
            ]
        ),
    ],
)
def test_a_malformed_server_or_repository_links_nothing(project: Project, server: str, repository: str, linked: bool):
    """URLs built from the same bad variables the run has: nothing links, and the text is still written."""
    project.spec("- T-REQ-001-01: One.")
    base = f"{server}/{repository}"
    ci = {**CI, "run_url": f"{base}/actions/runs/7/attempts/2", "job_url": f"{base}/actions/runs/7/job/8"}
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=ci)
    env = {
        **ENV,
        "GITHUB_SERVER_URL": server,
        "GITHUB_REPOSITORY": repository,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_WORKSPACE": str(project.root),
    }
    text = project.speccheck("report", "u.jsonl", env=env).out
    report_url = f"{base}/actions/runs/7/artifacts/5"
    project.speccheck("verify", "u.jsonl", "--summary", "s.md", "--report-url", report_url, env=env)
    summary = (project.root / "s.md").read_text()
    if linked:
        assert f"[unit]({ci['job_url']})" in text and f"[7/attempts/2]({ci['run_url']})" in text, text
        assert f"]({base}/blob/{'a' * 40}/specs/001-thing.md#L" in text, text
        assert f"[speccheck-report]({report_url})" in summary, summary
        return
    assert "- ✅ passed in unit\n" in text and "- Runs: none" in text, text
    assert "http" not in text and "\nIn [" not in text, text
    assert summary.startswith("**speccheck:**") and "Full report" not in summary, summary
    assert "](" not in summary and "http" not in summary, summary
