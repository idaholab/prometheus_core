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

"""Tests for speccheck.py. Standard library only: `python3 -m unittest -v` in this folder."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import speccheck  # noqa: E402

INDEX = "# Index\n\n- [001](001-thing.md)\n"
"""An index that links the one spec most tests write."""


def spec(body: str, *, status: str = "implemented", tests: str = "tests", number: str = "001") -> str:
    """A spec file with the header lines filled in and `body` as its Requirements section."""
    return (
        f"# {number} - Thing\n\nstatus: {status}\nsources: x.py\ntests: {tests}\ndepends-on: none\n\n"
        f"## Requirements\n{textwrap.dedent(body).strip()}\n"
    )


def cites(*ids: str) -> str:
    """A Python test file whose one test cites the IDs in its docstring (the docstring is line 2)."""
    return f'def test_it():\n    """Covers {" ".join(ids)}."""\n'


class Repo:
    """A throwaway repository with a `specs/` folder, a `tests/` folder and a workflows folder."""

    def __init__(self) -> None:
        """Create the folders in a temporary directory."""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        """The repository root."""
        (self.root / "specs").mkdir()
        (self.root / "tests").mkdir()
        (self.root / ".github" / "workflows").mkdir(parents=True)
        self.write("specs/000-index.md", INDEX)

    def write(self, name: str, text: str) -> Path:
        """Write a file under the root and return its path."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def problems(self) -> list[str]:
        """Every problem the checker reports, as `path:line: message` strings."""
        problems, _, _ = speccheck.check(self.root / "specs", self.root)
        return [str(problem) for problem in problems]

    def close(self) -> None:
        """Delete the directory."""
        self._tmp.cleanup()


class CheckerTest(unittest.TestCase):
    """Base class giving each test a fresh repository."""

    def setUp(self) -> None:
        """A fresh repository per test."""
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def assertProblems(self, *fragments: str) -> None:  # noqa: N802 (unittest naming)
        """Exactly one problem per fragment, each containing it, in any order."""
        problems = self.repo.problems()
        self.assertEqual(len(problems), len(fragments), problems)
        for fragment in fragments:
            self.assertTrue(any(fragment in problem for problem in problems), f"{fragment!r} not in {problems}")


class TestCoverage(CheckerTest):
    """Which requirements count as satisfied."""

    def test_a_cited_requirement_passes(self):
        """A test that names the ID satisfies it."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work."))
        self.repo.write("tests/test_x.py", cites("REQ-001-01"))
        self.assertProblems()

    def test_an_uncited_requirement_fails(self):
        """No test and no marker is a problem."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work."))
        self.assertProblems("REQ-001-01 has no citing test")

    def test_untested_and_planned_markers_excuse_a_missing_test(self):
        """Both markers mean "no test yet, on purpose"."""
        body = """
            - REQ-001-01: It MUST work. ⚠ untested
            - REQ-001-02: It MUST work later. (planned: step 3b)
        """
        self.repo.write("specs/001-thing.md", spec(body))
        self.assertProblems()

    def test_a_marker_on_a_cited_requirement_must_go(self):
        """Once a test cites it, the marker is stale."""
        body = """
            - REQ-001-01: It MUST work. ⚠ untested
            - REQ-001-02: It MUST work later. (planned: step 3b)
        """
        self.repo.write("specs/001-thing.md", spec(body))
        self.repo.write("tests/test_x.py", cites("REQ-001-01", "REQ-001-02"))
        self.assertProblems("REQ-001-01 is cited, so remove", "REQ-001-02 is cited, so remove its `(planned")

    def test_planned_and_untested_together_is_a_problem(self):
        """A requirement is either waiting for a step or untested, not both."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: Later. (planned: step 7) ⚠ untested"))
        self.assertProblems("both planned and untested")

    def test_a_draft_spec_is_held_to_the_same_rules(self):
        """Draft only describes the spec; an unplanned, uncited requirement still fails."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work.", status="draft"))
        self.assertProblems("has no citing test")

    def test_a_marker_on_a_continuation_line_counts(self):
        """Long bullets wrap; the marker can be on the last line."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work\n  for a long while. ⚠ untested"))
        self.assertProblems()

    def test_behaviors_are_checked_like_requirements(self):
        """BEH IDs need evidence too."""
        self.repo.write("specs/001-thing.md", spec("- BEH-001-01: GIVEN x WHEN y THEN z."))
        self.assertProblems("BEH-001-01 has no citing test")


class TestRetired(CheckerTest):
    """Retired IDs stay in the spec and are never cited."""

    def test_a_retired_requirement_needs_no_test(self):
        """`Retired.` replaces the text of a requirement that no longer applies."""
        self.repo.write(
            "specs/001-thing.md", spec("- REQ-001-01: Retired. Superseded by REQ-001-02.\n- REQ-001-02: New.")
        )
        self.repo.write("tests/test_x.py", cites("REQ-001-02"))
        self.assertProblems()

    def test_citing_a_retired_requirement_fails(self):
        """A test should cite what replaced it."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: Retired. Gone."))
        self.repo.write("tests/test_x.py", cites("REQ-001-01"))
        self.assertProblems("REQ-001-01 is retired")

    def test_every_requirement_in_a_retired_spec_is_retired(self):
        """A retired spec keeps its IDs for history only."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It did work.", status="retired"))
        self.assertProblems()


class TestCitations(CheckerTest):
    """Where citations may come from."""

    def test_an_unknown_id_fails(self):
        """A typo or a deleted ID."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work."))
        self.repo.write("tests/test_x.py", cites("REQ-001-01", "REQ-001-09"))
        self.assertProblems("REQ-001-09 isn't in any spec")

    def test_a_citation_outside_the_specs_tests_paths_fails(self):
        """Spec 002's tests can't be the evidence for spec 001."""
        self.repo.write("specs/000-index.md", INDEX + "- [002](002-other.md)\n")
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work.", tests="tests/one"))
        self.repo.write("specs/002-other.md", spec("- REQ-002-01: It MUST work.", tests="tests/two", number="002"))
        self.repo.write("tests/one/test_x.py", cites("REQ-001-01"))
        self.repo.write("tests/two/test_y.py", cites("REQ-002-01", "REQ-001-01"))
        self.assertProblems("REQ-001-01 is cited here, outside specs/001-thing.md")

    def test_several_tests_paths(self):
        """`tests:` takes a comma-separated list; any of them can hold the evidence."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One.\n- REQ-001-02: Two.", tests="tests/a, tests/b"))
        self.repo.write("tests/a/test_x.py", cites("REQ-001-01"))
        self.repo.write("tests/b/test_y.py", cites("REQ-001-02"))
        self.assertProblems()

    def test_a_tests_path_that_does_not_exist_fails(self):
        """A moved test folder would otherwise make every citation vanish silently."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It. ⚠ untested", tests="tests/gone"))
        self.assertProblems("`tests:` names tests/gone")

    def test_tests_none(self):
        """A spec with no requirements yet can say `tests: none`."""
        self.repo.write("specs/001-thing.md", spec("", tests="none"))
        self.assertProblems()

    def test_caches_and_binary_files_are_ignored(self):
        """A `.pyc` or a `node_modules` copy can't count as evidence."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work."))
        self.repo.write("tests/node_modules/x.js", "// REQ-001-01\n")
        (self.repo.root / "tests" / "blob.bin").write_bytes(b"\xff\xfeREQ-001-01")
        self.assertProblems("has no citing test")

    def test_a_mention_is_not_a_citation(self):
        """Only a `test_*` docstring or a `# Covers` comment cites; any other mention is just text."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work."))
        source = '''\
            """Module docstring: Covers REQ-001-01."""
            # A plain comment about REQ-001-01.
            NOTE = "Covers REQ-001-01"

            def helper():
                """Covers REQ-001-01."""

            def test_nothing_cited():
                """Checks something else."""
                name = "REQ-001-01"

            def test_no_docstring():
                pass

            def test_expression_first():
                42
        '''
        self.repo.write("tests/test_x.py", textwrap.dedent(source))
        self.assertProblems("REQ-001-01 has no citing test")

    def test_a_covers_comment_in_python_cites(self):
        """`# Covers` works anywhere a comment can go, for tests that can't carry a docstring."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One.\n- REQ-001-02: Two.\n- REQ-001-03: Three."))
        source = "x = 1  # not a citation of REQ-001-03\n# Covers REQ-001-01, REQ-001-02\n"
        self.repo.write("tests/conftest.py", source)
        self.assertProblems("REQ-001-03 has no citing test")

    def test_docstrings_of_async_and_method_tests_cite_on_their_own_line(self):
        """A method in a test class and an async test both count, and the line is the ID's own."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One.\n- REQ-001-02: Two."))
        source = '''\
            class TestThing:
                def test_a(self):
                    """Does a thing.

                    Covers REQ-001-01.
                    """

            async def test_b():
                """Covers REQ-001-02."""
        '''
        self.repo.write("tests/test_x.py", textwrap.dedent(source))
        _, cited, _ = speccheck.check(self.repo.root / "specs", self.repo.root)
        self.assertEqual([c.line for c in cited["REQ-001-01"]], [5])
        self.assertEqual([c.line for c in cited["REQ-001-02"]], [9])

    def test_implements_in_a_test_is_a_problem_not_evidence(self):
        """`Implements` is for a workflow job; in a test it is reported, and never clears the requirement."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One.\n- REQ-001-02: Two.\n- REQ-001-03: Three."))
        self.repo.write(
            "tests/test_x.py", 'def test_a():\n    """Implements REQ-001-01."""\n\n# Implements REQ-001-02\n'
        )
        self.repo.write("tests/check.sh", "# Implements REQ-001-03\n")
        self.assertProblems(
            "REQ-001-01: a test cites with `Covers`",
            "REQ-001-02: a test cites with `Covers`",
            "REQ-001-03: a test cites with `Covers`",
            "REQ-001-01 has no citing test",
            "REQ-001-02 has no citing test",
            "REQ-001-03 has no citing test",
        )

    def test_python_that_does_not_parse_is_a_problem(self):
        """A syntax error would otherwise hide every citation in the file."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It. ⚠ untested"))
        self.repo.write("tests/test_x.py", "def test_x(:\n")
        self.assertProblems("tests/test_x.py: this isn't valid Python")

    def test_other_languages_cite_on_a_covers_line(self):
        """A shell script or TypeScript test has no docstring: `Covers` before the ID."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One.\n- REQ-001-02: Two."))
        self.repo.write("tests/check.sh", "# Covers REQ-001-01\necho REQ-001-02\n")
        self.assertProblems("REQ-001-02 has no citing test")


class TestWorkflows(CheckerTest):
    """Citations in GitHub Actions workflows."""

    WORKFLOW = """\
        name: ci
        on: push
        jobs:
          diff-config:
            # Covers REQ-001-01: the merged config is unchanged.
            runs-on: ubuntu-latest
            steps:
              - run: echo hi
          publish:
            # Implements REQ-001-02
            runs-on: ubuntu-latest
        """
    """A workflow with one checking job and one implementing job."""

    def setUp(self) -> None:
        """A spec whose evidence may come from the workflows folder."""
        super().setUp()
        self.repo.write(
            "specs/001-thing.md", spec("- REQ-001-01: Same.\n- REQ-001-02: Published.", tests=".github/workflows")
        )

    def test_covers_and_implements_comments_in_jobs_count(self):
        """Each kind satisfies the checker and is reported with its job."""
        self.repo.write(".github/workflows/ci.yml", textwrap.dedent(self.WORKFLOW))
        self.assertProblems()
        _, cited, _ = speccheck.check(self.repo.root / "specs", self.repo.root)
        self.assertEqual([(c.kind, c.job) for c in cited["REQ-001-01"]], [("ci", "diff-config")])
        self.assertEqual([(c.kind, c.job) for c in cited["REQ-001-02"]], [("implements", "publish")])

    def test_a_comment_outside_any_job_fails(self):
        """At the top of the file there is no job that would fail when the behaviour breaks."""
        self.repo.write(".github/workflows/ci.yml", "# Covers REQ-001-01\n" + textwrap.dedent(self.WORKFLOW))
        self.assertProblems("must be a comment inside a job")

    def test_a_comment_at_the_job_key_level_fails(self):
        """A comment above a job key is ambiguous, so it must go below the key."""
        workflow = textwrap.dedent(self.WORKFLOW).replace("  publish:", "  # Covers REQ-001-01\n  publish:")
        self.repo.write(".github/workflows/ci.yml", workflow)
        self.assertProblems("must be a comment inside a job")

    def test_an_id_in_a_workflow_needs_a_keyword(self):
        """A bare ID in a step name or a plain comment is not a citation."""
        workflow = textwrap.dedent(self.WORKFLOW).replace("- run: echo hi", "- run: echo REQ-001-01")
        self.repo.write(".github/workflows/ci.yml", workflow)
        self.assertProblems("as a `# Covers ...` or `# Implements ...` comment")

    def test_a_citation_in_a_job_of_another_top_level_key_fails(self):
        """Only `jobs:` holds jobs; `on:` sub-keys are not jobs."""
        workflow = "name: ci\non:\n  push:\n    # Covers REQ-001-01\n    branches: [main]\n"
        self.repo.write(".github/workflows/ci.yml", workflow)
        self.assertProblems(
            "must be a comment inside a job", "REQ-001-01 has no citing test", "REQ-001-02 has no citing test"
        )


class TestFormat(CheckerTest):
    """The shape of the spec files themselves."""

    def test_duplicate_ids_fail(self):
        """IDs are unique across the whole folder."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One. ⚠ untested\n- REQ-001-01: Again. ⚠ untested"))
        self.assertProblems("REQ-001-01 is also at specs/001-thing.md:")

    def test_a_malformed_bullet_fails(self):
        """`REQ-1-1`, a trailing ID or a missing colon."""
        self.repo.write("specs/001-thing.md", spec("- REQ-1-1: Short.\n- REQ-001-02 Missing colon."))
        self.assertProblems("a bullet must read", "a bullet must read")

    def test_an_id_in_the_wrong_spec_fails(self):
        """REQ-002-XX belongs in 002."""
        self.repo.write("specs/001-thing.md", spec("- REQ-002-01: Misplaced. ⚠ untested"))
        self.assertProblems("REQ-002-01 belongs in spec 002")

    def test_header_lines_are_required(self):
        """`status:` and `tests:` must both be there, and status must be a known value."""
        self.repo.write("specs/001-thing.md", "# 001 - Thing\n\nstatus: done\n")
        self.assertProblems("status must be one of", "missing the `tests:` line")

    def test_the_title_must_carry_the_number(self):
        """`# 001 - Name`, so a renamed file shows."""
        self.repo.write("specs/001-thing.md", spec("", tests="none").replace("# 001 -", "# 01 -"))
        self.assertProblems("the first line must be the title")

    def test_file_names_and_the_index(self):
        """Specs are named NNN-name.md and the index lists each one's number (a link or a table row)."""
        self.repo.write("specs/001-thing.md", spec("", tests="none"))
        self.repo.write("specs/002-unlisted.md", spec("", tests="none", number="002"))
        self.repo.write("specs/Notes.md", "x")
        self.assertProblems("the index doesn't list 002 (002-unlisted.md)", "must be named NNN-short-name.md")

    def test_a_missing_index_fails(self):
        """The index is the entry point."""
        (self.repo.root / "specs" / "000-index.md").unlink()
        self.repo.write("specs/001-thing.md", spec("", tests="none"))
        self.assertProblems("needs a 000-index.md")


class TestPrefix(CheckerTest):
    """An `id-prefix:` in the index keeps this folder's IDs apart from another folder's."""

    def prefixed(self, line: str = "id-prefix: BLD") -> None:
        """Give the index an `id-prefix:` line (or whatever `line` says) above its first `##`."""
        self.repo.write("specs/000-index.md", f"# Index\n\n{line}\n\n## Specs\n\n- [001](001-thing.md)\n")

    def test_prefixed_ids_are_cited_and_checked(self):
        """The prefix is part of the ID, in the spec and in the citation."""
        self.prefixed()
        self.repo.write("specs/001-thing.md", spec("- BLD-REQ-001-01: It MUST work.\n- BLD-BEH-001-01: GIVEN x."))
        self.repo.write("tests/test_x.py", cites("BLD-REQ-001-01"))
        self.assertProblems("BLD-BEH-001-01 has no citing test")

    def test_a_bare_id_is_not_this_folders(self):
        """`REQ-001-01` could be the SDK's; it neither cites nor trips the unknown-ID rule."""
        self.prefixed()
        self.repo.write("specs/001-thing.md", spec("- BLD-REQ-001-01: It MUST work."))
        self.repo.write("tests/test_x.py", cites("REQ-001-01 and OTHER-REQ-001-01 and BLD-REQ-001-09"))
        self.assertProblems("BLD-REQ-001-01 has no citing test", "BLD-REQ-001-09 isn't in any spec")

    def test_a_prefixed_id_is_not_a_bare_folders(self):
        """Without a prefix, `BLD-REQ-001-01` isn't read as `REQ-001-01`."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work."))
        self.repo.write("tests/test_x.py", cites("BLD-REQ-001-01"))
        self.assertProblems("REQ-001-01 has no citing test")

    def test_a_bullet_without_the_prefix_fails(self):
        """The message shows the form to write."""
        self.prefixed()
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: It MUST work. ⚠ untested"))
        self.assertProblems("a bullet must read `- BLD-REQ-NNN-XX: text`")

    def test_the_number_check_names_the_whole_id(self):
        """A prefixed ID numbered for another spec says so."""
        self.prefixed()
        self.repo.write("specs/001-thing.md", spec("- BLD-REQ-002-01: Misplaced. ⚠ untested"))
        self.assertProblems("BLD-REQ-002-01 belongs in spec 002")

    def test_a_workflow_citation_carries_the_prefix(self):
        """`# Covers BLD-REQ-...` in a job counts; a bare ID in a comment is ignored."""
        self.prefixed()
        self.repo.write("specs/001-thing.md", spec("- BLD-REQ-001-01: Same.", tests=".github/workflows"))
        workflow = "jobs:\n  check:\n    # Covers BLD-REQ-001-01 (not REQ-001-01)\n    runs-on: x\n"
        self.repo.write(".github/workflows/ci.yml", workflow)
        self.assertProblems()

    def test_a_malformed_prefix_fails(self):
        """Capital letters and digits, starting with a letter."""
        for bad in ("bld", "B-LD", "1BLD", ""):
            with self.subTest(prefix=bad):
                self.prefixed(f"id-prefix: {bad}")
                self.repo.write("specs/001-thing.md", spec("", tests="none"))
                self.assertProblems("id-prefix must be capital letters and digits")

    def test_the_prefix_line_must_come_before_the_first_section(self):
        """An `id-prefix:` in an example further down is prose, not the setting."""
        self.repo.write("specs/000-index.md", "# Index\n\n## Specs\n\nid-prefix: BLD\n\n- [001](001-thing.md)\n")
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: Bare. ⚠ untested"))
        self.assertProblems()


class TestMain(CheckerTest):
    """The command line."""

    def run_main(self, *args: str) -> tuple[int, str, str]:
        """Exit code, stdout and stderr of one run."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = speccheck.main(["--specs", str(self.repo.root / "specs"), "--root", str(self.repo.root), *args])
            except SystemExit as exit_:
                code = int(exit_.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_and_report(self):
        """0 when clean, 1 with the problems on stderr; `--report` lists each ID's evidence."""
        body = "- REQ-001-01: Tested.\n- REQ-001-02: Later. (planned: step 2)\n- REQ-001-03: No. ⚠ untested"
        self.repo.write("specs/001-thing.md", spec(body))
        self.repo.write("tests/test_x.py", cites("REQ-001-01"))
        code, out, err = self.run_main("--report")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("REQ-001-01  test: tests/test_x.py:2", out)
        self.assertIn("REQ-001-02  planned", out)
        self.assertIn("REQ-001-03  untested", out)

        self.repo.write("tests/test_x.py", "# nothing\n")
        code, out, err = self.run_main()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("REQ-001-01 has no citing test", err)
        self.assertIn("speccheck: 1 problem\n", err)

    def test_report_shows_retired_ids_and_ci_jobs(self):
        """A retired ID is listed as such, and a workflow citation names its job."""
        self.repo.write(
            "specs/001-thing.md", spec("- REQ-001-01: Retired. Gone.\n- REQ-001-02: Checked.", tests=".github")
        )
        self.repo.write(".github/workflows/ci.yml", "jobs:\n  check:\n    # Covers REQ-001-02\n    runs-on: x\n")
        code, out, _ = self.run_main("--report")
        self.assertEqual(code, 0)
        self.assertIn("REQ-001-01  retired", out)
        self.assertIn("REQ-001-02  ci: .github/workflows/ci.yml job check:3", out)

    def test_problems_are_counted_in_the_plural(self):
        """ "2 problems", and a path outside the root is printed as given."""
        self.repo.write("specs/001-thing.md", spec("- REQ-001-01: One.\n- REQ-001-02: Two."))
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("speccheck: 2 problems\n", err)
        self.assertEqual(speccheck.rel(Path("/elsewhere/x.md"), self.repo.root), "/elsewhere/x.md")

    def test_a_missing_specs_folder_is_a_usage_error(self):
        """argparse's exit 2."""
        code, _, err = self.run_main("--specs", str(self.repo.root / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("is not a folder", err)


if __name__ == "__main__":
    unittest.main()
