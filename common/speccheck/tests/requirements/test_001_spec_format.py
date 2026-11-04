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

"""specs/001-spec-format.md, through `speccheck lint` and `speccheck check`."""

from __future__ import annotations

import pytest

from tests.requirements.conftest import INDEX, Project, spec


@pytest.mark.covers(
    "SPC-REQ-001-01",
    "lint reports a `Notes.md` in the folder as misnamed, and a spec titled `# 2 -` instead of `# 002 -` at line 1",
)
def test_file_names_and_titles(project: Project):
    """A misnamed file and a title without the number are each reported where they are."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("")
    project.write("specs/002-other.md", spec("", number="002").replace("# 002 -", "# 2 -"))
    project.write("specs/Notes.md", "x")
    run = project.speccheck("lint")
    assert run.code == 1
    assert "specs/Notes.md: a spec file must be named NNN-short-name.md" in run.err
    assert "specs/002-other.md:1: the first line must be the title, `# 002 - <name>`" in run.err


@pytest.mark.covers(
    "SPC-REQ-001-01",
    "lint reports a title with no dash, one with a dash but no name, a title that is not on line 1, and three misnamed files, each at its line or path",
)
def test_only_nnn_dash_name_is_a_title(project: Project):
    """`# NNN - Name` is the one title form, on the first line; file names are exactly `NNN-short-name.md`."""
    title_error = "specs/001-thing.md:1: the first line must be the title, `# 001 - <name>`"
    for first in ("# 001 Thing", "# 001 -", "# 001 -   ", "# 001-Thing", "", "<!-- c -->\n# 001 - Thing"):
        project.write("specs/001-thing.md", f"{first}\n\nstatus: draft\n")
        run = project.speccheck("lint")
        assert run.code == 1 and title_error in run.err, first
    project.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: draft\n")
    assert project.speccheck("lint").code == 0
    # `002-Other.md`, not a capitalised twin of 001-thing.md: that would be the same file on a case-insensitive disk
    for name in ("1-a.md", "002-Other.md", "001.md"):
        project.write(f"specs/{name}", "x")
        run = project.speccheck("lint")
        assert run.code == 1 and f"specs/{name}: a spec file must be named NNN-short-name.md" in run.err, name
        (project.root / "specs" / name).unlink()


@pytest.mark.covers(
    "SPC-REQ-001-02",
    "an index that names 002-other.md only in prose fails lint with the link to add, a missing index fails, and require-index = false turns the check off",
)
def test_the_index_must_link_every_spec(project: Project):
    """A spec the index only mentions in prose is reported; a link in any markdown form lists it."""
    project.write("specs/000-index.md", "# Index\n\nSpec 002 is 002-other.md.\n\n| 001 | [x](./001-thing.md#a) |\n")
    project.spec("")
    project.spec("", number="002", name="002-other.md")
    run = project.speccheck("lint")
    assert run.code == 1
    assert run.err.splitlines()[0] == (
        "specs/000-index.md: the index doesn't link 002-other.md; list it as `[002](002-other.md)`"
    )
    (project.root / "specs" / "000-index.md").unlink()
    assert "needs a 000-index.md" in project.speccheck("lint").err
    project.write("speccheck.toml", 'specs = "specs"\nid-prefix = "T"\nrequire-index = false\n')
    assert project.speccheck("lint").code == 0


@pytest.mark.covers(
    "SPC-REQ-001-02",
    "with require-index = false and an index that exists but leaves out spec 002, lint is clean, and with it on the same folder exits 1",
)
def test_require_index_false_turns_off_the_link_check_not_just_the_missing_index(project: Project):
    """The index is there and incomplete: the config alone decides whether that is a problem."""
    project.spec("")
    project.spec("", number="002", name="002-other.md")
    assert project.speccheck("lint").code == 1
    project.write("speccheck.toml", 'specs = "specs"\nid-prefix = "T"\nrequire-index = false\n')
    run = project.speccheck("lint")
    assert run.code == 0 and "doesn't link" not in run.err


@pytest.mark.covers(
    "SPC-REQ-001-02",
    "a folder with no 000-index.md exits 1 from lint, saying the folder needs one that links every spec",
)
def test_a_missing_index_is_exit_1(project: Project):
    """Exit 1, not only the message."""
    project.spec("")
    (project.root / "specs" / "000-index.md").unlink()
    run = project.speccheck("lint")
    assert run.code == 1
    assert "specs/000-index.md: the spec folder needs a 000-index.md that links every spec" in run.err


@pytest.mark.parametrize(
    "link",
    [
        pytest.param(
            "[001](001-thing.md)",
            marks=pytest.mark.covers("SPC-REQ-001-02", "a plain markdown link to the spec lists it"),
            id="plain",
        ),
        pytest.param(
            "[001](./001-thing.md)",
            marks=pytest.mark.covers("SPC-REQ-001-02", "a markdown link with a ./ prefix lists the spec"),
            id="dot-slash",
        ),
        pytest.param(
            "[001](001-thing.md#requirements)",
            marks=pytest.mark.covers("SPC-REQ-001-02", "a markdown link with an anchor lists the spec"),
            id="anchor",
        ),
    ],
)
def test_each_markdown_link_form_lists_a_spec(project: Project, link: str):
    """Any link to the file counts."""
    project.write("specs/000-index.md", f"# Index\n\n{link}\n")
    project.spec("")
    assert project.speccheck("lint").code == 0


@pytest.mark.parametrize(
    "prose",
    [
        pytest.param(
            "001-thing.md is the first spec.",
            marks=pytest.mark.covers("SPC-REQ-001-02", "the spec's file name written in prose does not list it"),
            id="file-name",
        ),
        pytest.param(
            "See `001-thing.md` and spec 001, the Thing.",
            marks=pytest.mark.covers("SPC-REQ-001-02", "the number and name in prose and a code span do not list it"),
            id="code-span-and-number",
        ),
        pytest.param(
            "[001](other-001-thing.md)",
            marks=pytest.mark.covers(
                "SPC-REQ-001-02", "a link to a file whose name merely ends with the spec's does not list it"
            ),
            id="longer-name",
        ),
    ],
)
def test_prose_does_not_list_a_spec(project: Project, prose: str):
    """Only a markdown link to this exact file counts."""
    project.write("specs/000-index.md", f"# Index\n\n{prose}\n")
    project.spec("")
    run = project.speccheck("lint")
    assert run.code == 1 and "the index doesn't link 001-thing.md" in run.err


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(
            status,
            marks=pytest.mark.covers(
                "SPC-REQ-001-03", f"a spec with status {status} and one unimplemented requirement lints clean"
            ),
            id=status,
        )
        for status in ("draft", "implemented")
    ],
)
def test_each_status_value_is_accepted(project: Project, status: str):
    """Both values are valid."""
    project.spec("- T-REQ-001-01: One. (unimplemented: later)", status=status)
    run = project.speccheck("lint")
    assert run.code == 0 and run.err == "", run.err


@pytest.mark.covers(
    "SPC-REQ-001-03",
    "a draft spec with an empty Requirements section lints clean, exit 0 and no output",
)
def test_only_an_implemented_spec_needs_a_requirement(project: Project):
    """The "at least one requirement" rule is for `implemented` alone."""
    project.spec("", status="draft")
    run = project.speccheck("lint", "--json")
    assert run.code == 0 and run.json()["problems"] == []
    assert project.speccheck("lint").err == ""


@pytest.mark.covers(
    "SPC-REQ-001-03",
    "a status line placed under ## Requirements does not count, so lint reports the status missing",
)
def test_a_status_below_the_first_section_does_not_count(project: Project):
    """The line must be above the first `##`."""
    project.write(
        "specs/001-thing.md",
        "# 001 - Thing\n\n## Requirements\n\nstatus: draft\n\n- T-REQ-001-01: One. (unimplemented: later)\n",
    )
    run = project.speccheck("lint")
    assert run.code == 1 and "specs/001-thing.md: missing the `status:` line" in run.err


@pytest.mark.covers(
    "SPC-REQ-001-03",
    "a draft spec's unclaimed requirement is reported by check as unclaimed, as an implemented spec's is",
)
def test_a_draft_specs_requirements_are_checked_like_an_implemented_ones(project: Project):
    """The status doesn't exempt a requirement from needing a claim."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: Draft one.", status="draft")
    project.spec("- T-REQ-002-01: Implemented one.", number="002", name="002-other.md", status="implemented")
    run = project.speccheck("check", "--json")
    statuses = {r["id"]: r["status"] for r in run.json()["requirements"]}
    assert statuses == {"T-REQ-001-01": "unclaimed", "T-REQ-002-01": "unclaimed"}
    assert run.code == 1


@pytest.mark.covers(
    "SPC-REQ-001-03",
    "lint reports an unknown status value and a second status line each at its line, and a missing status line and an implemented spec with no requirements each with no line",
)
def test_the_status_line(project: Project):
    """Missing, unknown, repeated, and implemented with nothing in it, are all problems."""
    project.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: done\nstatus: draft\n")
    run = project.speccheck("lint")
    assert "specs/001-thing.md:3: status must be one of draft, implemented" in run.err
    assert "specs/001-thing.md:4: a second `status:` line; a spec has one" in run.err
    project.spec("", status="implemented")
    assert "specs/001-thing.md: an implemented spec needs at least one requirement" in project.speccheck("lint").err
    project.write("specs/001-thing.md", "# 001 - Thing\n")
    assert "specs/001-thing.md: missing the `status:` line" in project.speccheck("lint").err


@pytest.mark.covers(
    "SPC-REQ-001-04",
    "star, bold, nested and unprefixed bullets each get the form to write, and T-REQ-002-01 in spec 001 is told which spec it belongs in",
)
def test_bullets_in_any_other_form_are_reported(project: Project):
    """Star, bold, nested, unprefixed and wrongly numbered bullets each get a problem with the form to write."""
    project.spec(
        "- T-REQ-001-01: Good. (unimplemented: later)\n* T-REQ-001-02: Star.\n- **T-REQ-001-03**: Bold.\n"
        "  - T-REQ-001-04: Nested.\n- REQ-001-05: No prefix.\n- T-REQ-002-01: Wrong spec."
    )
    run = project.speccheck("lint")
    assert run.err.count("a bullet must read `- T-REQ-NNN-XX: text` (or BEH)") == 4
    assert "T-REQ-002-01 belongs in spec 002" in run.err
    assert run.err.splitlines()[-1] == "speccheck lint: 1 specs, 2 requirements; 5 problems"


@pytest.mark.covers(
    "SPC-REQ-001-04",
    "with --json, a bullet numbered for another spec is one `bullet-wrong-spec` problem at its own line, naming the spec it belongs in",
)
def test_a_wrong_spec_number_is_one_coded_problem_at_its_line(project: Project):
    """The ID of spec 002 on line 8 of spec 001: the code, the line and the message are all pinned."""
    project.spec("- T-REQ-001-01: Good. (unimplemented: later)\n- T-REQ-002-01: Wrong spec. (unimplemented: later)")
    run = project.speccheck("lint", "--json")
    [problem] = run.json()["problems"]
    assert run.code == 1
    assert (problem["code"], problem["line"]) == ("bullet-wrong-spec", 8)
    assert problem["message"] == "T-REQ-002-01 belongs in spec 002"


@pytest.mark.parametrize(
    "bullet",
    [
        pytest.param(
            "+ T-REQ-001-02: Plus.",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04", "a `+` list marker is reported as a malformed bullet at its own line"
            ),
            id="plus",
        ),
        pytest.param(
            "- T-REQ-001-02:",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04",
                "a well-formed ID followed by a colon and no text is reported as malformed at its line",
            ),
            id="empty-text",
        ),
    ],
)
def test_a_plus_bullet_and_an_empty_one_are_malformed(project: Project, bullet: str):
    """Both are close to `- T-REQ-NNN-XX: text` but are not it, so each is a coded problem on line 8."""
    project.spec(f"- T-REQ-001-01: Good. (unimplemented: later)\n{bullet}")
    run = project.speccheck("lint", "--json")
    [problem] = run.json()["problems"]
    assert (problem["code"], problem["line"]) == ("bullet-malformed", 8)


@pytest.mark.covers(
    "SPC-REQ-001-04",
    "a T-BEH-001-01 bullet is a valid requirement, so lint is clean and check lists it",
)
def test_a_beh_bullet_is_a_requirement(project: Project):
    """BEH is the other form, beside REQ."""
    project.spec("- T-BEH-001-01: It behaves. (unimplemented: later)")
    run = project.speccheck("check", "--json")
    assert run.json()["problems"] == []
    assert [r["id"] for r in run.json()["requirements"]] == ["T-BEH-001-01"]
    assert project.speccheck("lint").code == 0


@pytest.mark.parametrize(
    ("bullet", "detail"),
    [
        pytest.param(
            "* T-REQ-001-02: Star.",
            "found `*` where `-` belongs: `* T-REQ-001-02: Star.`",
            marks=pytest.mark.covers("SPC-REQ-001-04", "a star bullet is reported at its own line saying `*` is wrong"),
            id="star",
        ),
        pytest.param(
            "- **T-REQ-001-02**: Bold.",
            "found the ID wrapped in markup: `- **T-REQ-001-02**: Bold.`",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04", "a bold-wrapped ID is reported at its own line saying the ID is in markup"
            ),
            id="bold",
        ),
        pytest.param(
            "  - T-REQ-001-02: Nested.",
            "found an indented bullet: `- T-REQ-001-02: Nested.`",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04", "a nested bullet is reported at its own line saying it is indented"
            ),
            id="nested",
        ),
        pytest.param(
            "- REQ-001-02: No prefix.",
            "found an ID without the `T-` prefix: `- REQ-001-02: No prefix.`",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04",
                "an ID without the project prefix is reported at its own line saying the prefix is missing",
            ),
            id="unprefixed",
        ),
        pytest.param(
            "- T-REQ-001-02 No colon.",
            "found no `: ` and text after the ID: `- T-REQ-001-02 No colon.`",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04", "a bullet whose ID has no colon and text after it is reported at its own line"
            ),
            id="no-colon",
        ),
        pytest.param(
            "- T-REQ-01-02: Short number.",
            "found an ID that is not NNN-XX: `- T-REQ-01-02: Short number.`",
            marks=pytest.mark.covers(
                "SPC-REQ-001-04", "an ID whose spec number has two digits is reported at its own line"
            ),
            id="short-number",
        ),
    ],
)
def test_each_malformed_bullet_is_named_at_its_line(project: Project, bullet: str, detail: str):
    """One bad bullet after a good one: its own line number, the form to write, and what is wrong with it."""
    project.spec(f"- T-REQ-001-01: Good. (unimplemented: later)\n{bullet}")
    run = project.speccheck("lint", "--json")
    [problem] = run.json()["problems"]
    assert (problem["code"], problem["line"]) == ("bullet-malformed", 8)
    assert problem["message"] == f"a bullet must read `- T-REQ-NNN-XX: text` (or BEH); {detail}"


@pytest.mark.covers(
    "SPC-REQ-001-05",
    "the same ID in specs 001 and 002 fails lint at the second one, pointing back at the first",
)
def test_ids_are_unique(project: Project):
    """The second use of an ID points at the first."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: One. (unimplemented: later)")
    project.write("specs/002-other.md", spec("- T-REQ-001-01: Again. (unimplemented: later)", number="002"))
    run = project.speccheck("lint")
    assert "specs/002-other.md:7: T-REQ-001-01 is also at specs/001-thing.md:7; IDs are unique" in run.err.splitlines()


def requirement_json(project: Project) -> dict:
    """The first requirement of a `check --json` run."""
    return project.speccheck("check", "--json").json()["requirements"][0]


@pytest.mark.covers(
    "SPC-REQ-001-06",
    "a bullet wrapped over three indented lines is read as one text, each line joined with one space",
)
def test_a_wrapped_bullet_is_one_text(project: Project):
    """The joined text is what check reports, with one space at each join."""
    project.spec("- T-REQ-001-01: It MUST work\n  for a long\n  while.")
    assert requirement_json(project)["text"] == "It MUST work for a long while."


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "- T-REQ-001-01: It MUST work.\nmore text",
            marks=pytest.mark.covers("SPC-REQ-001-06", "an unindented line after a bullet is not joined to its text"),
            id="unindented",
        ),
        pytest.param(
            "- T-REQ-001-01: It MUST work.\n more text",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "a line indented by one space after a bullet is not joined to its text"
            ),
            id="one-space",
        ),
        pytest.param(
            "- T-REQ-001-01: It MUST work.\n\n  more text",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "an indented line after a blank line is not joined to the bullet's text"
            ),
            id="after-a-blank-line",
        ),
    ],
)
def test_a_line_that_is_not_a_continuation_is_not_joined(project: Project, body: str):
    """Only the two-space-indented lines straight after the bullet are its text."""
    project.spec(body)
    assert requirement_json(project)["text"] == "It MUST work."


@pytest.mark.parametrize(
    ("body", "text", "reason"),
    [
        pytest.param(
            "- T-REQ-001-01: It works. (unimplemented: plan step 2)",
            "It works.",
            "plan step 2",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "a suffix after the full stop makes the requirement unimplemented with its reason"
            ),
            id="stop-before",
        ),
        pytest.param(
            "- T-REQ-001-01: It works (unimplemented: plan step 2).",
            "It works",
            "plan step 2",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "a suffix followed by a full stop still counts, and the stop goes with it"
            ),
            id="stop-after",
        ),
        pytest.param(
            "- T-REQ-001-01: It works (unimplemented:   plan step 2  )",
            "It works",
            "plan step 2",
            marks=pytest.mark.covers("SPC-REQ-001-07", "the reason is trimmed of the spaces around it"),
            id="trimmed",
        ),
        pytest.param(
            "- T-REQ-001-01: It works. (unimplemented: plan\n  step 2)",
            "It works.",
            "plan step 2",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "a suffix wrapped onto the next indented line is read from the joined text"
            ),
            id="wrapped",
        ),
        pytest.param(
            "- T-REQ-001-01: It works. (unimplemented: see (b))",
            "It works.",
            "see (b)",
            marks=pytest.mark.covers("SPC-REQ-001-07", "a reason holding parentheses is kept whole"),
            id="parentheses",
        ),
    ],
)
def test_the_unimplemented_suffix(project: Project, body: str, text: str, reason: str):
    """check shows the status, the text without the suffix, and the reason, and passes: nothing needs claiming."""
    project.spec(body)
    run = project.speccheck("check", "--json")
    found = run.json()["requirements"][0]
    assert (found["status"], found["text"], found["reason"]) == ("unimplemented", text, reason)
    assert run.code == 0, run.err


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "- T-REQ-001-01: It (unimplemented: step 2) works.",
            marks=pytest.mark.covers("SPC-REQ-001-07", "the suffix in the middle of the text does not count"),
            id="mid-text",
        ),
        pytest.param(
            "- T-REQ-001-01: It works. (unimplemented: step 2) Really.",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "the suffix followed by another sentence is not at the end, so it does not count"
            ),
            id="text-after",
        ),
        pytest.param(
            "- T-REQ-001-01: It works. (Unimplemented: step 2)",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "a capitalised `Unimplemented` is not the suffix, so the requirement needs a claim"
            ),
            id="capital",
        ),
        pytest.param(
            "- T-REQ-001-01: It waits 30 seconds (default: 30s)",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "another word in the same trailing form, such as `(default: 30s)`, is ordinary text"
            ),
            id="other-word",
        ),
    ],
)
def test_the_suffix_counts_only_at_the_end(project: Project, body: str):
    """Anywhere else it is text: the requirement is unclaimed, its text kept whole, with no reason."""
    project.spec(body)
    found = requirement_json(project)
    assert (found["status"], found["reason"]) == ("unclaimed", None)
    assert found["text"] == body.split(": ", 1)[1]


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(
            "(unimplemented)",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07",
                "lint reports `(unimplemented)` with no reason at the bullet's line, saying to add one",
            ),
            id="bare",
        ),
        pytest.param(
            "(unimplemented:  )",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "lint reports a suffix whose reason is only spaces as having no reason"
            ),
            id="blank",
        ),
    ],
)
def test_the_reason_is_required(project: Project, suffix: str):
    """A missing reason fails lint with what to write."""
    project.spec(f"- T-REQ-001-01: One.\n- T-REQ-001-02: Later. {suffix}")
    run = project.speccheck("lint", "--json")
    assert run.code == 1
    assert [(p["line"], p["code"], p["message"]) for p in run.json()["problems"]] == [
        (8, "reason-missing", "T-REQ-001-02 needs a reason: write `(unimplemented: <reason>)`")
    ]


@pytest.mark.covers(
    "SPC-REQ-001-08",
    "a dash bullet and a star bullet with real IDs inside a markdown code fence leave lint clean, with one requirement counted",
)
def test_fenced_examples_are_ignored(project: Project):
    """Bullets in a code block are neither requirements nor problems, even a star bullet that is a problem outside one."""
    project.spec(
        "- T-REQ-001-01: Real. (unimplemented: later)\n\n```markdown\n- T-REQ-001-09: Example\n* T-REQ-001-02: Star\n```"
    )
    run = project.speccheck("lint", "--json")
    assert run.code == 0 and run.json()["requirement_count"] == 1


@pytest.mark.covers(
    "SPC-REQ-001-08",
    "a status line and a `## ` header inside ``` and ~~~ fences ahead of the real ones change nothing: lint is clean, with the real status and one requirement",
)
def test_fences_in_the_header_are_ignored(project: Project):
    """The fenced lines sit where they would matter, before `## Requirements`, so ignoring them is what keeps lint clean."""
    project.write(
        "specs/001-thing.md",
        "# 001 - Thing\n\n```markdown\n## Example\nstatus: bogus\n```\n\nstatus: draft\n\n"
        "~~~\nstatus: again\n~~~\n\n## Requirements\n\n- T-REQ-001-01: Real. (unimplemented: later)\n",
    )
    run = project.speccheck("lint", "--json")
    assert run.code == 0, run.err
    assert run.json()["requirement_count"] == 1
    assert [s["status"] for s in run.json()["specs"]] == ["draft"]
    # An unfenced second status line is still reported, at its own line, so the fenced ones above really were skipped
    project.write(
        "specs/001-thing.md",
        "# 001 - Thing\n\n```\nstatus: bogus\n```\n\nstatus: draft\nstatus: draft\n\n## Requirements\n\n"
        "- T-REQ-001-01: Real. (unimplemented: later)\n",
    )
    assert "specs/001-thing.md:8: a second `status:` line; a spec has one" in project.speccheck("lint").err


@pytest.mark.covers(
    "SPC-REQ-001-09",
    "lint points an index's `id-prefix:` line and a spec's `tests:` line at the config, each at its line",
)
def test_the_old_checkers_lines_say_where_the_setting_went(project: Project):
    """`tests:` and `id-prefix:` point at the config."""
    project.write("specs/000-index.md", "# Index\n\nid-prefix: T\n\n" + INDEX)
    project.write("specs/001-thing.md", spec("").replace("status: draft", "status: draft\ntests: tests"))
    run = project.speccheck("lint")
    assert "specs/000-index.md:3: the `id-prefix:` line is gone; set `id-prefix` in the config instead" in run.err
    assert (
        "specs/001-thing.md:4: the `tests:` line is gone; say which producers may claim this spec in the config"
        in run.err
    )


@pytest.mark.covers(
    "SPC-REQ-001-10",
    "lint fails on a requirement in spec 002 repeating one in 001 in other case and spacing, naming both IDs and nothing else",
)
def test_requirement_text_is_said_once(project: Project):
    """Across the folder."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: The file MUST be written.\n- T-REQ-001-02: Something else.")
    project.write(
        "specs/002-other.md", spec("- T-REQ-002-01: the  FILE must be\n  written", number="002", title="Other")
    )
    run = project.speccheck("lint")
    assert run.code == 1
    assert (
        "specs/002-other.md:7: T-REQ-002-01 has the same text as T-REQ-001-01 at specs/001-thing.md:7; "
        "each requirement says something new" in run.err
    )
    assert "T-REQ-001-02" not in run.err


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        pytest.param(
            "The file MUST be written.",
            "The file MUST be written",
            True,
            marks=pytest.mark.covers("SPC-REQ-001-10", "one trailing full stop is ignored when comparing texts"),
            id="one-stop",
        ),
        pytest.param(
            "The file MUST be written..",
            "The file MUST be written.",
            False,
            marks=pytest.mark.covers(
                "SPC-REQ-001-10", "only one trailing stop is dropped, so two stops and one are different texts"
            ),
            id="two-stops",
        ),
        pytest.param(
            "The file MUST be written .",
            "The file MUST be written",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-001-10", "a trailing full stop and the space before it are both dropped when comparing texts"
            ),
            id="space-before-the-stop",
        ),
        pytest.param(
            "The file MUST be written.",
            "The file MUST. be written",
            False,
            marks=pytest.mark.covers("SPC-REQ-001-10", "a full stop in the middle of a text makes it a different text"),
            id="mid-stop",
        ),
        pytest.param(
            "The file MUST be written.",
            "THE  FILE\tmust be   written",
            True,
            marks=pytest.mark.covers(
                "SPC-REQ-001-10", "case, runs of spaces and a tab are ignored when comparing texts"
            ),
            id="case-and-space",
        ),
    ],
)
def test_what_counts_as_the_same_text(project: Project, first: str, second: str, same: bool):
    """Two bullets in one spec, so the duplicate is within a spec as well as across them."""
    project.spec(f"- T-REQ-001-01: {first}\n- T-REQ-001-02: {second}")
    run = project.speccheck("lint", "--json")
    codes = [p["code"] for p in run.json()["problems"]]
    assert (codes == ["text-duplicate"]) is same, run.json()["problems"]
    if same:
        assert run.json()["problems"][0]["message"].startswith("T-REQ-001-02 has the same text as T-REQ-001-01 at ")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            "The file MUST be written.",
            "The file MUST be written. (unimplemented: step 2)",
            marks=pytest.mark.covers(
                "SPC-REQ-001-10",
                "an unimplemented requirement repeating an implemented one's text, apart from the suffix, is a duplicate",
            ),
            id="one-suffix",
        ),
        pytest.param(
            "The file MUST be written. (unimplemented: step 2)",
            "The file MUST be written (unimplemented: step 3).",
            marks=pytest.mark.covers(
                "SPC-REQ-001-10",
                "two unimplemented requirements with different reasons but the same text are duplicates",
            ),
            id="two-reasons",
        ),
    ],
)
def test_texts_are_compared_without_the_suffix(project: Project, first: str, second: str):
    """The suffix says when, not what, so it doesn't make a text new."""
    project.spec(f"- T-REQ-001-01: {first}\n- T-REQ-001-02: {second}")
    run = project.speccheck("lint", "--json")
    assert [p["code"] for p in run.json()["problems"]] == ["text-duplicate"]


@pytest.mark.covers(
    "SPC-REQ-001-10",
    "a requirement repeating the text of an earlier one in the same spec fails lint, naming both IDs and the first one's line",
)
def test_a_duplicate_within_one_spec_names_both(project: Project):
    """Not only across specs."""
    project.spec("- T-REQ-001-01: One thing.\n- T-REQ-001-02: Another.\n- T-REQ-001-03: one thing")
    run = project.speccheck("lint")
    assert run.code == 1
    assert (
        "specs/001-thing.md:9: T-REQ-001-03 has the same text as T-REQ-001-01 at specs/001-thing.md:7; "
        "each requirement says something new" in run.err
    )
