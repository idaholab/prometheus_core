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
from markdown_it import MarkdownIt

from speccheck.actions.report import OUTCOMES
from tests.conftest import CONFIG, INDEX, spec
from tests.requirements.conftest import CI, ENV, JOB, Project

SHA = "e" * 40
"""The commit the run tested, whose files the report links to."""
CONFIG_WITH_NIGHTLY = (
    'specs = "specs"\nid-prefix = "T"\n[producers.unit]\nworkflows = ["ci"]\n[producers.nightly]\nworkflows = ["ci"]\n'
)
"""A config with a second producer, `nightly`, that never reports in these tests."""


def anchor(heading: str) -> str:
    """The link anchor GitHub makes of a heading: lower case, punctuation dropped, spaces as hyphens.

    Written here from that rule rather than imported, so the report's own anchors are checked against it.
    """
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def section(text: str, heading: str) -> str:
    """The report's text from `heading` up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(f"\n{heading}\n") + 1
    rest = text[start + len(heading) + 1 :]
    ends = [m.start() for m in re.finditer(rf"^#{{1,{len(level)}}} ", rest, re.M)]
    return text[start : start + len(heading) + 1 + (ends[0] if ends else len(rest))]


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


@pytest.fixture
def two_specs(project: Project) -> Project:
    """Two specs with every status between them, a `nightly` producer that never reports, and one result.

    Spec 001 (with a Purpose): passed, failed, unclaimed. Spec 002 (no Purpose): two unimplemented, and one
    requirement only `nightly` could prove, so it is `not run`.
    """
    project.write(
        "speccheck.toml",
        'specs = "specs"\nid-prefix = "T"\n[producers.unit]\nspecs = ["001"]\n[producers.nightly]\nspecs = ["002"]\n',
    )
    project.write("specs/000-index.md", "# Index\n\n- [001](001-a.md)\n- [002](002-b.md)\n")
    project.write(
        "specs/001-a.md",
        spec(
            "- T-REQ-001-01: Passes.\n- T-REQ-001-02: Fails.\n- T-REQ-001-03: Nobody claims it.", title="Alpha"
        ).replace("## Requirements", "## Purpose\n\nThe first\nspec.\n\n## Requirements"),
    )
    project.write(
        "specs/002-b.md",
        spec(
            "- T-REQ-002-01: Later. (unimplemented: step 3)\n"
            "- T-REQ-002-02: Much later. (unimplemented: the `cache` | plan *b*)\n"
            "- T-REQ-002-03: Waits for the nightly run.",
            number="002",
            title="Beta",
        ),
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
    "a report of two specs holding every status lists one row per spec with its own count, leaves out statuses with none, and opens with the counts of the five statuses it has",
)
def test_several_specs_and_every_status(two_specs: Project):
    """Rows per spec, zero counts left out, and the summary line in order from the worst status."""
    text = two_specs.speccheck("report", "unit.jsonl", env=ENV).out
    assert text.startswith(
        "# speccheck requirements\n\n6 requirements: 1 failed, 1 unclaimed, 1 not run, 1 passed, 2 unimplemented\n"
    )
    rows = [line for line in section(text, "## Specs").splitlines() if line.startswith("| [")]
    assert rows == [
        "| [001 Alpha](#001-alpha) | 3 | ❌ 1 failed, ❌ 1 unclaimed, ✅ 1 passed |",
        "| [002 Beta](#002-beta) | 3 | ⏸ 1 not run, 🗓 2 unimplemented |",
    ]
    counts_line = text.splitlines()[4]
    assert counts_line == "❌ failed: 1 · ❌ unclaimed: 1 · ⏸ not run: 1 · ✅ passed: 1 · 🗓 unimplemented: 2"


@pytest.mark.covers(
    "SPC-REQ-006-01",
    "a report with exactly one requirement says '1 requirement', not '1 requirements'",
)
def test_one_requirement_is_singular(project: Project):
    """The summary line's noun agrees with the count."""
    project.spec("- T-REQ-001-01: One.")
    project.results("u.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    assert project.speccheck("report", "u.jsonl").out.startswith(
        "# speccheck requirements\n\n1 requirement: 1 passed\n"
    )


@pytest.mark.covers(
    "SPC-REQ-006-01",
    "each link in the specs table points at a heading the report has, for two specs and a title with punctuation",
)
def test_the_specs_table_links_resolve(two_specs: Project):
    """GitHub's anchor for each heading is the one the table links to."""
    two_specs.spec("- T-REQ-002-01: x.", number="002", name="002-b.md", title="Beta: the (second) one")
    text = two_specs.speccheck("report", "unit.jsonl", env=ENV).out
    headings = re.findall(r"^## (.+)$", text, re.M)
    targets = re.findall(r"^\| \[[^\]]+\]\(#([^)]+)\) \| \d+ \|", text, re.M)
    assert len(targets) == 2
    assert {anchor(h) for h in headings} >= set(targets), (headings, targets)


@pytest.mark.covers(
    "SPC-REQ-006-07",
    "a spec holding failed, unclaimed, not run, passed and unimplemented requirements, written in reverse, lists them in that order",
)
def test_the_status_table_orders_every_status(project: Project):
    """Failed, unclaimed and not run first, in that order, then passed, then unimplemented, whatever the spec order."""
    # A CI job that claims T-REQ-001-03 and never reports, so that one alone is not run
    project.write("speccheck.toml", CONFIG + '[ci.nightly.covers]\n"T-REQ-001-03" = "the nightly job waits"\n')
    project.spec(
        "- T-REQ-001-01: Later. (unimplemented: step 2)\n- T-REQ-001-02: Passes.\n- T-REQ-001-03: Waits.\n"
        "- T-REQ-001-04: Nobody.\n- T-REQ-001-05: Fails."
    )
    project.results(
        "u.jsonl",
        "unit",
        [
            ("tests/t.py::test_ok", ["T-REQ-001-02"], "passed"),
            ("tests/t.py::test_bad", ["T-REQ-001-05"], "failed"),
        ],
    )
    text = project.speccheck("report", "u.jsonl").out
    rows = [
        line.split(" | ", 1)[1].removesuffix(" |")
        for line in section(text, "## 001 Thing").splitlines()
        if line.startswith("| [T-")
    ]
    assert rows == ["❌ failed", "❌ unclaimed", "⏸ not run", "✅ passed", "🗓 unimplemented: step 2"]


@pytest.mark.covers(
    "SPC-REQ-006-07",
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
    "SPC-REQ-006-07",
    "a spec with a not run requirement listed last and two unimplemented ones lists not run first, then each unimplemented one with its reason escaped",
)
def test_the_status_table_puts_not_run_before_the_rest(two_specs: Project):
    """Spec 002's table: `not run` first, then the unimplemented ones in spec order, each with its reason."""
    text = two_specs.speccheck("report", "unit.jsonl", env=ENV).out
    rows = [line for line in section(text, "## 002 Beta").splitlines() if line.startswith("| [T-")]
    assert rows == [
        "| [T-REQ-002-03](#t-req-002-03--not-run) | ⏸ not run |",
        "| [T-REQ-002-01](#t-req-002-01--unimplemented) | 🗓 unimplemented: step 3 |",
        "| [T-REQ-002-02](#t-req-002-02--unimplemented) | 🗓 unimplemented: the `cache` \\| plan \\*b\\* |",
    ]


@pytest.mark.covers(
    "SPC-REQ-006-08",
    "an unimplemented requirement's section quotes its text without the suffix and gives the reason, escaped, on its own line under it",
)
def test_an_unimplemented_requirement_shows_its_reason(two_specs: Project):
    """The suffix is not quoted as part of the text; the reason is shown once, as its own line."""
    text = two_specs.speccheck("report", "unit.jsonl", env=ENV).out
    body = section(text, "### T-REQ-002-02 🗓 unimplemented")
    assert body.startswith(
        "### T-REQ-002-02 🗓 unimplemented\n\n> Much later.\n\n**Unimplemented:** the `cache` \\| plan \\*b\\*\n\n"
    )
    assert "(unimplemented" not in body


@pytest.mark.covers(
    "SPC-REQ-006-07",
    "a spec with no Purpose section has a heading, a blank line and the status table, with no stray paragraph between",
)
def test_a_spec_without_a_purpose_has_no_paragraph(two_specs: Project):
    """Nothing is written for a Purpose that isn't there; the Purpose of the other spec is."""
    text = two_specs.speccheck("report", "unit.jsonl", env=ENV).out
    assert section(text, "## 002 Beta").startswith("## 002 Beta\n\n| Requirement | Status |\n|---|---|\n")
    assert section(text, "## 001 Alpha").startswith("## 001 Alpha\n\nThe first spec.\n\n| Requirement | Status |")


@pytest.mark.covers(
    "SPC-REQ-006-07",
    "every ID link in a spec's status table points at the heading of that requirement's own section",
)
def test_a_status_table_link_resolves_to_its_requirements_section(two_specs: Project):
    """The anchor in the table is the one GitHub makes of the requirement's heading."""
    text = two_specs.speccheck("report", "unit.jsonl", env=ENV).out
    anchors = {anchor(h) for h in re.findall(r"^### (.+)$", text, re.M)}
    linked = re.findall(r"^\| \[T-[^\]]+\]\(#([^)]+)\) \|", text, re.M)
    assert len(linked) == 6 and set(linked) <= anchors, (linked, anchors)


@pytest.mark.covers(
    "SPC-REQ-006-08",
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
    "SPC-REQ-006-08",
    "a requirement of 600 words wrapped over 60 lines, with a code span in it, is quoted in the report whole, to its last word",
)
def test_a_long_requirement_is_quoted_in_full(project: Project):
    """No cut: the reader of the report sees everything the requirement promises, past any cell-sized limit."""
    words = [f"word{n}" for n in range(600)]
    words[300] = "`a b`"
    wrapped = "\n  ".join(" ".join(words[start : start + 10]) for start in range(0, 600, 10))
    project.spec(f"- T-REQ-001-01: {wrapped}")
    project.results("u.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "passed")])
    text = project.speccheck("report", "u.jsonl").out
    quoted = section(text, "### T-REQ-001-01 ✅ passed").split("\n", 2)[2].split("\n\n", 1)[0]
    assert quoted == "> " + " ".join(words)
    assert len(quoted) > 3000 and quoted.endswith("word599") and "…" not in quoted


@pytest.mark.covers(
    "SPC-REQ-006-08",
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
    # Each test's own how sits under its own heading, in order (`_` outside a code span is escaped)
    assert re.findall(r"^\*\*How:\*\* (.+)$", text, re.M) == [
        "publish proves T-REQ-001-01",
        "tests/a.py::test\\_a proves T-REQ-001-01",
        "tests/b.py::test\\_b proves T-REQ-001-01",
    ]


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


@pytest.mark.parametrize(
    ("names", "ci", "expected"),
    [
        pytest.param(
            None,
            CI,
            "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/job/8)",
            marks=pytest.mark.covers(
                "SPC-REQ-006-02", "with no --job-names file a result is named by its producer and linked to its job"
            ),
            id="no-names-file",
        ),
        pytest.param(
            {"99": "some other job"},
            CI,
            "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/job/8)",
            marks=pytest.mark.covers(
                "SPC-REQ-006-02", "a --job-names file with no entry for job 8 names the result by its producer"
            ),
            id="id-not-in-the-names",
        ),
        pytest.param(
            {"8": "unit python 3.12"},
            {**CI, "job_id": None, "job_url": "https://github.com/o/r/actions/runs/7/attempts/2"},
            "- ✅ passed in [unit](https://github.com/o/r/actions/runs/7/attempts/2)",
            marks=pytest.mark.covers(
                "SPC-REQ-006-02",
                "a result with no job ID is named by its producer, since the names are by ID, and linked to its run attempt",
            ),
            id="no-job-id",
        ),
        pytest.param(
            {"8": "unit python 3.12"},
            {**CI, "job_url": "https://evil.example/o/r/actions/runs/7/job/8"},
            "- ✅ passed in unit python 3.12",
            marks=pytest.mark.covers(
                "SPC-REQ-006-02",
                "a result whose job URL is on another server keeps its display name and is written plainly, with no link",
            ),
            id="foreign-url",
        ),
    ],
)
def test_the_result_line_without_a_name_or_a_link(project: Project, names: dict | None, ci: dict, expected: str):
    """A name when the map has one for this job's ID, the producer otherwise; a link only when the URL is this run's."""
    project.spec("- T-REQ-001-01: One.")
    project.results("a.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], "passed")], ci=ci)
    args = []
    if names is not None:
        project.write("names.json", json.dumps(names))
        args = ["--job-names", "names.json"]
    text = project.speccheck("report", "a.jsonl", *args, env=ENV).out
    assert [line for line in text.splitlines() if " passed in " in line] == [expected]
    assert "evil" not in text


@pytest.mark.covers(
    "SPC-REQ-006-02",
    "a CI job's result line gives its outcome and the job named by its display name, linked to its job",
)
def test_a_ci_jobs_result_line_names_and_links_it(ci_project: Project):
    """The result of a `record` run, not a test's, has the same line."""
    ci_project.write("names.json", json.dumps({"8": "publish the image"}))
    ci_project.results("p.jsonl", "publish", [("publish", ["T-REQ-001-01"], "passed")], kind="ci", ci=CI)
    text = ci_project.speccheck("report", "p.jsonl", "--job-names", "names.json", env=ENV).out
    assert "- ✅ passed in [publish the image](https://github.com/o/r/actions/runs/7/job/8)" in text


@pytest.mark.covers(
    "SPC-REQ-006-03",
    "a test name, explanation and job name holding a link, an img tag, emphasis and a heading stay text",
)
def test_untrusted_text_cant_add_markdown(project: Project):
    """Code spans hold names; outside them, what could make a link, HTML or emphasis is escaped."""
    project.spec("- T-REQ-001-01: One.")
    project.write("names.json", json.dumps({"8": "# [x](https://evil) <b>*bold*</b>"}))
    evil = "t[click](https://evil)<img src=x onerror=1>`"
    ci = {"job": "unit", "job_id": 8}  # a job ID to name, but no URL, so the name is plain text
    header = json.dumps({"schema": "speccheck-results/1", "producer": "unit", "ci": ci}) + "\n"
    line = {
        "test": evil,
        "covers": [{"id": "T-REQ-001-01", "how": "# see [here](https://evil) <i>_x_</i>"}],
        "outcome": "passed",
    }
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    text = project.speccheck("report", "u.jsonl", "--job-names", "names.json", env=ENV).out
    assert "#### Test `t[click](https://evil)<img src=x onerror=1>`" in text
    assert "**How:** # see \\[here\\](https\\://evil) \\<i\\>\\_x\\_\\</i\\>" in text
    assert "- ✅ passed in # \\[x\\](https\\://evil) \\<b\\>\\*bold\\*\\</b\\>" in text
    # Outside code spans, no bracket or angle bracket is left unescaped
    prose = re.sub(r"`[^`]*`", "", text)
    assert re.search(r"(?<!\\)\]\(https://evil", prose) is None and re.search(r"(?<!\\)<(?:img|b|i)", prose) is None


@pytest.mark.parametrize(
    "how",
    [
        pytest.param(
            "x `a```b` ![px](https://evil.example/t.png) [login](https://evil.example/p) `",
            marks=pytest.mark.covers(
                "SPC-REQ-006-03",
                "an explanation pairing a single backtick with a run of three renders through CommonMark and GitHub autolinks with no link or image",
            ),
            id="run-of-three",
        ),
        pytest.param(
            "``[login](https://evil.example/p)`` and `<img src=https://evil.example/t.png>`",
            marks=pytest.mark.covers(
                "SPC-REQ-006-03",
                "an explanation in double-backtick spans renders through CommonMark and GitHub autolinks with no link, image or HTML",
            ),
            id="double-backticks",
        ),
        pytest.param(
            "`` ` `` [login](https://evil.example/p) ` ``` `",
            marks=pytest.mark.covers(
                "SPC-REQ-006-03",
                "an explanation mixing backtick runs of one, two and three renders through CommonMark and GitHub autolinks with no link",
            ),
            id="mixed-runs",
        ),
    ],
)
def test_backtick_runs_cant_open_a_link(project: Project, how: str):
    """The report as a markdown renderer reads it: no element that links or loads anything."""
    project.spec("- T-REQ-001-01: One.")
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": how}], "outcome": "passed"}
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    html = renderer().render(project.speccheck("report", "u.jsonl").out)
    # The report's own links are anchors within it; nothing may point anywhere else or load anything
    assert re.findall(r'<a href="(?!#)[^"]*"|<img\b', html) == []


PAYLOADS = [
    "# h",
    "- x",
    "> q",
    "1. n",
    "---",
    "<https://e.com>",
    "https://e.com/p",
    "www.e.com",
    "a@b.com",
    "*e*",
    "<b>x</b>",
    "![i](https://e.com/i.png)",
]
"""Text that, written raw at the start of a line or in the middle of one, would add an element to the report."""
STRUCTURE = {
    "heading_open",
    "bullet_list_open",
    "ordered_list_open",
    "blockquote_open",
    "hr",
    "link_open",
    "image",
    "html_inline",
    "html_block",
    "em_open",
    "strong_open",
    "fence",
    "code_block",
}
"""The markdown elements 006-03 says text from outside must not add."""


def renderer() -> MarkdownIt:
    """CommonMark with GitHub's extended autolinks: a bare `http(s)://` URL, `www.` host or email address becomes a link.

    linkify-it's fuzzy links also link a bare `e.com` or `t.py`, which GitHub leaves as text, so this is
    stricter than GitHub: a report that passes here has nothing GitHub would link either.
    """
    return MarkdownIt("commonmark", {"linkify": True}).enable("linkify")


def elements(text: str) -> list[str]:
    """The element tokens in the report as a CommonMark renderer reads it, raw HTML allowed, sorted."""
    found = []
    for token in renderer().parse(text):
        found += [token.type] + [child.type for child in token.children or []]
    return sorted(t for t in found if t in STRUCTURE)


def hostile_spec(project: Project, text: str, purpose: str, title: str) -> None:
    """Spec 001 whose requirement text, Purpose and title are the given strings."""
    project.write(
        "specs/001-thing.md",
        f"# 001 - {title}\n\nstatus: draft\n\n## Purpose\n\n{purpose}\n\n## Requirements\n\n- T-REQ-001-01: {text}\n",
    )


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            payload,
            marks=pytest.mark.covers(
                "SPC-REQ-006-03",
                f"a spec whose requirement text, Purpose and title are {payload!r} renders through CommonMark and GitHub autolinks "
                "with the same elements as a spec of plain words",
            ),
            id=payload,
        )
        for payload in PAYLOADS
    ],
)
def test_spec_text_cant_add_markdown(project: Project, payload: str):
    """Requirement text, Purpose and title come from a spec a pull request can edit; compared with plain words."""
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    hostile_spec(project, payload, payload, payload)
    hostile = project.speccheck("report", "u.jsonl").out
    hostile_spec(project, "plain words", "plain words", "plain words")
    plain = project.speccheck("report", "u.jsonl").out
    assert elements(plain), "the plain report has elements of its own (headings, anchors), so the check can fail"
    assert elements(hostile) == elements(plain), hostile


@pytest.mark.covers(
    "SPC-REQ-006-03",
    "a results file whose producer is a heading, link and HTML, listed in the Inputs, adds no element",
)
def test_a_producer_name_cant_add_markdown(project: Project):
    """A producer name comes from the results file, so it is arbitrary (a configured one is restricted to safe characters)."""
    project.spec("- T-REQ-001-01: One.")

    def report(producer: str) -> str:
        """The report of one passing result written by a producer of this name."""
        header = json.dumps({"schema": "speccheck-results/1", "producer": producer}) + "\n"
        line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
        project.write("u.jsonl", header + json.dumps(line) + "\n")
        return project.speccheck("report", "u.jsonl").out

    hostile = report("# [x](https://e.com) <b>*y*</b>")
    assert "- Producers reported: " in hostile
    assert elements(hostile) == elements(report("plain"))


def _shown(project: Project, kind: str, length: int):
    """Run `report` with a `kind` of name that is `length` letters long; the run, and the name as the report shows it."""
    project.spec("- T-REQ-001-01: One.")
    name = "x" * length
    ci = {"job": "unit", "job_id": 8}  # a job ID to name, but no URL, so the name is plain text
    if kind == "display":
        project.write("names.json", json.dumps({"8": name}))
        project.results("u.jsonl", "unit", [("t.py::test_a", ["T-REQ-001-01"], "passed")], ci=ci)
        run = project.speccheck("report", "u.jsonl", "--job-names", "names.json")
        return run, (lambda text: next(x for x in text.splitlines() if " passed in " in x).split(" passed in ", 1)[1])
    if kind == "producer":
        project.results("u.jsonl", name, [("t.py::test_a", ["T-REQ-001-01"], "passed")])
        run = project.speccheck("report", "u.jsonl")
        return run, (
            lambda text: next(x for x in text.splitlines() if x.startswith("- Producers reported: ")).split(": ", 1)[1]
        )
    if kind == "job":
        project.results("u.jsonl", "unit", [(name, ["T-REQ-001-01"], "passed")], kind="ci")
        run = project.speccheck("report", "u.jsonl")
        return run, (
            lambda text: next(x for x in text.splitlines() if x.startswith("#### Job ")).split(" ", 2)[2].strip("`")
        )
    project.results("u.jsonl", "unit", [(name, ["T-REQ-001-01"], "passed")])
    run = project.speccheck("report", "u.jsonl")
    return run, (lambda text: next(x for x in text.splitlines() if x.startswith("#### Test ")))


@pytest.mark.parametrize(
    ("kind", "limit"),
    [
        pytest.param(
            kind,
            limit,
            marks=pytest.mark.covers(
                "SPC-REQ-006-09",
                f"a {kind} name of exactly {limit} characters is accepted and listed in the report"
                + (" (its heading may shorten it)" if kind == "test" else " whole")
                + ", and one character more is refused where it comes in",
            ),
            id=kind,
        )
        for kind, limit in (("display", 200), ("producer", 200), ("job", 200), ("test", 250))
    ],
)
def test_a_name_is_whole_at_its_limit_and_refused_over_it(project: Project, kind: str, limit: int):
    """The limit is 200 for a producer, a CI job and a display name, 250 for a test node ID; over it, nothing is reported."""
    run, shown = _shown(project, kind, limit)
    assert run.code == 0, run.err
    if kind == "test":
        # A heading may shorten a long test name to stay on one line (006-09), so look only for its start
        assert shown(run.out).startswith("#### Test `" + "x" * 100)
    else:
        assert shown(run.out) == "x" * limit
    over, _ = _shown(project, kind, limit + 1)
    assert "x" * (limit + 1) not in over.out
    if kind == "display":
        # `--job-names` is a command-line input, so a name over the limit is a usage error before any report
        assert over.code == 2 and f"the name for 8 is {limit + 1} characters; the limit is {limit}" in over.err
    else:
        # `report` always exits 0 (006-05), so the refusal shows as a problem; `verify` fails on it
        assert over.code == 0 and f"is longer than {limit} characters" in over.out
        assert project.speccheck("verify", "u.jsonl").code == 1


@pytest.mark.covers(
    "SPC-REQ-006-09",
    "a report of a results file whose longest test node ID is 250 characters lists that ID's problem line without cutting its fix",
)
def test_a_longest_test_id_keeps_its_problem_line_whole(project: Project):
    """A failing result with a 250-character ID: the Problems line still ends with the hint on what to do."""
    project.spec("- T-REQ-001-01: One.")
    name = "t.py::" + "x" * 244
    project.results("u.jsonl", "unit", [(name, ["T-REQ-001-01"], "deselected")])
    text = project.speccheck("report", "u.jsonl").out
    problems = text.split("## Problems", 1)[1].split("## Specs", 1)[0]
    assert "x" * 244 in problems and "…" not in problems
    assert "drop the -k/-m filter" in problems  # `code()` keeps no backtick, so the hint's are gone


@pytest.mark.covers(
    "SPC-REQ-006-04",
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


@pytest.mark.covers(
    "SPC-REQ-006-04",
    "two results files from different commits and runs list both 12-character commits and both run attempts, in order, and never a full 40-character hash",
)
def test_the_inputs_list_every_commit_and_run(project: Project):
    """Sorted, shortened to 12 characters, and one link per run attempt."""
    project.spec("- T-REQ-001-01: One.")
    first = {**CI, "sha": "b" * 40, "run_url": "https://github.com/o/r/actions/runs/5/attempts/1"}
    second = {**CI, "sha": "a" * 40, "run_url": "https://github.com/o/r/actions/runs/7/attempts/2"}
    project.results("a.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=first)
    project.results("b.jsonl", "unit", [("t", ["T-REQ-001-01"], "failed")], ci=second)
    inputs = project.speccheck("report", "a.jsonl", "b.jsonl", env=ENV).out.split("## Inputs", 1)[1]
    assert "- Commit: aaaaaaaaaaaa, bbbbbbbbbbbb\n" in inputs
    assert "a" * 13 not in inputs and "b" * 13 not in inputs
    assert (
        "- Runs: [5/attempts/1](https://github.com/o/r/actions/runs/5/attempts/1), "
        "[7/attempts/2](https://github.com/o/r/actions/runs/7/attempts/2)\n"
    ) in inputs


@pytest.mark.covers(
    "SPC-REQ-006-04",
    "a report of a results file written outside CI says the commit is unknown and there are no runs, and lists no missing producers when all reported",
)
def test_the_inputs_outside_ci(project: Project):
    """No commit or run to name, and no `Producers missing` line when nobody is missing."""
    project.spec("- T-REQ-001-01: One.")
    project.results("a.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    inputs = project.speccheck("report", "a.jsonl").out.split("## Inputs", 1)[1]
    assert inputs.strip().splitlines() == [
        "- Commit: unknown (not run in CI)",
        "- Runs: none",
        "- Producers reported: unit",
    ]


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(
            "failed",
            marks=pytest.mark.covers("SPC-REQ-006-05", "a failing requirement leaves report exiting 0 and verify 1"),
            id="failed",
        ),
        pytest.param(
            "not-run",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05",
                "a requirement a missing producer could prove, under --complete, leaves report exiting 0 and verify 1",
            ),
            id="not-run",
        ),
        pytest.param(
            "skipped",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05", "a requirement whose only result is skipped leaves report exiting 0 and verify 1"
            ),
            id="skipped",
        ),
        pytest.param(
            "error",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05", "a requirement whose only result is an error leaves report exiting 0 and verify 1"
            ),
            id="error",
        ),
        pytest.param(
            "bad-spec",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05", "a spec with a malformed bullet leaves report exiting 0 and verify 1"
            ),
            id="bad-spec",
        ),
        pytest.param(
            "bad-results",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05", "a results file that is not JSON leaves report exiting 0 and verify 1"
            ),
            id="bad-results",
        ),
    ],
)
def test_report_exits_0_whatever_makes_verify_fail(project: Project, setup: str):
    """Each kind of problem fails `verify` and still gives a report, starting with its title, and exit 0."""
    flags: list[str] = []
    project.spec("- T-REQ-001-01: One.")
    outcome = {"failed": "failed", "skipped": "skipped", "error": "error"}.get(setup, "passed")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], outcome)])
    if setup == "not-run":
        project.write(
            "speccheck.toml",
            CONFIG_WITH_NIGHTLY,
        )
        project.write("specs/001-thing.md", spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two."))
        flags = ["--complete"]
    if setup == "bad-spec":
        project.spec("- T-REQ-001-01: One.\n* T-REQ-001-02: A bad bullet.")
    if setup == "bad-results":
        project.write("r.jsonl", "not json\n")
    assert project.speccheck("verify", "r.jsonl", *flags).code == 1
    run = project.speccheck("report", "r.jsonl", *flags, "--output", "r.md")
    assert run.code == 0
    assert (project.root / "r.md").read_text().startswith("# speccheck requirements\n")


@pytest.mark.covers(
    "SPC-REQ-006-06",
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
    "file",
    [
        pytest.param(
            file,
            marks=pytest.mark.covers(
                "SPC-REQ-006-06",
                f"a test file named {file!r}, with dots inside a segment but no `..` segment, is linked at the commit",
            ),
            id=f"file-{n}",
        )
        for n, file in enumerate(["tests/a..b.py", "tests/..a.py", "tests/a.b.c.py", "tests/..."])
    ],
)
def test_dots_inside_a_name_still_link(project: Project, file: str):
    """Only a whole `..` segment climbs out of the repository, so these paths are plain."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", "root": "proj"}
    line = {
        "test": "x::test_a",
        "file": file,
        "line": 3,
        "covers": [{"id": "T-REQ-001-01", "how": "h"}],
        "outcome": "passed",
    }
    project.write("u.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    env = {**ENV, "GITHUB_SHA": SHA, "GITHUB_WORKSPACE": str(project.root.parent)}
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert f"#### Test [`test_a`](https://github.com/o/r/blob/{SHA}/proj/{file}#L3) in `proj/{file}`" in text


@pytest.mark.covers(
    "SPC-REQ-006-06",
    "a result with no line number links its test file at the commit with no #L anchor, where one with line 12 gets #L12",
)
def test_a_test_with_no_line_links_the_file_without_an_anchor(project: Project):
    """An unknown line is not line 0: the link opens the file, not `#L0`."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", "root": "proj"}
    with_line = {"test": "t.py::test_a", "file": "tests/t.py", "line": 12, "outcome": "passed"}
    without_line = {"test": "t.py::test_b", "file": "tests/t.py", "outcome": "passed"}
    lines = [
        {**result, "covers": [{"id": "T-REQ-001-01", "how": f"{result['test']} proves it"}]}
        for result in (with_line, without_line)
    ]
    project.write("u.jsonl", "\n".join(json.dumps(line) for line in [header, *lines]) + "\n")
    env = {**ENV, "GITHUB_SHA": SHA, "GITHUB_WORKSPACE": str(project.root.parent)}
    text = project.speccheck("report", "u.jsonl", env=env).out
    blob = f"https://github.com/o/r/blob/{SHA}/proj/tests/t.py"
    assert f"#### Test [`test_a`]({blob}#L12) in `proj/tests/t.py`" in text
    assert f"#### Test [`test_b`]({blob}) in `proj/tests/t.py`" in text
    assert "#L0" not in text


@pytest.mark.parametrize(
    ("change", "env"),
    [
        pytest.param(
            {"root": "proj", "file": "../outside.py"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-06", "a test file path that climbs out with .. is shown but not linked"
            ),
            id="dot-dot",
        ),
        *(
            pytest.param(
                {"root": "proj", "file": path},
                {**ENV, "GITHUB_SHA": SHA},
                marks=pytest.mark.covers("SPC-REQ-006-06", f"a test file path {path!r} is shown but not linked"),
                id=f"path-{n}",
            )
            for n, path in enumerate(
                ["a b.py", "a/../b.py", "/abs.py", "é.py", "a%20b.py", "a(1).py", "a\\b.py", "a//b.py", "a/", "a;b.py"]
            )
        ),
        pytest.param(
            {"root": "proj", "file": "tests/t.py?x=1#frag"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-06", "a test file path holding URL characters like ? and # is shown but not linked"
            ),
            id="url-characters",
        ),
        pytest.param(
            {"root": "../outside", "file": "tests/t.py"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-06", "a results file whose root climbs out of the repository with .. gets no test link"
            ),
            id="root-dot-dot",
        ),
        pytest.param(
            {"root": "my project", "file": "tests/t.py"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers("SPC-REQ-006-06", "a results file whose root has a space in it gets no test link"),
            id="root-space",
        ),
        pytest.param(
            {"root": None, "file": "tests/t.py"},
            {**ENV, "GITHUB_SHA": SHA},
            marks=pytest.mark.covers(
                "SPC-REQ-006-06", "a results file that doesn't know its repository root gets no test link"
            ),
            id="no-root",
        ),
        pytest.param(
            {"root": "proj", "file": "tests/t.py"},
            {**ENV, "GITHUB_SHA": "not-a-sha"},
            marks=pytest.mark.covers(
                "SPC-REQ-006-06", "a GITHUB_SHA that isn't a full commit hash links no spec or test line"
            ),
            id="bad-sha",
        ),
        pytest.param(
            {"root": "proj", "file": "tests/t.py"},
            {},
            marks=pytest.mark.covers("SPC-REQ-006-06", "outside CI no spec or test line is linked"),
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


@pytest.mark.parametrize(
    "folder",
    [
        pytest.param(
            folder,
            marks=pytest.mark.covers(
                "SPC-REQ-006-06",
                f"a spec in a folder named {folder!r} is reported with its requirement, but with no spec line link",
            ),
            id=f"folder-{n}",
        )
        for n, folder in enumerate(["my specs", "specs(1)", "spécs", "100%"])
    ],
)
def test_a_spec_path_needs_to_be_plain_to_link(project: Project, folder: str):
    """The spec file is valid and loaded, but its path isn't plain, so the requirement's section links nothing."""
    project.write("speccheck.toml", CONFIG.replace('specs = "specs"', f'specs = "{folder}"'))
    project.write(f"{folder}/000-index.md", INDEX)
    project.write(f"{folder}/001-thing.md", spec("- T-REQ-001-01: One."))
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    env = {**ENV, "GITHUB_SHA": SHA, "GITHUB_WORKSPACE": str(project.root.parent)}
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert "1 requirement" in text and "T-REQ-001-01" in text, text
    assert "/blob/" not in text and "\nIn [" not in text


@pytest.mark.covers(
    "SPC-REQ-006-06",
    "with GITHUB_WORKSPACE set to a sub folder that doesn't hold the specs, a requirement gets no spec line link",
)
def test_a_spec_outside_the_workspace_is_not_linked(project: Project):
    """The spec has no path from the repository's root, so nothing is linked."""
    project.spec("- T-REQ-001-01: One.")
    header = '{"schema": "speccheck-results/1", "producer": "unit"}\n'
    line = {"test": "t", "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    project.write("u.jsonl", header + json.dumps(line) + "\n")
    (project.root / "elsewhere").mkdir()
    env = {**ENV, "GITHUB_SHA": SHA, "GITHUB_WORKSPACE": str(project.root / "elsewhere")}
    text = project.speccheck("report", "u.jsonl", env=env).out
    assert "/blob/" not in text and "\nIn [" not in text


@pytest.mark.parametrize(
    ("outcome", "mark", "how"),
    [
        pytest.param(outcome, mark, how, marks=pytest.mark.covers("SPC-REQ-006-02", how), id=outcome)
        for outcome, mark, how in [
            (
                "failed",
                "❌",
                "a requirement whose only result failed gets the line '❌ failed in' followed by the linked job",
            ),
            (
                "error",
                "❌",
                "a requirement whose only result is an error gets the line '❌ error in' followed by the linked job",
            ),
            (
                "xfailed",
                "❌",
                "a requirement whose only result is an expected failure gets '❌ xfailed in' and the linked job, not a pass mark",
            ),
            (
                "xpassed",
                "❌",
                "a requirement whose only result is an unexpected pass gets '❌ xpassed in' and the linked job, not a pass mark",
            ),
            (
                "deselected",
                "❌",
                "a requirement whose only result was deselected gets '❌ deselected in' and the linked job",
            ),
            (
                "collected",
                "☑",
                "a requirement whose only result was collected but never run gets the ballot mark '☑ collected in' and the linked job",
            ),
        ]
    ],
)
def test_each_outcome_has_its_own_result_line(project: Project, outcome: str, mark: str, how: str):
    """One result of each other outcome: the mark the report gives it, its outcome word, and the job linked."""
    project.spec("- T-REQ-001-01: One.")
    project.results("a.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], outcome)], ci=CI)
    text = project.speccheck("report", "a.jsonl", env=ENV).out
    lines = [line for line in text.splitlines() if line.startswith(f"- {mark} {outcome} in ")]
    assert lines == [f"- {mark} {outcome} in [unit](https://github.com/o/r/actions/runs/7/job/8)"]


@pytest.mark.covers(
    "SPC-REQ-006-02",
    "one claim with a result of each of the eight outcomes, given in the reverse of the report's own order, comes out in that OUTCOMES order with failed first and passed last",
)
def test_result_lines_are_listed_worst_first(project: Project):
    """The order is the report's named OUTCOMES constant, whatever order the results files were given in."""
    project.spec("- T-REQ-001-01: One.")
    names = {}
    files = []
    for n, outcome in enumerate(reversed(OUTCOMES)):
        job = {**CI, "job_id": 10 + n, "job_url": f"https://github.com/o/r/actions/runs/7/job/{10 + n}"}
        names[str(10 + n)] = f"job {outcome}"
        project.results(f"{outcome}.jsonl", "unit", [("tests/t.py::test_a", ["T-REQ-001-01"], outcome)], ci=job)
        files.append(f"{outcome}.jsonl")
    project.write("names.json", json.dumps(names))
    text = project.speccheck("report", *files, "--job-names", "names.json", env=ENV).out
    shown = re.findall(r"^- \S+ (\w+) in \[job \w+\]\(", text, re.M)
    assert shown == list(OUTCOMES)
    assert shown[0] == "failed" and shown[-1] == "passed"


def hostile_results(
    project: Project,
    *,
    test: str = "t",
    file: str | None = None,
    claim: str = "T-REQ-001-01",
    kind: str | None = None,
    producer: str = "unit",
    ci: dict | None = None,
) -> None:
    """Write `u.jsonl`: one passing result for `claim` from `producer`, with the given test name, file, kind and CI block."""
    header: dict = {"schema": "speccheck-results/1", "producer": producer}
    if ci is not None:
        header["ci"] = ci
    line: dict = {"test": test, "covers": [{"id": claim, "how": "h"}], "outcome": "passed"}
    if file is not None:
        line["file"] = file
    if kind is not None:
        line["kind"] = kind
    project.write("u.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")


def payload_claim(place: str, payload: str) -> pytest.MarkDecorator:
    """The 006-03 claim for one payload put in `place`; its explanation names both."""
    return pytest.mark.covers(
        "SPC-REQ-006-03",
        f"a results file whose {place} is {payload!r} renders through CommonMark and GitHub autolinks "
        "with the same elements as one whose is plain words",
    )


@pytest.mark.parametrize(
    "payload",
    [pytest.param(payload, marks=payload_claim("test file path", payload), id=payload) for payload in PAYLOADS],
)
def test_a_test_file_path_cant_add_markdown(project: Project, payload: str):
    """The `file` of a result is shown in the Test heading, so a results file chooses what that text is."""
    project.spec("- T-REQ-001-01: One.")
    hostile_results(project, test="tests/t.py::test_a", file=payload)
    hostile = project.speccheck("report", "u.jsonl", env=ENV).out
    hostile_results(project, test="tests/t.py::test_a", file="tests/t.py")
    plain = project.speccheck("report", "u.jsonl", env=ENV).out
    assert elements(plain), "the plain report has elements of its own (headings, anchors), so the check can fail"
    assert "#### Test " in hostile
    assert elements(hostile) == elements(plain), hostile


@pytest.mark.parametrize(
    ("root", "file"),
    [
        pytest.param(
            None,
            "tests/" + "d" * 394,
            marks=pytest.mark.covers(
                "SPC-REQ-006-09",
                "a results file whose file path is 400 characters gets a Test heading showing at most 150 characters of it, the last an ellipsis",
            ),
            id="long-file",
        ),
        pytest.param(
            "r" * 300,
            "tests/t.py",
            marks=pytest.mark.covers(
                "SPC-REQ-006-09",
                "a results file whose root is 300 characters gets a Test heading showing at most 150 characters of root and file together, the last an ellipsis",
            ),
            id="long-root",
        ),
    ],
)
def test_a_long_path_is_shortened_in_the_heading(project: Project, root: str | None, file: str):
    """A heading may shorten a long test name or path to stay on one line (006-09); the full text is in `--json`."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit", "root": root}
    line = {"test": "t.py::test_a", "file": file, "covers": [{"id": "T-REQ-001-01", "how": "h"}], "outcome": "passed"}
    project.write("u.jsonl", json.dumps(header) + "\n" + json.dumps(line) + "\n")
    text = project.speccheck("report", "u.jsonl").out
    heading = next(x for x in text.splitlines() if x.startswith("#### Test "))
    shown = heading.split(" in `", 1)[1].rstrip("`")
    assert len(shown) == 150 and shown.endswith("…")
    body = project.speccheck("report", "u.jsonl", "--json").json()
    assert body["requirements"][0]["evidence"][0]["file"] == file


@pytest.mark.parametrize(
    "payload",
    [pytest.param(payload, marks=payload_claim("CI job name", payload), id=payload) for payload in PAYLOADS],
)
def test_a_ci_job_name_cant_add_markdown(ci_project: Project, payload: str):
    """The name of a CI job heads its own subsection (`#### Job`), and the results file chooses it."""
    hostile_results(ci_project, test=payload, kind="ci", producer="publish")
    hostile = ci_project.speccheck("report", "u.jsonl", env=ENV).out
    hostile_results(ci_project, test="publish", kind="ci", producer="publish")
    plain = ci_project.speccheck("report", "u.jsonl", env=ENV).out
    assert elements(plain), "the plain report has elements of its own (headings, anchors), so the check can fail"
    assert "#### Job " in hostile
    assert elements(hostile) == elements(plain), hostile


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(payload, marks=payload_claim("test name and claimed ID", payload), id=payload)
        for payload in PAYLOADS
    ],
)
def test_a_problem_line_cant_add_markdown(project: Project, payload: str):
    """A result claiming an ID that isn't in any spec is a problem naming its test and the ID, listed in the report."""
    project.spec("- T-REQ-001-01: One.")
    hostile_results(project, test=payload, claim=payload)
    hostile = project.speccheck("report", "u.jsonl").out
    hostile_results(project, test="t", claim="T-REQ-009-09")
    plain = project.speccheck("report", "u.jsonl").out
    # The unknown ID is one problem, and the requirement nobody validly claims is the other
    assert "## Problems (2)" in plain and "## Problems (2)" in hostile
    assert elements(plain), "the plain report has elements of its own (headings, anchors), so the check can fail"
    assert elements(hostile) == elements(plain), hostile


@pytest.mark.parametrize(
    "payload",
    [pytest.param(payload, marks=payload_claim("commit and run URL", payload), id=payload) for payload in PAYLOADS],
)
def test_the_commit_and_run_in_the_inputs_cant_add_markdown(project: Project, payload: str):
    """The Inputs section shows the first 12 characters of `ci.sha`; a `run_url` that isn't this run's is dropped."""
    project.spec("- T-REQ-001-01: One.")
    hostile_results(project, ci={"sha": payload, "run_url": payload})
    hostile = project.speccheck("report", "u.jsonl", env=ENV).out
    hostile_results(project, ci={"sha": "e" * 40})
    plain = project.speccheck("report", "u.jsonl", env=ENV).out
    assert "- Runs: none" in hostile
    assert elements(plain), "the plain report has elements of its own (headings, anchors), so the check can fail"
    assert elements(hostile) == elements(plain), hostile


@pytest.mark.covers(
    "SPC-REQ-006-04",
    "a results file with a run URL, reported on where no GITHUB_ variable is set, says 'Runs: none' and still gives its 12-character commit",
)
def test_a_run_url_is_only_listed_for_this_runs_repository(project: Project):
    """Without a server and repository from the environment, no run URL is one of this run's, so none is listed or linked."""
    project.spec("- T-REQ-001-01: One.")
    project.results("a.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=CI)
    inputs = project.speccheck("report", "a.jsonl", env={}).out.split("## Inputs", 1)[1]
    assert inputs.strip().splitlines() == [
        "- Commit: dddddddddddd",
        "- Runs: none",
        "- Producers reported: unit",
    ]
    assert "github.com" not in inputs


@pytest.mark.covers(
    "SPC-REQ-006-04",
    "in a full GitHub Actions job environment, the Inputs section is exactly the 12-character commit, the linked run attempt and the reporting producer",
)
def test_the_inputs_in_a_ci_job(project: Project):
    """The same three lines, whole, when the report is written by a CI job."""
    project.spec("- T-REQ-001-01: One.")
    project.results("a.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")], ci=CI)
    env = {**JOB, "GITHUB_SHA": "d" * 40, "GITHUB_WORKSPACE": str(project.root)}
    inputs = project.speccheck("report", "a.jsonl", env=env).out.split("## Inputs", 1)[1]
    assert inputs.strip().splitlines() == [
        "- Commit: dddddddddddd",
        "- Runs: [7/attempts/2](https://github.com/o/r/actions/runs/7/attempts/2)",
        "- Producers reported: unit",
    ]


@pytest.mark.covers(
    "SPC-REQ-006-05",
    "a spec of which one requirement no test claims leaves report exiting 0 where verify exits 1, with the requirement reported unclaimed",
)
def test_report_exits_0_for_an_unclaimed_requirement(project: Project):
    """Nothing claims T-REQ-001-02, so `verify` fails on it; `report` still writes its report and exits 0."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.")
    project.results("r.jsonl", "unit", [("t", ["T-REQ-001-01"], "passed")])
    assert project.speccheck("verify", "r.jsonl").code == 1
    run = project.speccheck("report", "r.jsonl", "--output", "r.md")
    assert run.code == 0
    assert "### T-REQ-001-02 ❌ unclaimed" in (project.root / "r.md").read_text()


@pytest.mark.parametrize(
    "where",
    [
        pytest.param(
            "stdout",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05",
                "a failing and an unclaimed requirement leave report exiting 0 when it prints the report to stdout with no --output",
            ),
            id="stdout",
        ),
        pytest.param(
            "json",
            marks=pytest.mark.covers(
                "SPC-REQ-006-05",
                "a failing and an unclaimed requirement leave report --json exiting 0 and printing the report command's object",
            ),
            id="json",
        ),
    ],
)
def test_report_exits_0_to_stdout_and_as_json(reported: Project, where: str):
    """`verify` fails on the same results; `report` prints in the other two ways it can and still exits 0."""
    assert reported.speccheck("verify", "unit.jsonl").code == 1
    if where == "stdout":
        run = reported.speccheck("report", "unit.jsonl")
        assert run.code == 0 and run.out.startswith("# speccheck requirements\n")
    else:
        run = reported.speccheck("report", "unit.jsonl", "--json")
        assert run.code == 0
        body = run.json()
        assert body["command"] == "report"
        assert {r["id"]: r["status"] for r in body["requirements"]} == {
            "T-REQ-001-01": "passed",
            "T-REQ-001-02": "failed",
            "T-REQ-001-03": "unclaimed",
        }


@pytest.mark.covers(
    "SPC-REQ-006-08",
    "one test name claiming a requirement in two results with different explanations gets two subsections, each with its own How",
)
def test_one_test_with_two_hows_gets_two_subsections(project: Project):
    """Claims are grouped by kind, test and how, so the same test name with another how is another subsection."""
    project.spec("- T-REQ-001-01: One.")
    header = {"schema": "speccheck-results/1", "producer": "unit"}
    lines = [
        {
            "test": "tests/t.py::test_a",
            "file": "tests/t.py",
            "line": line,
            "covers": [{"id": "T-REQ-001-01", "how": how}],
            "outcome": "passed",
        }
        for line, how in ((3, "checks the first thing"), (9, "checks the second thing"))
    ]
    project.write("u.jsonl", "\n".join(json.dumps(x) for x in [header, *lines]) + "\n")
    text = project.speccheck("report", "u.jsonl").out
    assert re.findall(r"^#### (.+)$", text, re.M) == ["Test `test_a` in `tests/t.py`"] * 2
    assert re.findall(r"^\*\*How:\*\* (.+)$", text, re.M) == ["checks the first thing", "checks the second thing"]
