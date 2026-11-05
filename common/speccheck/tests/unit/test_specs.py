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

"""Reading a spec folder: file names, the index, the header, bullets and markers; and the ID syntax."""

from __future__ import annotations

from pathlib import Path

import pytest

from speccheck import specs
from tests.conftest import INDEX, spec

ONE = "- T-REQ-001-01: One."
"""Spec 001's one requirement, for a test about something else: a spec needs at least one."""
TWO = "- T-REQ-002-01: Two."
"""Spec 002's one requirement."""


class Repo:
    """A spec folder under a temporary root, with the index most tests start from."""

    def __init__(self, root: Path) -> None:
        """Write `specs/000-index.md` linking spec 001."""
        self.root = root
        """The root paths in problems are relative to."""
        self.write("specs/000-index.md", INDEX)

    def write(self, name: str, text: str) -> Path:
        """Write a file under the root."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def spec(self, body: str, **kwargs) -> Path:
        """Write spec 001 (or `number=`, named `name=`) with `body` as its requirements."""
        name = kwargs.pop("name", f"{kwargs.get('number', '001')}-thing.md")
        return self.write(f"specs/{name}", spec(body, **kwargs))


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A fresh spec folder."""
    return Repo(tmp_path)


def problems(repo: Repo, prefix: str = "T", require_index: bool = True) -> list[str]:
    """Every format problem in the repo's spec folder, as `path:line: message` strings."""
    loaded = specs.load(repo.root / "specs", repo.root, prefix, require_index)
    return [str(p) for p in loaded.problems]


def assert_problems(repo: Repo, *fragments: str, prefix: str = "T") -> None:
    """Exactly one problem per fragment, each containing it, in any order."""
    found = problems(repo, prefix)
    assert len(found) == len(fragments), found
    for fragment in fragments:
        assert any(fragment in problem for problem in found), (fragment, found)


def requirements(repo: Repo, prefix: str = "T") -> list[specs.Requirement]:
    """Every requirement read, in spec order."""
    return list(specs.load(repo.root / "specs", repo.root, prefix).requirements.values())


class TestFilesAndIndex:
    """File names, titles and the index."""

    def test_file_names_and_the_index(self, repo: Repo):
        """Specs are named NNN-name.md and the index links each one."""
        repo.spec(ONE)
        repo.spec(TWO, number="002", name="002-unlisted.md")
        repo.write("specs/Notes.md", "x")
        assert_problems(repo, "the index doesn't link 002-unlisted.md", "must be named NNN-short-name.md")

    def test_the_title_must_carry_the_number(self, repo: Repo):
        """`# 001 - Name`, so a renamed file shows."""
        repo.write("specs/001-thing.md", spec(ONE).replace("# 001 -", "# 01 -"))
        assert_problems(repo, "specs/001-thing.md:1: the first line must be the title")

    def test_an_empty_file_has_no_title(self, repo: Repo):
        """An empty spec is reported, not a crash."""
        repo.write("specs/001-thing.md", "")
        assert_problems(repo, "the first line must be the title", "a spec needs at least one requirement")

    def test_the_title_is_read(self, repo: Repo):
        """The report shows each spec's title."""
        repo.spec(ONE, title="Spec format")
        assert specs.load(repo.root / "specs", repo.root, "T").specs[0].title == "Spec format"

    def test_the_purpose_is_read(self, repo: Repo):
        """The `## Purpose` section's lines, joined onto one, without a fenced example; "" when there's none."""
        repo.write(
            "specs/001-thing.md",
            "# 001 - Thing\n\nsources: tests\n\n## Purpose\n\nWhat it\n  is for.\n\n```\nnot this\n```\n\n"
            "## Requirements\n\n- T-REQ-001-01: One.\n\n## Notes\n\nNot this either.\n",
        )
        loaded = specs.load(repo.root / "specs", repo.root, "T")
        assert loaded.specs[0].purpose == "What it is for."
        assert [r.text for r in loaded.requirements.values()] == ["One."]
        repo.spec("- T-REQ-001-01: One.")
        assert specs.load(repo.root / "specs", repo.root, "T").specs[0].purpose == ""

    def test_a_heading_ends_a_bullet(self, repo: Repo):
        """An indented line after a `## ` heading isn't more of the last bullet's text."""
        repo.write(
            "specs/001-thing.md",
            "# 001 - Thing\n\nsources: tests\n\n## Requirements\n\n- T-REQ-001-01: One.\n## Open questions\n  Two.\n",
        )
        assert [r.text for r in specs.load(repo.root / "specs", repo.root, "T").requirements.values()] == ["One."]

    def test_an_unlinked_spec_is_named(self, repo: Repo):
        """The index's problem says which file and how to link it."""
        repo.write("specs/000-index.md", "# Index\n\nSpec 002 is below.\n\n- [001](001-thing.md)\n")
        repo.spec(ONE)
        repo.spec(TWO, number="002", name="002-other.md")
        assert problems(repo) == [
            "specs/000-index.md: the index doesn't link 002-other.md; list it as `[002](002-other.md)`"
        ]

    def test_a_missing_index_fails_only_when_required(self, repo: Repo):
        """The index is the entry point, unless the config says a folder has none."""
        (repo.root / "specs" / "000-index.md").unlink()
        repo.spec(ONE)
        assert_problems(repo, "needs a 000-index.md")
        assert problems(repo, require_index=False) == []

    def test_an_index_is_not_required_to_link_when_not_required(self, repo: Repo):
        """With require-index off, an index that exists isn't checked for links."""
        repo.spec(TWO, number="002", name="002-unlisted.md")
        assert problems(repo, require_index=False) == []


class TestHeader:
    """The header: no `status:` line any more, and at least one requirement."""

    def test_a_status_line_is_reported(self, repo: Repo):
        """At its line, saying to delete it."""
        repo.write("specs/001-thing.md", spec(ONE, header="status: implemented"))
        assert problems(repo) == [
            "specs/001-thing.md:3: the `status:` line is gone; delete it "
            "(a planned requirement ends with `(unimplemented: <reason>)`)"
        ]

    def test_a_status_below_the_header_is_text(self, repo: Repo):
        """Under a `##` or in a fence, a `status:` is prose, not the old header line."""
        repo.spec(f"{ONE}\n\n```\nstatus: bogus\n```\n\nstatus: bogus\n")
        assert_problems(repo)

    def test_no_header_line_is_needed(self, repo: Repo):
        """A title and a Requirements section are enough."""
        repo.write("specs/001-thing.md", f"# 001 - Thing\n\n## Requirements\n\n{ONE}\n")
        assert_problems(repo)

    def test_a_spec_needs_a_requirement(self, repo: Repo):
        """With nothing in it, it says to remove the spec through the index."""
        repo.spec("")
        assert problems(repo) == [
            "specs/001-thing.md: a spec needs at least one requirement; if it has none left, delete it "
            "and list 001 in 000-index.md's `removed:` line"
        ]


class TestOldForms:
    """`old_forms`: the old format's markers on a requirement's text, each with its replacement."""

    @pytest.mark.parametrize(
        "text",
        [
            "It. ⚠ untested",
            "It. ⚠ untested.",
            "It. (planned: step 2)",
            "It (planned: step 2).",
            "It (planned: x (y)).",
            "Retired. Gone.",
        ],
    )
    def test_found(self, text):
        """At the end (untested, planned) or the start (retired), with or without a full stop."""
        assert len(specs.old_forms(text, "T-REQ-001-01")) == 1

    @pytest.mark.parametrize(
        "text",
        [
            "It names `⚠ untested` in the middle.",
            "It names (planned: x) mid-text.",
            "Retired later.",
            "It was Retired. Once.",
            "It.",
        ],
    )
    def test_ordinary_words(self, text):
        """Anywhere else they are words, so a requirement can name them."""
        assert specs.old_forms(text, "T-REQ-001-01") == []

    def test_each_says_what_replaces_it(self):
        """Untested and planned: the suffix or a test. Retired: delete it and list the ID in `removed:`."""
        replace = "end it with `(unimplemented: <reason>)` if a plan delivers it later, or give it a test"
        assert specs.old_forms("It. ⚠ untested", "X") == [("`⚠ untested`, which is gone", replace)]
        assert specs.old_forms("It. (planned: 2)", "X") == [("`(planned: ...)`, which is gone", replace)]
        assert specs.old_forms("Retired: gone", "X") == [
            ("`Retired:`, which is gone", "delete the requirement and list X in its spec's `removed:` line")
        ]

    def test_reported_by_load(self, repo: Repo):
        """At the bullet's line, with code `old-marker`."""
        repo.spec("- T-REQ-001-01: One. ⚠ untested")
        [found] = specs.load(repo.root / "specs", repo.root, "T").problems
        assert (found.line, found.code) == (7, "old-marker")
        assert found.message.startswith("T-REQ-001-01 has `⚠ untested`, which is gone; end it with")


class TestBullets:
    """The shape of a requirement bullet."""

    def test_a_malformed_bullet_fails(self, repo: Repo):
        """`REQ-1-1` or a missing colon."""
        repo.spec(f"{ONE}\n- T-REQ-1-1: Short.\n- T-REQ-001-02 Missing colon.")
        assert_problems(repo, "a bullet must read", "a bullet must read")

    def test_every_bullet_style_is_a_bullet(self, repo: Repo):
        """`*`, bold, `+` and a nested bullet are malformed, not invisible."""
        body = (
            "- T-REQ-001-01: Fine.\n* T-REQ-001-02: Star.\n- **T-REQ-001-03**: Bold.\n"
            "  - T-REQ-001-04: Nested.\n+ T-BEH-001-01 Plus."
        )
        repo.spec(body)
        assert_problems(repo, *["a bullet must read `- T-REQ-NNN-XX: text`"] * 4)

    def test_the_message_says_what_was_found(self, repo: Repo):
        """Each malformed shape gets its own reason, and the line's first 60 characters are echoed."""
        long = "- T-REQ-001-09 " + "x" * 80
        repo.spec(
            "- T-REQ-001-10: Real.\n* T-REQ-001-01: Star.\n- **T-REQ-001-02**: Bold.\n  - T-REQ-001-03: Nested.\n"
            f"- REQ-001-04: No prefix.\n- T-REQ-001-05 No colon.\n- T-REQ-1-6: Short.\n{long}"
        )
        assert_problems(
            repo,
            "found `*` where `-` belongs: `* T-REQ-001-01: Star.`",
            "found the ID wrapped in markup: `- **T-REQ-001-02**: Bold.`",
            "found an indented bullet: `- T-REQ-001-03: Nested.`",
            "found an ID without the `T-` prefix: `- REQ-001-04: No prefix.`",
            "found no `: ` and text after the ID: `- T-REQ-001-05 No colon.`",
            "found an ID that is not NNN-XX: `- T-REQ-1-6: Short.`",
            f"found no `: ` and text after the ID: `{long[:60]}…`",
        )

    def test_an_id_in_the_wrong_spec_fails(self, repo: Repo):
        """T-REQ-002-XX belongs in 002."""
        repo.spec("- T-REQ-002-01: Misplaced.")
        assert_problems(repo, "T-REQ-002-01 belongs in spec 002")

    def test_a_bullet_without_the_prefix_fails(self, repo: Repo):
        """The message shows the form to write."""
        repo.spec(f"{ONE}\n- REQ-001-01: It MUST work.")
        assert_problems(repo, "a bullet must read `- T-REQ-NNN-XX: text`")

    def test_a_prefixed_id_in_a_bare_folder_is_ordinary_text(self, repo: Repo):
        """Without a prefix, `T-REQ-001-01` is not a bullet of this folder, and bare IDs are."""
        repo.spec("- REQ-001-01: Bare.\n- T-REQ-001-02: Someone else's.")
        assert problems(repo, prefix="") == []
        assert [r.id for r in requirements(repo, prefix="")] == ["REQ-001-01"]

    def test_behaviours_are_requirements_too(self, repo: Repo):
        """BEH IDs are read like REQ IDs."""
        repo.spec("- T-BEH-001-01: GIVEN x WHEN y THEN z.")
        assert [r.id for r in requirements(repo)] == ["T-BEH-001-01"]


def test_duplicate_ids_fail(repo: Repo):
    """IDs are unique across the whole folder."""
    repo.spec("- T-REQ-001-01: One.\n- T-REQ-001-01: Again.")
    assert_problems(repo, "T-REQ-001-01 is also at specs/001-thing.md:7")


def test_duplicate_text_fails(repo: Repo):
    """Text is unique across the folder, compared as `comparable`."""
    repo.spec("- T-REQ-001-01: It is WRITTEN.\n- T-REQ-001-02: it is\n  written")
    found = problems(repo)
    assert found == [
        "specs/001-thing.md:8: T-REQ-001-02 has the same text as T-REQ-001-01 at specs/001-thing.md:7; "
        "each requirement says something new"
    ]
    assert specs.load(repo.root / "specs", repo.root, "T").problems[0].code == "text-duplicate"


@pytest.mark.parametrize(
    ("text", "collapsed", "compared"),
    [
        ("  a\n\tb  c ", "a b c", "a b c"),
        ("It Is.", "It Is.", "it is"),
        ("It is . ", "It is .", "it is"),
        ("Two..", "Two..", "two."),
        ("It works. (unimplemented: x)", "It works. (unimplemented: x)", "it works"),
        ("It\n  works (unimplemented:\n  x).", "It works (unimplemented: x).", "it works"),
        ("", "", ""),
    ],
)
def test_collapse_and_comparable(text, collapsed, compared):
    """Whitespace to single spaces; then case folded and one trailing full stop dropped."""
    assert (specs.collapse(text), specs.comparable(text)) == (collapsed, compared)


@pytest.mark.parametrize(
    ("text", "kept", "reason"),
    [
        ("It works. (unimplemented: step 2)", "It works.", "step 2"),
        ("It works (unimplemented: step 2).", "It works", "step 2"),
        ("It works (unimplemented:  step 2 )", "It works", "step 2"),
        ("It works (unimplemented: see (b))", "It works", "see (b)"),
        ("It works. (unimplemented)", "It works.", ""),
        ("It works. (unimplemented: )", "It works.", ""),
        ("It works.", "It works.", None),
        ("It (unimplemented: step 2) works.", "It (unimplemented: step 2) works.", None),
        ("It works. (unimplemented: step 2) later", "It works. (unimplemented: step 2) later", None),
        ("It works. (unimplemented: step 2)..", "It works. (unimplemented: step 2)..", None),
        ("It works. (Unimplemented: step 2)", "It works. (Unimplemented: step 2)", None),
        ("It works. (default: 30s)", "It works. (default: 30s)", None),
        ("It works. (unimplementedx: a)", "It works. (unimplementedx: a)", None),
    ],
)
def test_split_suffix(text, kept, reason):
    """Only a suffix at the very end counts, with one optional stop after it; the reason is trimmed."""
    assert specs.split_suffix(text) == (kept, reason)


class TestUnimplemented:
    """The suffix on a bullet, as `load` reads it."""

    def test_the_suffix_is_split_off(self, repo: Repo):
        """The text is kept without it, and the reason is the requirement's."""
        repo.spec("- T-REQ-001-01: It works. (unimplemented: step 2)")
        requirement = requirements(repo)[0]
        assert (requirement.text, requirement.reason, requirement.unimplemented) == ("It works.", "step 2", True)

    def test_no_suffix_is_implemented(self, repo: Repo):
        """The default."""
        repo.spec("- T-REQ-001-01: It works.")
        requirement = requirements(repo)[0]
        assert (requirement.reason, requirement.unimplemented) == (None, False)

    def test_a_suffix_on_a_continuation_line_counts(self, repo: Repo):
        """The lines are joined first, so the suffix may be on the last line or wrap."""
        repo.spec("- T-REQ-001-01: It MUST work\n  for a while. (unimplemented: plan\n  step 2)")
        requirement = requirements(repo)[0]
        assert (requirement.text, requirement.reason) == ("It MUST work for a while.", "plan step 2")

    def test_a_missing_reason_is_a_problem(self, repo: Repo):
        """At the bullet's line, saying what to write."""
        repo.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Later. (unimplemented)")
        assert problems(repo) == [
            "specs/001-thing.md:8: T-REQ-001-02 needs a reason: write `(unimplemented: <reason>)`"
        ]

    def test_the_text_is_compared_without_the_suffix(self, repo: Repo):
        """The same requirement, with and without the suffix, is a duplicate."""
        repo.spec("- T-REQ-001-01: It works.\n- T-REQ-001-02: It works. (unimplemented: step 2)")
        assert_problems(repo, "T-REQ-001-02 has the same text as T-REQ-001-01")

    def test_a_nested_bullet_is_not_glued_to_the_one_above(self, repo: Repo):
        """It ends the previous requirement's text instead of extending it."""
        repo.spec("- T-REQ-001-01: Real.\n  - T-REQ-001-02: nested (unimplemented: step 2)")
        assert [(r.id, r.unimplemented) for r in requirements(repo)] == [("T-REQ-001-01", False)]

    def test_a_blank_line_ends_the_bullet(self, repo: Repo):
        """Indented text after a blank line is not the bullet's."""
        repo.spec("- T-REQ-001-01: Real.\n\n  (unimplemented: step 2)")
        assert not requirements(repo)[0].unimplemented


@pytest.mark.parametrize(
    ("line", "continued"),
    [("  more", True), ("    more", True), ("  ", False), (" more", False), ("\tmore", False), ("more", False)],
)
def test_continues(line, continued):
    """Two or more spaces then text continue a line; anything less, a tab, or a blank does not."""
    assert specs.continues(line) is continued


class TestHeaderLines:
    """`header_lines`: a `key:` line above the first `##`, outside fences, joined across continuations."""

    def test_one_line(self):
        """Its line number and trimmed value."""
        assert specs.header_lines(["# 001 - X", "", "removed:  A, B "], "removed") == [(3, "A, B")]

    def test_continued(self):
        """Continuation lines join with one space; a line that doesn't continue ends it."""
        lines = ["removed: A,", "  B,", "    C", "next: x"]
        assert specs.header_lines(lines, "removed") == [(1, "A, B, C")]

    def test_every_one_is_found(self):
        """A repeat is kept, so the caller can report it at its line."""
        assert specs.header_lines(["removed: A", "removed: B"], "removed") == [(1, "A"), (2, "B")]

    def test_only_above_the_first_section(self):
        """The header ends at the first `##`."""
        assert specs.header_lines(["## Requirements", "removed: A"], "removed") == []

    def test_not_in_a_fence(self):
        """A fenced example is not the spec's header, and doesn't continue the line above it."""
        lines = ["removed: A", "```", "  B", "removed: C", "```"]
        assert specs.header_lines(lines, "removed") == [(1, "A")]

    def test_another_key_is_not_this_one(self):
        """`removed:` must start the line; `not removed:` is text."""
        assert specs.header_lines(["not removed: A", "removedx: B"], "removed") == []


@pytest.mark.parametrize(
    ("value", "items"),
    [("A, B", ["A", "B"]), ("A,,B,", ["A", "B"]), ("  A  ", ["A"]), ("", []), (" , ", [])],
)
def test_listed(value, items):
    """Comma-separated, trimmed, with empty items dropped."""
    assert specs.listed(value) == items


class TestRemovedList:
    """`removed_list`: the items of a `removed:` line, checked."""

    def refuse_x(self, item: str) -> str:
        """A check that refuses only `X`."""
        return "no X" if item == "X" else ""

    def run(self, found: list[tuple[int, str]]) -> tuple[list[str], list[tuple[int, str, str]]]:
        """The items kept, and each problem's line, code and message."""
        problems: list[specs.Problem] = []
        kept = specs.removed_list(found, self.refuse_x, "f.md", problems)
        return kept, [(p.line, p.code, p.message) for p in problems]

    def test_none(self):
        """No line, nothing listed, no problem."""
        assert self.run([]) == ([], [])

    def test_kept_in_order(self):
        """Every allowed item, in the order written."""
        assert self.run([(3, "B, A")]) == (["B", "A"], [])

    def test_a_refused_item(self):
        """Reported at the line with the check's message, and left out."""
        assert self.run([(3, "A, X")]) == (["A"], [(3, "removed-invalid", "no X")])

    def test_an_item_twice(self):
        """Reported once, kept once."""
        assert self.run([(3, "A, A")]) == (["A"], [(3, "removed-repeated", "A is listed twice in `removed:`")])

    def test_a_second_line(self):
        """Reported at its own line, and its items are not read."""
        kept, found = self.run([(3, "A"), (4, "B")])
        assert kept == ["A"]
        assert found == [(4, "removed-repeated", "a second `removed:` line; list everything on the first")]


@pytest.mark.parametrize(("item", "ok"), [("007", True), ("7", False), ("0007", False), ("abc", False)])
def test_spec_number_problem(item, ok):
    """Three digits, and the message shows the form."""
    found = specs.spec_number_problem(item)
    assert (found == "") is ok
    if not ok:
        assert found == f"`{item}` in `removed:` isn't a spec number; they are three digits, like `007`"


def test_the_index_is_not_a_removed_spec():
    """`000` is three digits but names the index itself."""
    assert specs.spec_number_problem("000") == "`000` in `removed:` is the index, not a spec"


def test_removed_from():
    """A removed ID names its spec; an ID of a removed spec says the spec went; anything else is ""."""
    found = specs.SpecSet([], {}, [], specs.Syntax("T"), removed={"T-REQ-001-05": "001"}, removed_specs=["009"])
    assert found.removed_from("T-REQ-001-05", "001") == "T-REQ-001-05 was removed from spec 001; delete the claim"
    assert (
        found.removed_from("T-REQ-009-01", "009") == "T-REQ-009-01 is in spec 009, which was removed; delete the claim"
    )
    assert found.removed_from("T-REQ-001-06", "001") == ""


class TestRemoved:
    """A spec's and the index's `removed:` lines, as `load` reads them."""

    def test_a_specs_removed_ids(self, repo: Repo):
        """Listed on the spec, kept by ID with the spec's number, and no problem."""
        repo.write(
            "specs/001-thing.md",
            spec("- T-REQ-001-01: One.", header="sources: tests\nremoved: T-REQ-001-02,\n  T-REQ-001-03"),
        )
        loaded = specs.load(repo.root / "specs", repo.root, "T")
        assert (loaded.removed, loaded.problems) == ({"T-REQ-001-02": "001", "T-REQ-001-03": "001"}, [])
        assert loaded.specs[0].removed_line == 4

    def test_an_id_of_another_spec_is_refused(self, repo: Repo):
        """Each spec lists only its own IDs."""
        repo.write(
            "specs/001-thing.md",
            spec("- T-REQ-001-01: One.", header="sources: tests\nremoved: T-REQ-002-01"),
        )
        assert_problems(
            repo,
            "specs/001-thing.md:4: `T-REQ-002-01` in `removed:` isn't an ID of this spec; they read like `T-REQ-001-01`",
        )

    def test_a_removed_id_that_is_a_requirement(self, repo: Repo):
        """At the `removed:` line, naming where the requirement is."""
        repo.write(
            "specs/001-thing.md",
            spec("- T-REQ-001-01: One.", header="sources: tests\nremoved: T-REQ-001-01"),
        )
        assert problems(repo) == [
            "specs/001-thing.md:4: T-REQ-001-01 is listed in `removed:` but is a requirement at specs/001-thing.md:8; "
            "a removed ID is never reused"
        ]

    def test_the_index_lists_removed_specs(self, repo: Repo):
        """Read from the index, and a spec file with a listed number is a problem and not read."""
        repo.write("specs/000-index.md", INDEX + "\nremoved: 002, 003\n")
        repo.spec(ONE)
        repo.spec("- T-REQ-002-01: Two.", number="002", name="002-old.md")
        loaded = specs.load(repo.root / "specs", repo.root, "T")
        assert loaded.removed_specs == ["002", "003"]
        assert [s.number for s in loaded.specs] == ["001"]
        assert [str(p) for p in loaded.problems] == [
            "specs/002-old.md: spec 002 is listed as removed in 000-index.md; delete the file or the listing"
        ]

    def test_a_bad_number_in_the_index(self, repo: Repo):
        """At the index's line."""
        repo.write("specs/000-index.md", INDEX + "\nremoved: 9\n")
        repo.spec(ONE)
        assert_problems(repo, "specs/000-index.md:5: `9` in `removed:` isn't a spec number")


def test_a_fenced_example_is_not_a_requirement(repo: Repo):
    """A code block can show the format, a header line or a bullet, and none of it counts."""
    body = (
        "- T-REQ-001-01: Real.\n\n```markdown\n- T-REQ-001-09: Example\n* T-REQ-1-1 bad\ntests: x\n```\n\n"
        "~~~\n- T-REQ-001-08: Tilde\n~~~"
    )
    repo.spec(body)
    assert_problems(repo)
    assert [r.id for r in requirements(repo)] == ["T-REQ-001-01"]


class TestProblems:
    """The problem format, and control characters."""

    def test_path_line_message(self):
        """With a line and without one."""
        assert str(specs.Problem("a.md", 3, "bad")) == "a.md:3: bad"
        assert str(specs.Problem("a.md", 0, "bad")) == "a.md: bad"
        assert specs.Problem("a.md", 3, "bad").to_json() == {
            "path": "a.md",
            "line": 3,
            "message": "bad",
            "code": "problem",
        }

    def test_control_characters_are_written_out(self):
        """A newline can't start a `::error::` line in a CI log."""
        problem = specs.Problem("a\n::error::x.md", 1, "m\x1b[31m")
        assert str(problem) == r"a\n::error::x.md:1: m\x1b[31m"
        assert "\n" not in str(problem)

    def test_plain_leaves_ordinary_text_alone(self):
        """Paths with spaces, accents and symbols read as written; other controls are escaped."""
        assert specs.plain("tests/café é/x y.py") == "tests/café é/x y.py"
        assert specs.plain(f"a\tb{chr(0x2028)}c\x7fd\x85") == "a\\tb\\u2028c\\x7fd\\x85"

    @pytest.mark.parametrize(
        ("text", "written"),
        [
            ("::error title=x::FORGED", r"\x3a:error title=x::FORGED"),
            ("  ::warning::x", r"  \x3a:warning::x"),
            ("\t::error::x", r"\t::error::x"),
            ("a ##[error]x ##[group]y", r"a ##\x5berror]x ##\x5bgroup]y"),
            ("a::b ::c # [x] #[y]", "a::b ::c # [x] #[y]"),
        ],
    )
    def test_plain_writes_out_log_commands(self, text: str, written: str):
        """A line can't start `::`, even after spaces, and `##[` is written out anywhere; other colons stay."""
        assert specs.plain(text) == written

    def test_a_problem_whose_path_is_a_log_command(self):
        """A `file` field of `::error::x`, with no newline, is the start of the line and is written out."""
        assert str(specs.Problem("::error::x", 3, "m")) == r"\x3a:error::x:3: m"
        assert str(specs.Problem("::error::x", 0, "m")) == r"\x3a:error::x: m"

    @pytest.mark.parametrize("code", [*range(0x202A, 0x202F), *range(0x2066, 0x206A)])
    def test_plain_writes_out_bidi_controls(self, code: int):
        """Each bidi embedding, override and isolate control is written out, so text can't read reversed."""
        assert specs.plain(f"a{chr(code)}b") == f"a\\u{code:04x}b"

    def test_plain_keeps_other_right_to_left_text(self):
        """Hebrew and Arabic letters, and the implicit marks U+200E and U+200F, aren't controls."""
        assert specs.plain("test_שלום_مرحبا\u200e\u200f") == "test_שלום_مرحبا\u200e\u200f"

    def test_a_path_outside_the_root_is_printed_as_given(self, tmp_path: Path):
        """`rel` falls back to the path itself."""
        assert specs.rel(Path("/elsewhere/x.md"), tmp_path) == "/elsewhere/x.md"


@pytest.mark.parametrize(
    ("index", "linked"),
    [
        ("- [001](001-thing.md)", True),
        ("| 001 | [Thing](./001-thing.md#purpose) |", True),
        ("* [x](001-thing.md)", True),
        ("[](001-thing.md)", True),
        ("Spec 001 and 001-thing.md, in prose.", False),
        ("`001-thing.md`", False),
        ("| 001 | Thing | draft |", False),
        ("- [elsewhere](../x/001-thing.md)", False),
        ("- [other](001-thing.md.bak)", False),
        ("- [other](x001-thing.md)", False),
    ],
)
def test_links_to(index: str, linked: bool):
    """Only a markdown link to the file itself lists it; a mention doesn't."""
    assert specs.links_to(index, "001-thing.md") is linked


class TestSyntax:
    """One folder's ID patterns."""

    @pytest.mark.parametrize(
        ("prefix", "good", "bad"),
        [
            ("T", ["T-REQ-001-01", "T-BEH-123-99"], ["REQ-001-01", "T-REQ-1-1", "T-XYZ-001-01", "U-REQ-001-01"]),
            ("", ["REQ-001-01", "BEH-001-01"], ["T-REQ-001-01", "REQ-001-1"]),
        ],
    )
    def test_ids(self, prefix: str, good: list[str], bad: list[str]):
        """A whole ID in this folder's form, and nothing else."""
        syntax = specs.Syntax(prefix)
        assert all(syntax.id.fullmatch(i) for i in good) and not any(syntax.id.fullmatch(i) for i in bad)
        assert syntax.id.fullmatch(good[0]).group("number") == good[0].split("-")[-2]

    @pytest.mark.parametrize(
        ("line", "starts", "well_formed"),
        [
            ("- T-REQ-001-01: Text.", True, True),
            ("- T-REQ-001-01 Text.", True, False),
            ("* T-REQ-001-01: Text.", True, False),
            ("- **T-REQ-001-01**: Text.", True, False),
            ("  - T-REQ-001-01: Text.", True, False),
            ("+ T-BEH-001-01: Text.", True, False),
            ("- T-REQ-001-01:", True, False),
            ("- REQ-001-01: Text.", True, False),
            ("- Some text about T-REQ-001-01.", False, False),
            ("T-REQ-001-01: not a bullet", False, False),
        ],
    )
    def test_bullets(self, line: str, starts: bool, well_formed: bool):
        """Every list style starts a bullet, so none slips past as text; only `- ID: text` is well-formed."""
        syntax = specs.Syntax("T")
        assert bool(syntax.bullet_start.match(line)) is starts
        assert bool(syntax.bullet.match(line)) is well_formed

    def test_the_example_id_has_the_prefix(self):
        """Messages show an ID in the folder's own form."""
        assert specs.Syntax("SPC").example() == "SPC-REQ-001-01"
        assert specs.Syntax("").example() == "REQ-001-01"
