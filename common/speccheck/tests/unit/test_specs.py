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

"""Spec parsing, ported from #355's tests without the citation and `tests:` rules."""

from __future__ import annotations

from pathlib import Path

from speccheck import specs
from tests.conftest import INDEX, Repo, spec


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
        repo.spec("")
        repo.spec("", number="002", name="002-unlisted.md")
        repo.write("specs/Notes.md", "x")
        assert_problems(repo, "the index doesn't link 002-unlisted.md", "must be named NNN-short-name.md")

    def test_the_title_must_carry_the_number(self, repo: Repo):
        """`# 001 - Name`, so a renamed file shows."""
        repo.write("specs/001-thing.md", spec("").replace("# 001 -", "# 01 -"))
        assert_problems(repo, "specs/001-thing.md:1: the first line must be the title")

    def test_an_empty_file_has_no_title(self, repo: Repo):
        """An empty spec is reported, not a crash."""
        repo.write("specs/001-thing.md", "")
        assert_problems(repo, "the first line must be the title", "missing the `status:` line")

    def test_the_title_is_read(self, repo: Repo):
        """The report shows each spec's title."""
        repo.spec("", title="Spec format")
        assert specs.load(repo.root / "specs", repo.root, "T").specs[0].title == "Spec format"

    def test_a_mention_in_the_index_is_not_a_listing(self, repo: Repo):
        """The number or file name in prose, a code span or a link to another file doesn't list a spec."""
        repo.write(
            "specs/000-index.md",
            "# Index\n\nSpec 002 and 002-other.md are below; `002-other.md` too.\n\n"
            "| 002 | Other | draft |\n\n- [001](001-thing.md)\n- [elsewhere](../x/002-other.md)\n",
        )
        repo.spec("")
        repo.spec("", number="002", name="002-other.md")
        assert_problems(repo, "the index doesn't link 002-other.md")

    def test_the_index_may_link_in_any_markdown_form(self, repo: Repo):
        """A table cell, a list item, `./`, an anchor and a title-less link all list the spec."""
        repo.write(
            "specs/000-index.md", "# Index\n\n| 001 | [Thing](./001-thing.md#purpose) |\n\n* [002](002-other.md)\n"
        )
        repo.spec("")
        repo.spec("", number="002", name="002-other.md")
        assert_problems(repo)

    def test_a_missing_index_fails_only_when_required(self, repo: Repo):
        """The index is the entry point, unless the config says a folder has none."""
        (repo.root / "specs" / "000-index.md").unlink()
        repo.spec("")
        assert_problems(repo, "needs a 000-index.md")
        assert problems(repo, require_index=False) == []

    def test_an_index_is_not_required_to_link_when_not_required(self, repo: Repo):
        """With require-index off, an index that exists isn't checked for links."""
        repo.spec("", number="002", name="002-unlisted.md")
        assert problems(repo, require_index=False) == []


class TestHeader:
    """The `status:` line."""

    def test_the_status_line_is_required_and_known(self, repo: Repo):
        """A missing or unknown status is a problem."""
        repo.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: done\n")
        assert_problems(repo, "status must be one of draft, implemented, retired")
        repo.write("specs/001-thing.md", "# 001 - Thing\n")
        assert_problems(repo, "missing the `status:` line")

    def test_the_header_is_read_only_above_the_first_section(self, repo: Repo):
        """A `status:` in an example further down is prose, not the spec's setting."""
        repo.spec("- T-REQ-001-01: It MUST work.\n\n```\nstatus: retired\n```\n\nstatus: retired\n")
        assert_problems(repo)
        assert not requirements(repo)[0].retired

    def test_a_repeated_status_line_fails(self, repo: Repo):
        """The second one would otherwise win without a word."""
        repo.write("specs/001-thing.md", spec("").replace("status: draft", "status: draft\nstatus: retired"))
        assert_problems(repo, "a second `status:` line")

    def test_an_implemented_spec_needs_a_requirement(self, repo: Repo):
        """A skeleton is fine as a draft, but "implemented" with nothing in it would pass vacuously."""
        repo.spec("", status="implemented")
        assert_problems(repo, "an implemented spec needs at least one requirement")

    def test_draft_and_retired_specs_may_be_empty(self, repo: Repo):
        """Only a spec that says it is implemented must say something."""
        repo.write("specs/000-index.md", INDEX + "- [002](002-old.md)\n")
        repo.spec("")
        repo.spec("", status="retired", number="002", name="002-old.md")
        assert_problems(repo)


class TestBullets:
    """The shape of a requirement bullet."""

    def test_a_malformed_bullet_fails(self, repo: Repo):
        """`REQ-1-1` or a missing colon."""
        repo.spec("- T-REQ-1-1: Short.\n- T-REQ-001-02 Missing colon.")
        assert_problems(repo, "a bullet must read", "a bullet must read")

    def test_every_bullet_style_is_a_bullet(self, repo: Repo):
        """`*`, bold, `+` and a nested bullet are malformed, not invisible."""
        body = (
            "- T-REQ-001-01: Fine.\n* T-REQ-001-02: Star.\n- **T-REQ-001-03**: Bold.\n"
            "  - T-REQ-001-04: Nested.\n+ T-BEH-001-01 Plus."
        )
        repo.spec(body)
        assert_problems(repo, *["a bullet must read `- T-REQ-NNN-XX: text`"] * 4)

    def test_an_id_in_the_wrong_spec_fails(self, repo: Repo):
        """T-REQ-002-XX belongs in 002."""
        repo.spec("- T-REQ-002-01: Misplaced.")
        assert_problems(repo, "T-REQ-002-01 belongs in spec 002")

    def test_a_bullet_without_the_prefix_fails(self, repo: Repo):
        """The message shows the form to write."""
        repo.spec("- REQ-001-01: It MUST work.")
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


class TestMarkers:
    """Continuation lines and the untested and planned markers."""

    def test_a_marker_on_a_continuation_line_counts(self, repo: Repo):
        """Long bullets wrap; the marker can be on the last line."""
        repo.spec("- T-REQ-001-01: It MUST work\n  for a long while. ⚠ untested")
        requirement = requirements(repo)[0]
        assert requirement.untested and not requirement.planned
        assert requirement.text == "It MUST work for a long while. ⚠ untested"

    def test_planned(self, repo: Repo):
        """`(planned: step 3b)` marks a requirement a later step delivers."""
        repo.spec("- T-REQ-001-01: Later. (planned: step 3b)")
        assert requirements(repo)[0].planned

    def test_planned_and_untested_together_is_a_problem(self, repo: Repo):
        """A requirement is either waiting for a step or untested, not both."""
        repo.spec("- T-REQ-001-01: Later. (planned: step 7) ⚠ untested")
        assert_problems(repo, "T-REQ-001-01 is both planned and untested")

    def test_a_nested_bullet_is_not_glued_to_the_one_above(self, repo: Repo):
        """It ends the previous requirement's text instead of extending it."""
        repo.spec("- T-REQ-001-01: Real.\n  - T-REQ-001-02: nested (planned: step 2)")
        found = requirements(repo)
        assert [r.id for r in found] == ["T-REQ-001-01"]
        assert not found[0].planned

    def test_a_blank_line_ends_the_bullet(self, repo: Repo):
        """Indented text after a blank line is not the bullet's."""
        repo.spec("- T-REQ-001-01: Real.\n\n  (planned: step 2)")
        assert not requirements(repo)[0].planned


class TestRetired:
    """Retired requirements."""

    def test_only_retired_with_a_stop_retires_a_requirement(self, repo: Repo):
        """Text that merely starts with the word is still a live requirement."""
        repo.spec(
            "- T-REQ-001-01: Retired: gone.\n- T-REQ-001-02: Retired later, maybe.\n- T-REQ-001-03: Retired. Gone."
        )
        assert [r.retired for r in requirements(repo)] == [True, False, True]

    def test_every_requirement_in_a_retired_spec_is_retired(self, repo: Repo):
        """A retired spec keeps its IDs for history only."""
        repo.spec("- T-REQ-001-01: It did work.", status="retired")
        assert requirements(repo)[0].retired


def test_a_fenced_example_is_not_a_requirement(repo: Repo):
    """A code block can show the format, a header line or a bullet, and none of it counts."""
    body = (
        "- T-REQ-001-01: Real.\n\n```markdown\n- T-REQ-001-09: Example\n* T-REQ-1-1 bad\ntests: x\n```\n\n"
        "~~~\n- T-REQ-001-08: Tilde\n~~~"
    )
    repo.spec(body)
    assert_problems(repo)
    assert [r.id for r in requirements(repo)] == ["T-REQ-001-01"]


def test_the_old_checkers_lines_are_reported(repo: Repo):
    """`tests:` and `id-prefix:` moved into the config, and the messages say so."""
    repo.write("specs/000-index.md", "# Index\n\nid-prefix: T\n\n- [001](001-thing.md)\n")
    repo.write("specs/001-thing.md", spec("").replace("status: draft", "status: draft\ntests: tests"))
    assert_problems(
        repo,
        "specs/000-index.md:3: the `id-prefix:` line is gone; set `id-prefix` in the config",
        "specs/001-thing.md:4: the `tests:` line is gone; say which producers may claim this spec in the config",
    )


class TestProblems:
    """The problem format, and control characters."""

    def test_path_line_message(self):
        """With a line and without one."""
        assert str(specs.Problem("a.md", 3, "bad")) == "a.md:3: bad"
        assert str(specs.Problem("a.md", 0, "bad")) == "a.md: bad"
        assert specs.Problem("a.md", 3, "bad").to_json() == {"path": "a.md", "line": 3, "message": "bad"}

    def test_control_characters_are_written_out(self):
        """A newline can't start a `::error::` line in a CI log."""
        problem = specs.Problem("a\n::error::x.md", 1, "m\x1b[31m")
        assert str(problem) == r"a\n::error::x.md:1: m\x1b[31m"
        assert "\n" not in str(problem)

    def test_plain_leaves_ordinary_text_alone(self):
        """Paths with spaces, accents and symbols read as written; other controls are escaped."""
        assert specs.plain("tests/café é/x y.py") == "tests/café é/x y.py"
        assert specs.plain(f"a\tb{chr(0x2028)}c\x7fd\x85") == "a\\tb\\u2028c\\x7fd\\x85"

    def test_a_path_outside_the_root_is_printed_as_given(self, tmp_path: Path):
        """`rel` falls back to the path itself."""
        assert specs.rel(Path("/elsewhere/x.md"), tmp_path) == "/elsewhere/x.md"

    def test_the_example_id_has_the_prefix(self):
        """Messages show an ID in the folder's own form."""
        assert specs.Syntax("SPC").example() == "SPC-REQ-001-01"
        assert specs.Syntax("").example() == "REQ-001-01"
