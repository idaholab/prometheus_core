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

"""specs/006-report.md: the markdown report, written by the real CLI from results files."""

from __future__ import annotations

import json
import re

import pytest

from tests.requirements.conftest import Project, spec

CI = {
    "job": "unit",
    "job_id": 8,
    "sha": "d" * 40,
    "run_url": "https://github.com/o/r/actions/runs/7/attempts/2",
    "job_url": "https://github.com/o/r/actions/runs/7/job/8",
}
"""A results file's CI block, from a re-run with a job ID."""
ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
"""The run `report` is in: links must be under its server and repository."""
SHA = "e" * 40
"""The commit the run tested, whose files the report links to."""


def section(text: str, heading: str) -> str:
    """The report's text from `heading` up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(f"\n{heading}\n") + 1
    rest = text[start + len(heading) + 1 :]
    ends = [m.start() for m in re.finditer(rf"^#{{1,{len(level)}}} ", rest, re.M)]
    return text[start : start + len(heading) + 1 + (ends[0] if ends else len(rest))]


@pytest.fixture
def reported(project: Project) -> Project:
    """A project with one passing, one failing and one unclaimed requirement, a Purpose, and a results file."""
    project.write(
        "specs/001-thing.md",
        spec(
            "- T-REQ-001-01: Passes.\n- T-REQ-001-02: Fails.\n- T-REQ-001-03: Nobody claims it.", title="The thing"
        ).replace("## Requirements", "## Purpose\n\nWhat the thing\npromises.\n\n## Requirements"),
    )
    project.results(
        "unit.jsonl",
        "unit",
        [("tests/t.py::test_ok", ["T-REQ-001-01"], "passed"), ("tests/t.py::test_bad", ["T-REQ-001-02"], "failed")],
        ci=CI,
    )
    return project


@pytest.mark.covers(
    "SPC-REQ-006-01",
    "a report of a pass, a failure and an unclaimed requirement opens with the counts and a specs table linking the spec with 3 requirements and its counts",
)
def test_the_counts_and_the_specs_table(reported: Project):
    """The summary line, a count per status, then one row per spec: link, number of requirements, counts."""
    text = reported.speccheck("report", "unit.jsonl").out
    assert text.startswith("# speccheck requirements\n\n3 requirements: 1 failed, 1 unclaimed, 1 passed\n")
    assert "❌ failed: 1 · ❌ unclaimed: 1 · ✅ passed: 1" in text
    assert "| [001 The thing](#001-the-thing) | 3 | ❌ 1 failed, ❌ 1 unclaimed, ✅ 1 passed |" in text
    assert text.index("## Specs") < text.index("## 001 The thing")


@pytest.mark.covers(
    "SPC-REQ-006-01",
    "a spec's section gives its Purpose on one line, then a status table with failed and unclaimed first, each ID linking to its section",
)
def test_a_spec_section_has_its_purpose_and_a_status_table(reported: Project):
    """The Purpose joined onto one line, and the table sorted by what needs attention."""
    spec_text = section(reported.speccheck("report", "unit.jsonl").out, "## 001 The thing")
    assert "\n\nWhat the thing promises.\n\n| Requirement | Status |\n|---|---|\n" in spec_text
    rows = [line for line in spec_text.splitlines() if line.startswith("| [T-")]
    assert rows == [
        "| [T-REQ-001-02](#t-req-001-02--failed) | ❌ failed |",
        "| [T-REQ-001-03](#t-req-001-03--unclaimed) | ❌ unclaimed |",
        "| [T-REQ-001-01](#t-req-001-01--passed) | ✅ passed |",
    ]


@pytest.mark.covers(
    "SPC-REQ-006-01",
    "each requirement gets a section in spec order with its full text quoted, its test as a subsection with How:, and an unclaimed one says what to add",
)
def test_a_section_per_requirement_and_per_claim(reported: Project):
    """Spec order, not status order; the claim's how under its own heading; nothing claimed says so."""
    text = reported.speccheck("report", "unit.jsonl").out
    headings = re.findall(r"^### (.+)$", text, re.M)
    assert headings == ["T-REQ-001-01 ✅ passed", "T-REQ-001-02 ❌ failed", "T-REQ-001-03 ❌ unclaimed"]
    passed = section(text, "### T-REQ-001-01 ✅ passed")
    assert "> Passes.\n" in passed
    # The helper writes every result with file tests/test_x.py; `_` outside a code span is escaped
    assert "#### Test `test_ok` in `tests/test_x.py`\n\n**How:** tests/t.py::test\\_ok proves T-REQ-001-01\n" in passed
    unclaimed = section(text, "### T-REQ-001-03 ❌ unclaimed")
    assert 'Not claimed: add `@pytest.mark.covers("T-REQ-001-03", "<how it proves it>")`' in unclaimed
    assert "####" not in unclaimed


@pytest.mark.covers(
    "SPC-REQ-006-01",
    "a requirement claimed by two tests and a CI job gets one subsection each, the job's headed Job with no file",
)
def test_each_claimant_has_its_own_subsection(project: Project):
    """Tests by name and file, a CI job by its name; each with its own explanation."""
    project.write(
        "speccheck.toml",
        'specs = "specs"\nid-prefix = "T"\n[producers.unit]\n[ci.publish]\ncovers = { "T-REQ-001-01" = "the image is pushed" }\n',
    )
    project.spec("- T-REQ-001-01: One.")
    project.results(
        "u.jsonl",
        "unit",
        [("tests/a.py::test_a", ["T-REQ-001-01"], "passed"), ("tests/b.py::test_b", ["T-REQ-001-01"], "passed")],
    )
    project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01"], "passed")], kind="ci")
    text = project.speccheck("report", "p.jsonl", "u.jsonl").out
    assert re.findall(r"^#### (.+)$", text, re.M) == [
        "Job `publish`",
        "Test `test_a` in `tests/test_x.py`",
        "Test `test_b` in `tests/test_x.py`",
    ]
    assert "**How:** publish proves T-REQ-001-01" in text  # the how in the job's own result


@pytest.mark.covers(
    "SPC-REQ-006-02",
    "with --job-names, each result line gives its outcome and the job's display name linking job 8, failures first",
)
def test_results_name_the_job_and_link_it(project: Project):
    """One line per job that ran the test, worst first, by display name, linked to the job."""
    project.write("names.json", json.dumps({"8": "unit python 3.12", "9": "unit python 3.13"}))
    project.spec("- T-REQ-001-01: One.")
    project.results("a.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "passed")], ci=CI)
    late = {**CI, "job_id": 9, "job_url": "https://github.com/o/r/actions/runs/7/job/9"}
    project.results("b.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "skipped")], ci=late)
    text = project.speccheck("report", "a.jsonl", "b.jsonl", "--job-names", "names.json", env=ENV).out
    lines = [line for line in text.splitlines() if line.startswith("- ") and " in " in line and "Commit" not in line]
    assert lines == [
        "- ❌ skipped in [unit python 3.13](https://github.com/o/r/actions/runs/7/job/9)",
        "- ✅ passed in [unit python 3.12](https://github.com/o/r/actions/runs/7/job/8)",
    ]


@pytest.mark.covers(
    "SPC-REQ-006-02",
    "without --job-names, or for a job ID the names don't list, a result is named by its producer, and still linked",
)
def test_without_a_name_a_result_is_named_by_its_producer(reported: Project):
    """The names are optional: a plain list of results files still gives a readable report."""
    reported.write("names.json", json.dumps({"999": "someone else"}))
    for extra in ([], ["--job-names", "names.json"]):
        text = reported.speccheck("report", "unit.jsonl", *extra, env=ENV).out
        assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/job/8)" in text, extra


@pytest.mark.covers("SPC-REQ-006-02", "a result whose job URL is the run attempt's links runs/7/attempts/2")
def test_without_a_job_id_it_links_the_run(project: Project):
    """The fallback link is the run attempt."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": CI["run_url"]})
    text = project.speccheck("report", "u.jsonl", env=ENV).out
    assert "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/attempts/2)" in text


@pytest.mark.covers(
    "SPC-REQ-006-03",
    "a test name, explanation and job name holding a link, an img tag, emphasis and a heading stay text, and a javascript: URL isn't linked",
)
def test_untrusted_text_cant_add_markdown(project: Project):
    """Code spans hold names; outside them, what could make a link, HTML or emphasis is escaped."""
    project.spec("- T-REQ-001-01: One.")
    project.write("names.json", json.dumps({"8": "# [x](https://evil) <b>*bold*</b>"}))
    evil = "t[click](https://evil)<img src=x onerror=1>`"
    ci = {**CI, "job_url": "javascript:x", "run_url": "javascript:x"}
    header = json.dumps({"schema": "speccheck-results/1", "producer": "unit", "ci": ci}) + "\n"
    line = {
        "test": evil,
        "covers": [{"id": "T-REQ-001-01", "how": "# see [here](https://evil) <i>_x_</i>"}],
        "outcome": "passed",
    }
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    text = project.speccheck("report", "u.jsonl", "--job-names", "names.json", env=ENV).out
    assert "#### Test `t[click](https://evil)<img src=x onerror=1>`" in text
    assert "**How:** # see \\[here\\](https://evil) \\<i\\>\\_x\\_\\</i\\>" in text
    assert "- ✅ passed in # \\[x\\](https://evil) \\<b\\>\\*bold\\*\\</b\\>" in text
    assert "javascript" not in text
    # Outside code spans, no bracket or angle bracket is left unescaped
    prose = re.sub(r"`[^`]*`", "", text)
    assert re.search(r"(?<!\\)\]\(https://evil", prose) is None and re.search(r"(?<!\\)<(?:img|b|i)", prose) is None


@pytest.mark.covers(
    "SPC-REQ-006-03",
    "a 1000-character explanation appears whole, while a 900-character test name is cut at 150 with an ellipsis",
)
def test_names_and_explanations_are_capped(project: Project):
    """Explanations keep their 1000 characters; a huge test name doesn't make a huge heading."""
    project.spec("- T-REQ-001-01: One.")
    how = ("a reasonable sentence " * 50)[:1000].strip()
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = {"test": "x" * 900, "covers": [{"id": "T-REQ-001-01", "how": how}], "outcome": "passed"}
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    text = project.speccheck("report", "u.jsonl").out
    assert f"**How:** {how}" in text
    heading = next(line for line in text.splitlines() if line.startswith("#### Test"))
    assert len(heading) < 200 and "…" in heading


@pytest.mark.parametrize(
    ("url", "env"),
    [
        pytest.param(
            "https://evil.example/o/r/actions/runs/7/job/8",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-006-03",
                "a job URL on another server than the run's isn't linked, and its host never appears in the report",
            ),
            id="other-server",
        ),
        pytest.param(
            "https://github.com/evil/r/actions/runs/7/job/8",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-006-03", "a job URL on the run's server but in another repository isn't linked"
            ),
            id="other-repository",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/job/8\n",
            ENV,
            marks=pytest.mark.covers(
                "SPC-REQ-006-03", "a job URL with a trailing newline isn't exactly a job link, so it isn't linked"
            ),
            id="trailing-newline",
        ),
        pytest.param(
            "https://github.com/o/r/actions/runs/7/job/8",
            {},
            marks=pytest.mark.covers(
                "SPC-REQ-006-03", "outside CI there is no run to compare with, so a well-formed job URL isn't linked"
            ),
            id="outside-ci",
        ),
    ],
)
def test_only_this_runs_repository_is_linked(project: Project, url: str, env: dict):
    """A run or job URL on another host or repository isn't linked, and outside CI nothing is."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci={**CI, "job_url": url, "run_url": url})
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert "- ✅ passed in unit\n" in text and "- Runs: none" in text
    assert "evil" not in text


@pytest.mark.covers(
    "SPC-REQ-006-05",
    "the report's Inputs section lists the commit, the linked run attempt, producer unit as reported and docker as missing",
)
def test_the_inputs(reported: Project):
    """Commit, runs, producers reported and missing."""
    reported.write("speccheck.toml", 'specs = "specs"\nid-prefix = "T"\n[producers.unit]\n[producers.docker]\n')
    reported.speccheck("report", "unit.jsonl", "--complete", "--output", "out/report.md", env=ENV)
    text = (reported.root / "out" / "report.md").read_text()
    inputs = text.split("## Inputs", 1)[1]
    assert "- Commit: dddddddddddd" in inputs
    assert "- Runs: [7/attempts/2](https://github.com/o/r/actions/runs/7/attempts/2)" in inputs
    assert "- Producers reported: unit" in inputs and "- Producers missing: docker" in inputs


@pytest.mark.covers("SPC-REQ-006-06", "inputs that make verify exit 1 still let report write r.md and exit 0")
def test_report_exits_0_when_verify_fails(reported: Project):
    """The same inputs fail verify and still give a report, with exit 0."""
    assert reported.speccheck("verify", "unit.jsonl").code == 1
    run = reported.speccheck("report", "unit.jsonl", "--output", "r.md")
    assert run.code == 0 and (reported.root / "r.md").is_file()


@pytest.mark.covers(
    "SPC-REQ-006-07",
    "in CI, a requirement links its spec line and a test its file line at GITHUB_SHA, both as paths from the repository's root",
)
def test_requirements_and_tests_link_to_their_lines(project: Project):
    """The project is a sub folder of the workspace, so both paths start with its name."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", "root": "proj"}
    line = {
        "test": "tests/t.py::test_a",
        "file": "tests/t.py",
        "line": 12,
        "covers": [{"id": "T-REQ-001-01", "how": "h"}],
        "outcome": "passed",
    }
    project.write("u.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    root = project.root.name
    env = {**ENV, "GITHUB_SHA": SHA, "GITHUB_WORKSPACE": str(project.root.parent)}
    text = project.speccheck("report", "u.jsonl", env=env).out
    blob = f"https://github.com/o/r/blob/{SHA}"
    assert f"In [`{root}/specs/001-thing.md:7`]({blob}/{root}/specs/001-thing.md#L7)" in text
    assert f"#### Test [`test_a`]({blob}/proj/tests/t.py#L12) in `proj/tests/t.py`" in text


@pytest.mark.parametrize(
    ("change", "env"),
    [
        pytest.param(
            {"root": "proj", "file": "../outside.py"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-07", "a test file path that climbs out with .. is shown but not linked"
            ),
            id="dot-dot",
        ),
        pytest.param(
            {"root": "proj", "file": "tests/t.py?x=1#frag"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-07", "a test file path holding URL characters like ? and # is shown but not linked"
            ),
            id="url-characters",
        ),
        pytest.param(
            {"root": None, "file": "tests/t.py"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-07", "a results file that doesn't know its repository root gets no test link"
            ),
            id="no-root",
        ),
        pytest.param(
            {"root": "proj", "file": "tests/t.py"},
            {**ENV, "GITHUB_SHA": "not-a-sha"},
            marks=pytest.mark.covers(
                "SPC-REQ-006-07", "a GITHUB_SHA that isn't a full commit hash links no spec or test line"
            ),
            id="bad-sha",
        ),
        pytest.param(
            {"root": "proj", "file": "tests/t.py"},
            {},
            marks=pytest.mark.covers("SPC-REQ-006-07", "outside CI no spec or test line is linked"),
            id="outside-ci",
        ),
    ],
)
def test_a_source_link_needs_a_plain_path_and_ci(project: Project, change: dict, env: dict):
    """The heading still names the test and its file; there is just no link to `blob/`."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", "root": change["root"]}
    line = {
        "test": "x::test_a",
        "file": change["file"],
        "line": 3,
        "covers": [{"id": "T-REQ-001-01", "how": "h"}],
        "outcome": "passed",
    }
    project.write("u.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    text = project.speccheck("report", "u.jsonl", env={**env, "GITHUB_WORKSPACE": str(project.root.parent)}).out
    heading = next(line for line in text.splitlines() if line.startswith("#### Test"))
    assert heading.startswith("#### Test `test_a` in `") and "/blob/" not in heading
    if env.get("GITHUB_SHA") != SHA:
        assert "/blob/" not in text
