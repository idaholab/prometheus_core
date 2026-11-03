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
                "SPC-REQ-001-03", f"a spec with status {status} and one untested requirement lints clean"
            ),
            id=status,
        )
        for status in ("draft", "implemented", "retired")
    ],
)
def test_each_status_value_is_accepted(project: Project, status: str):
    """All three values are valid."""
    project.spec("- T-REQ-001-01: One. ⚠ untested", status=status)
    run = project.speccheck("lint")
    assert run.code == 0 and run.err == "", run.err


@pytest.mark.covers(
    "SPC-REQ-001-03",
    "a status line placed under ## Requirements does not count, so lint reports the status missing",
)
def test_a_status_below_the_first_section_does_not_count(project: Project):
    """The line must be above the first `##`."""
    project.write(
        "specs/001-thing.md", "# 001 - Thing\n\n## Requirements\n\nstatus: draft\n\n- T-REQ-001-01: One. ⚠ untested\n"
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
    "lint reports an unknown status value, a second status line, a missing one, and an implemented spec with no requirements, each at its line",
)
def test_the_status_line(project: Project):
    """Missing, unknown, repeated, and implemented with nothing in it, are all problems."""
    project.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: done\nstatus: draft\n")
    run = project.speccheck("lint")
    assert "specs/001-thing.md:3: status must be one of draft, implemented, retired" in run.err
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
        "- T-REQ-001-01: Good. ⚠ untested\n* T-REQ-001-02: Star.\n- **T-REQ-001-03**: Bold.\n"
        "  - T-REQ-001-04: Nested.\n- REQ-001-05: No prefix.\n- T-REQ-002-01: Wrong spec."
    )
    run = project.speccheck("lint")
    assert run.err.count("a bullet must read `- T-REQ-NNN-XX: text` (or BEH)") == 4
    assert "T-REQ-002-01 belongs in spec 002" in run.err
    assert run.err.splitlines()[-1] == "speccheck lint: 1 specs, 2 requirements; 5 problems"


@pytest.mark.covers(
    "SPC-REQ-001-04",
    "a T-BEH-001-01 bullet is a valid requirement, so lint is clean and check lists it",
)
def test_a_beh_bullet_is_a_requirement(project: Project):
    """BEH is the other form, beside REQ."""
    project.spec("- T-BEH-001-01: It behaves. ⚠ untested")
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
    project.spec(f"- T-REQ-001-01: Good. ⚠ untested\n{bullet}")
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
    project.spec("- T-REQ-001-01: One. ⚠ untested")
    project.write("specs/002-other.md", spec("- T-REQ-001-01: Again. ⚠ untested", number="002"))
    run = project.speccheck("lint")
    assert "T-REQ-001-01 is also at specs/001-thing.md:7; IDs are unique" in run.err
    assert "specs/002-other.md:7:" in run.err


@pytest.mark.covers(
    "SPC-REQ-001-06",
    "the untested and planned markers count on a wrapped second line, and a bullet carrying both is a problem",
)
def test_markers_on_continuation_lines(project: Project):
    """A marker on a wrapped line counts, and both markers on one bullet is a problem."""
    project.spec(
        "- T-REQ-001-01: It MUST work\n  for a long while. ⚠ untested\n"
        "- T-REQ-001-02: Later\n  (planned: step 2)\n- T-REQ-001-03: Both. (planned: step 2) ⚠ untested"
    )
    run = project.speccheck("check", "--json")
    statuses = {r["id"]: r["status"] for r in run.json()["requirements"]}
    assert statuses == {"T-REQ-001-01": "untested", "T-REQ-001-02": "planned", "T-REQ-001-03": "planned"}
    assert [p["message"] for p in run.json()["problems"]] == [
        "T-REQ-001-03 is both planned and untested; keep one marker"
    ]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "- T-REQ-001-01: It MUST work.\n(planned: step 2)",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "a (planned: ...) marker on an unindented line after the bullet does not count"
            ),
            id="unindented-planned",
        ),
        pytest.param(
            "- T-REQ-001-01: It MUST work.\n⚠ untested",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "an untested marker on an unindented line after the bullet does not count"
            ),
            id="unindented-untested",
        ),
        pytest.param(
            "- T-REQ-001-01: It MUST work.\n y ⚠ untested",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "an untested marker on a line indented by one space does not count"
            ),
            id="one-space",
        ),
        pytest.param(
            "- T-REQ-001-01: It MUST work.\n\n  more ⚠ untested",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "an untested marker on an indented line after a blank line does not count"
            ),
            id="after-a-blank-line",
        ),
    ],
)
def test_a_marker_that_is_not_in_the_bullet_does_not_count(project: Project, body: str):
    """Only the bullet's own text counts: its line and the two-space-indented lines straight after it."""
    project.spec(body)
    run = project.speccheck("check", "--json")
    assert run.json()["requirements"][0]["status"] == "unclaimed"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param(
            "- T-REQ-001-01: It MUST work (planned:\n  step 2)",
            "planned",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "a (planned: ...) marker wrapped across two indented lines still counts"
            ),
            id="wrapped-planned",
        ),
        pytest.param(
            "- T-REQ-001-01: It MUST work ⚠\n  untested",
            "untested",
            marks=pytest.mark.covers(
                "SPC-REQ-001-06", "the untested marker wrapped across two indented lines still counts"
            ),
            id="wrapped-untested",
        ),
    ],
)
def test_a_marker_wrapped_over_lines_still_counts(project: Project, body: str, status: str):
    """The continuation lines are joined into the bullet's one text, so a wrap inside a marker doesn't break it."""
    project.spec(body)
    assert project.speccheck("check", "--json").json()["requirements"][0]["status"] == status


@pytest.mark.covers(
    "SPC-REQ-001-06",
    "a marker on the third of three indented lines of a bullet counts",
)
def test_a_marker_on_a_later_continuation_line_counts(project: Project):
    """Wherever it is in the continued text."""
    project.spec("- T-REQ-001-01: It MUST work\n  for a long\n  while ⚠ untested")
    assert project.speccheck("check", "--json").json()["requirements"][0]["status"] == "untested"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param(
            "- T-REQ-001-01: Is Retired. later",
            "unclaimed",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "`Retired.` in the middle of a bullet's text does not retire it"
            ),
            id="mid-text",
        ),
        pytest.param(
            "- T-REQ-001-01: It was\n  Retired. long ago",
            "unclaimed",
            marks=pytest.mark.covers(
                "SPC-REQ-001-07", "`Retired.` at the start of a continuation line does not retire the bullet"
            ),
            id="continuation-line",
        ),
        pytest.param(
            "- T-REQ-001-01: retired. lower case",
            "unclaimed",
            marks=pytest.mark.covers("SPC-REQ-001-07", "a lower-case `retired.` start does not retire the bullet"),
            id="lower-case",
        ),
        pytest.param(
            "- T-REQ-001-01: Retirement of the old file.",
            "unclaimed",
            marks=pytest.mark.covers("SPC-REQ-001-07", "a text starting with `Retirement` does not retire the bullet"),
            id="retirement",
        ),
        pytest.param(
            "- T-REQ-001-01: Retired.",
            "retired",
            marks=pytest.mark.covers("SPC-REQ-001-07", "a text of just `Retired.` retires the bullet"),
            id="just-retired",
        ),
    ],
)
def test_retired_only_at_the_start(project: Project, body: str, status: str):
    """The marker is at the start of the bullet's own text, with a full stop or a colon right after it."""
    project.spec(body)
    assert project.speccheck("check", "--json").json()["requirements"][0]["status"] == status


@pytest.mark.covers(
    "SPC-REQ-001-07",
    "check shows `Retired.` and `Retired:` bullets and every bullet of a retired spec as retired, while `Retired later.` stays unclaimed",
)
def test_retired_requirements(project: Project):
    """`Retired.` and `Retired:` retire a bullet, other wording doesn't, and a retired spec retires all of it."""
    project.write("specs/000-index.md", INDEX + "- [002](002-old.md)\n")
    project.spec("- T-REQ-001-01: Retired. Gone.\n- T-REQ-001-02: Retired: gone.\n- T-REQ-001-03: Retired later.")
    project.write("specs/002-old.md", spec("- T-REQ-002-01: It did.", status="retired", number="002"))
    statuses = {r["id"]: r["status"] for r in project.speccheck("check", "--json").json()["requirements"]}
    assert statuses == {
        "T-REQ-001-01": "retired",
        "T-REQ-001-02": "retired",
        "T-REQ-001-03": "unclaimed",
        "T-REQ-002-01": "retired",
    }


@pytest.mark.covers(
    "SPC-REQ-001-08",
    "a dash bullet and a star bullet with real IDs inside a markdown code fence leave lint clean, with one requirement counted",
)
def test_fenced_examples_are_ignored(project: Project):
    """Bullets in a code block are neither requirements nor problems, even a star bullet that is a problem outside one."""
    project.spec(
        "- T-REQ-001-01: Real. ⚠ untested\n\n```markdown\n- T-REQ-001-09: Example\n* T-REQ-001-02: Star\n```"
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
        "~~~\nstatus: again\n~~~\n\n## Requirements\n\n- T-REQ-001-01: Real. ⚠ untested\n",
    )
    run = project.speccheck("lint", "--json")
    assert run.code == 0, run.err
    assert run.json()["requirement_count"] == 1
    assert [s["status"] for s in run.json()["specs"]] == ["draft"]
    # An unfenced second status line is still reported, at its own line, so the fenced ones above really were skipped
    project.write(
        "specs/001-thing.md",
        "# 001 - Thing\n\n```\nstatus: bogus\n```\n\nstatus: draft\nstatus: draft\n\n## Requirements\n\n"
        "- T-REQ-001-01: Real. ⚠ untested\n",
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
    "lint fails on a requirement in spec 002 repeating one in 001 in other case and spacing, naming both IDs, and skips two retired ones",
)
def test_requirement_text_is_said_once(project: Project):
    """Across the folder; retired requirements, whose text is often just `Retired.`, don't count."""
    project.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: The file MUST be written.\n- T-REQ-001-02: Retired.\n- T-REQ-001-03: Retired.")
    project.write(
        "specs/002-other.md", spec("- T-REQ-002-01: the  FILE must be\n  written", number="002", title="Other")
    )
    run = project.speccheck("lint")
    assert run.code == 1
    assert (
        "specs/002-other.md:7: T-REQ-002-01 has the same text as T-REQ-001-01 at specs/001-thing.md:7; "
        "each requirement says something new" in run.err
    )
    assert "T-REQ-001-03" not in run.err


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


@pytest.mark.covers(
    "SPC-REQ-001-10",
    "a retired spec holding the text of a live requirement, and two retired bullets in a live spec with identical text, give no problem",
)
def test_retired_texts_are_not_compared(project: Project):
    """A retired spec's requirement is not a second copy of live text, and retired bullets are not compared with each other."""
    project.write("specs/000-index.md", INDEX + "- [002](002-old.md)\n")
    project.spec("- T-REQ-001-01: The file MUST be written.")
    project.write("specs/002-old.md", spec("- T-REQ-002-01: The file MUST be written.", status="retired", number="002"))
    assert project.speccheck("lint", "--json").json()["problems"] == []
    project.spec(
        "- T-REQ-001-01: The file MUST be written.\n"
        "- T-REQ-001-02: Retired. The file MUST be written.\n"
        "- T-REQ-001-03: Retired. The file MUST be written."
    )
    assert project.speccheck("lint", "--json").json()["problems"] == []


@pytest.mark.covers(
    "SPC-REQ-001-10",
    "a live requirement repeating the text of an earlier one in the same spec fails lint, naming both IDs and the first one's line",
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
