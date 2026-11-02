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

"""specs/003-claims.md, through real inner pytest runs of a project's tests."""

from __future__ import annotations

import pytest

from tests.requirements.conftest import Project

CHECKED = "speccheck_config = speccheck.toml\nspeccheck_producer = unit\n"
"""Ini options that turn on the collection check."""


def claims(project: Project, results: str = "r.jsonl") -> dict[str, list[dict[str, str]]]:
    """Test name (after the file) -> what it claims, from a results file."""
    return {line["test"].split("::", 1)[1]: line["covers"] for line in project.results_lines(results)[1:]}


def usage_error(project: Project, *args: str) -> str:
    """Run the project's tests, check that collection stopped them, and return stderr."""
    run = project.pytest(*args)
    assert run.ret == pytest.ExitCode.USAGE_ERROR, run.stdout.str()
    return run.stderr.str()


@pytest.mark.covers(
    "SPC-REQ-003-01",
    "an inner run with --strict-markers passes a marked test, and `pytest --markers` lists covers",
)
def test_strict_markers_accept_covers(project: Project):
    """A project with --strict-markers and no speccheck settings runs a marked test, and `--markers` lists it."""
    project.ini("", addopts="--strict-markers")
    project.tests('import pytest\n@pytest.mark.covers("ANYTHING", "a")\ndef test_a():\n    pass\n')
    project.pytest().assert_outcomes(passed=1)
    listing = project.pytest("--markers")
    assert listing.ret == 0 and "@pytest.mark.covers(id, how)" in listing.stdout.str()


@pytest.mark.covers(
    "SPC-REQ-003-02",
    "a plain function's mark and each pytest.param's marks land on that one test, and an unmarked param claims nothing",
)
def test_a_mark_lands_on_one_test(project: Project):
    """A plain function, and per-parameter marks (one with two claims), each written for their own test only."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "the plain test")
        def test_plain():
            pass

        @pytest.mark.parametrize(
            "n",
            [
                1,
                pytest.param(2, marks=pytest.mark.covers("T-REQ-001-02", "two"), id="two"),
                pytest.param(
                    3,
                    marks=[pytest.mark.covers("T-REQ-001-02", "three"), pytest.mark.covers("T-REQ-001-03", "three too")],
                    id="three",
                ),
            ],
        )
        def test_param(n):
            pass
        """
    )
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=4)
    assert claims(project) == {
        "test_plain": [{"id": "T-REQ-001-01", "how": "the plain test"}],
        "test_param[two]": [{"id": "T-REQ-001-02", "how": "two"}],
        "test_param[three]": [{"id": "T-REQ-001-02", "how": "three"}, {"id": "T-REQ-001-03", "how": "three too"}],
    }


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            'pytestmark = pytest.mark.covers("T-REQ-001-01", "m")\ndef test_a():\n    pass\n',
            "`covers` is on the module (`pytestmark`); move it onto each test",
            marks=pytest.mark.covers(
                "SPC-REQ-003-02", "a module-level pytestmark claim stops collection and says to move it onto each test"
            ),
            id="module",
        ),
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01", "c")\nclass TestThing:\n    def test_a(self):\n        pass\n',
            "`covers` is on class `TestThing`; move it onto each test",
            marks=pytest.mark.covers("SPC-REQ-003-02", "a claim on a test class stops collection, naming the class"),
            id="class",
        ),
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01", "f")\n@pytest.mark.parametrize("n", [1, 2])\ndef test_a(n):\n    pass\n',
            "`covers` is on the function of a parametrized test; put the claim on each pytest.param",
            marks=pytest.mark.covers(
                "SPC-REQ-003-02",
                "a function claim on a test with two parameters stops collection once, saying to claim per pytest.param",
            ),
            id="parametrized-function",
        ),
        pytest.param(
            '@pytest.mark.parametrize("x", [1])\n'
            '@pytest.mark.parametrize("n", [pytest.param(1, marks=pytest.mark.covers("T-REQ-001-01", "p"))])\n'
            "def test_a(n, x):\n    pass\n",
            "a claiming test has 2 `parametrize` marks",
            marks=pytest.mark.covers(
                "SPC-REQ-003-02", "a claim in one of two stacked parametrize decorators stops collection"
            ),
            id="two-parametrizes",
        ),
        pytest.param(
            '@pytest.fixture(params=["a", "b"])\ndef kind(request):\n    return request.param\n'
            '@pytest.mark.parametrize("n", [pytest.param(1, marks=pytest.mark.covers("T-REQ-001-01", "p"))])\n'
            "def test_a(n, kind):\n    pass\n",
            "a claiming test uses the parametrized fixture `kind`",
            marks=pytest.mark.covers(
                "SPC-REQ-003-02",
                "a claiming test that takes a fixture with params= stops collection, naming the fixture",
            ),
            id="parametrized-fixture",
        ),
    ],
)
def test_a_mark_that_would_stand_for_several_tests_fails(project: Project, source: str, message: str):
    """Even with no speccheck settings, and reported once per test function, not per parameter."""
    project.tests("import pytest\n" + source)
    err = usage_error(project)
    assert message in err and "each with its own explanation" in err
    assert "speccheck: 1 claim(s)" in err


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "four inner tests claiming malformed, unknown, retired and disallowed IDs stop collection with one message each, naming the test and the fix",
)
def test_a_bad_claim_fails_collection_with_what_to_do(project: Project):
    """Malformed, unknown, retired and disallowed IDs each stop the session, naming the test."""
    project.write("speccheck.toml", "specs = 'specs'\nid-prefix = 'T'\n[producers.unit]\nspecs = ['002']\n")
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Retired. Gone.")
    project.ini(CHECKED)
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-1-1", "malformed")
        def test_malformed():
            pass

        @pytest.mark.covers("T-REQ-001-09", "unknown")
        def test_unknown():
            pass

        @pytest.mark.covers("T-REQ-001-02", "retired")
        def test_retired():
            pass

        @pytest.mark.covers("T-REQ-001-01", "not allowed")
        def test_not_allowed():
            pass
        """
    )
    err = usage_error(project)
    assert "speccheck: 4 claim(s) the spec folder doesn't allow" in err
    assert "test_project.py:3: test_project.py::test_malformed: `T-REQ-1-1` is not an ID of this folder" in err
    assert "test_project.py::test_unknown: T-REQ-001-09 isn't in any spec; check the number" in err
    assert "test_project.py::test_retired: T-REQ-001-02 is retired; claim what replaced it" in err
    assert "test_project.py::test_not_allowed: T-REQ-001-01 is in spec 001, which producer `unit` may not claim" in err


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "with the collection check on and no results path, an inner test claiming a known, allowed ID runs and passes",
)
def test_a_good_claim_passes_collection(project: Project):
    """The same check lets a correct claim through, locally, with no results file asked for."""
    project.spec("- T-REQ-001-01: One.")
    project.ini(CHECKED)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "it passes")\ndef test_a():\n    pass\n')
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "with speccheck_config set and no producer, collection fails naming the ini option and the variable, and setting SPECCHECK_PRODUCER fixes it",
)
def test_a_configured_run_needs_a_producer(project: Project, monkeypatch: pytest.MonkeyPatch):
    """With `speccheck_config` and no producer, collection fails and names both ways to set one; either works."""
    project.spec("- T-REQ-001-01: One.")
    project.ini("speccheck_config = speccheck.toml\n")
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "it passes")\ndef test_a():\n    pass\n')
    monkeypatch.delenv("SPECCHECK_PRODUCER", raising=False)
    err = usage_error(project)
    assert "no producer set" in err and "`speccheck_producer`" in err and "$SPECCHECK_PRODUCER" in err
    monkeypatch.setenv("SPECCHECK_PRODUCER", "unit")
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.parametrize(
    ("mark", "message"),
    [
        pytest.param(
            "pytest.mark.covers()",
            "`covers` takes two strings, the ID and how the test proves it",
            marks=pytest.mark.covers(
                "SPC-REQ-003-04", "an inner mark with no arguments stops collection as a usage error"
            ),
            id="no-arguments",
        ),
        pytest.param(
            'pytest.mark.covers("T-REQ-001-01")',
            "`covers` takes two strings, the ID and how the test proves it",
            marks=pytest.mark.covers(
                "SPC-REQ-003-04",
                "an inner mark with an ID and no explanation stops collection, showing the two-string form",
            ),
            id="id-only",
        ),
        pytest.param(
            'pytest.mark.covers("T-REQ-001-01", "a", "b")',
            "`covers` takes two strings",
            marks=pytest.mark.covers("SPC-REQ-003-04", "an inner mark with a third argument stops collection"),
            id="three-arguments",
        ),
        pytest.param(
            'pytest.mark.covers("T-REQ-001-01", 3)',
            "`covers` takes two strings; got 'T-REQ-001-01', 3",
            marks=pytest.mark.covers(
                "SPC-REQ-003-04",
                "an inner mark whose explanation is the number 3 stops collection, showing both values",
            ),
            id="not-a-string",
        ),
        pytest.param(
            'pytest.mark.covers("T-REQ-001-01", how="x")',
            "`covers` takes the ID and how the test proves it, not keywords (how)",
            marks=pytest.mark.covers(
                "SPC-REQ-003-04", "an inner mark with a how= keyword stops collection, naming the keyword"
            ),
            id="keyword",
        ),
    ],
)
def test_a_malformed_mark_fails_collection(project: Project, mark: str, message: str):
    """Even with no speccheck settings."""
    project.tests(f"import pytest\n@{mark}\ndef test_a():\n    pass\n")
    assert message in usage_error(project)


@pytest.mark.covers(
    "SPC-REQ-003-05",
    "with no speccheck settings, a nonsense ID collects and the inner run reports pytest's own passed, failed and skipped, writing no file",
)
def test_unconfigured_the_plugin_changes_nothing(project: Project):
    """No config and no results path: a bad ID passes collection, outcomes are pytest's, no file is written."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("NOT-AN-ID", "passes")
        def test_passes():
            pass

        @pytest.mark.covers("T-REQ-001-01", "fails")
        def test_fails():
            assert False

        @pytest.mark.covers("T-REQ-001-01", "skips")
        def test_skips():
            pytest.skip("no")
        """
    )
    project.pytest().assert_outcomes(passed=1, failed=1, skipped=1)
    assert not list(project.root.rglob("*.jsonl"))


@pytest.mark.covers(
    "SPC-REQ-003-05",
    "with no speccheck_config, an explanation copied from a spec bullet is accepted, while a TODO one still stops collection",
)
def test_unconfigured_only_the_spec_free_checks_run(project: Project):
    """Without the config there are no specs to compare against; the checks that need none still run."""
    project.spec("- T-REQ-001-01: The thing MUST work.")
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "The thing MUST work.")\ndef test_a():\n    pass\n'
    )
    project.pytest().assert_outcomes(passed=1)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "TODO")\ndef test_a():\n    pass\n')
    assert "is a placeholder ('TODO')" in usage_error(project)


@pytest.mark.covers(
    "SPC-REQ-003-06",
    "an inner test naming the ID in its docstring and a comment leaves check reporting the requirement unclaimed",
)
def test_a_mention_is_not_a_claim(project: Project):
    """A docstring and a comment that name an ID leave the requirement unclaimed."""
    project.spec("- T-REQ-001-01: One.")
    project.tests('def test_a():\n    """Covers T-REQ-001-01."""\n    # Covers T-REQ-001-01\n')
    project.pytest("--collect-only", "-q", "--speccheck-results=c.jsonl")
    run = project.speccheck("check", "c.jsonl")
    assert run.code == 1 and "T-REQ-001-01 is not claimed" in run.err


@pytest.mark.covers(
    "SPC-REQ-003-08",
    "an explanation split over lines with tabs and runs of spaces is written to the results file as one single-spaced line",
)
def test_whitespace_in_an_explanation_is_collapsed(project: Project):
    """Newlines, tabs and runs of spaces become one space, and the ends are trimmed."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", """\n  writes\tthe file,\n\n   then reads   it  """)\n'
        "def test_a():\n    pass\n"
    )
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=1)
    assert claims(project)["test_a"] == [{"id": "T-REQ-001-01", "how": "writes the file, then reads it"}]


@pytest.mark.parametrize(
    ("how", "message"),
    [
        pytest.param(
            "   \n\t ",
            "the explanation for T-REQ-001-01 is empty",
            marks=pytest.mark.covers(
                "SPC-REQ-003-08", "an explanation of only spaces, a newline and a tab is empty once collapsed"
            ),
            id="empty",
        ),
        pytest.param(
            "x " * 500 + "y",
            "the explanation for T-REQ-001-01 is 1001 characters; the limit is 1000",
            marks=pytest.mark.covers(
                "SPC-REQ-003-08", "a 1001-character explanation stops collection, giving its length and the limit"
            ),
            id="too-long",
        ),
        pytest.param(
            "  t-req-001-01 ",
            "the explanation for T-REQ-001-01 is just the ID",
            marks=pytest.mark.covers(
                "SPC-REQ-003-08", "an explanation that is the claimed ID in lower case, padded with spaces, is refused"
            ),
            id="the-id",
        ),
        pytest.param(
            "tbd",
            "the explanation for T-REQ-001-01 is a placeholder ('tbd')",
            marks=pytest.mark.covers(
                "SPC-REQ-003-08", "a lower-case tbd is refused as a placeholder, quoted in the message"
            ),
            id="placeholder-tbd",
        ),
        pytest.param(
            "...",
            "the explanation for T-REQ-001-01 is a placeholder ('...')",
            marks=pytest.mark.covers(
                "SPC-REQ-003-08", "three dots as the whole explanation are refused as a placeholder"
            ),
            id="placeholder-dots",
        ),
    ],
)
def test_an_unusable_explanation_fails_collection(project: Project, how: str, message: str):
    """Even with no speccheck settings; the message names the test and the ID."""
    project.tests(f"import pytest\n@pytest.mark.covers('T-REQ-001-01', {how!r})\ndef test_a():\n    pass\n")
    err = usage_error(project)
    assert f"test_project.py::test_a: {message}" in err


@pytest.mark.covers(
    "SPC-REQ-003-08",
    "an explanation that only contains a placeholder word, like 'TODO list is cleared', is accepted",
)
def test_a_placeholder_word_inside_an_explanation_is_fine(project: Project):
    """Only the whole text counts as a placeholder."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "TODO list is cleared")\ndef test_a():\n    pass\n'
    )
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.covers(
    "SPC-REQ-003-09",
    "with the check on, explanations copying the claimed and a neighbouring requirement's text, in other case and spacing, are refused by name",
)
def test_an_explanation_that_is_a_requirements_text_fails(project: Project):
    """Any requirement's text, not only the claimed one's, compared ignoring case, whitespace and a final full stop."""
    project.spec("- T-REQ-001-01: The file MUST be written.\n- T-REQ-001-02: The file MUST be read\n  back the same.")
    project.ini(CHECKED)
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "the file must be written")
        def test_own():
            pass

        @pytest.mark.covers("T-REQ-001-01", "THE FILE MUST BE READ BACK   THE SAME.")
        def test_neighbour():
            pass
        """
    )
    err = usage_error(project)
    assert (
        "test_project.py::test_own: the explanation for T-REQ-001-01 is the text of T-REQ-001-01; "
        "describe how the test proves T-REQ-001-01" in err
    )
    assert "test_project.py::test_neighbour: the explanation for T-REQ-001-01 is the text of T-REQ-001-02" in err


@pytest.mark.covers(
    "SPC-REQ-003-09",
    "a retired requirement's text is not compared, so an explanation equal to it is accepted",
)
def test_a_retired_requirements_text_is_not_compared(project: Project):
    """Only requirements that aren't retired count."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Retired: the old file was written here.")
    project.ini(CHECKED)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "Retired: the old file was written here.")\n'
        "def test_a():\n    pass\n"
    )
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.covers(
    "SPC-REQ-003-10",
    "a test with two marks for one ID stops collection, saying to give one explanation or split the test",
)
def test_one_test_claims_an_id_once(project: Project):
    """Two marks on one function, and two in one pytest.param, each fail."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "first part")
        @pytest.mark.covers("T-REQ-001-01", "second part")
        def test_function():
            pass

        @pytest.mark.parametrize(
            "n",
            [pytest.param(1, marks=[pytest.mark.covers("T-REQ-001-02", "p1"), pytest.mark.covers("T-REQ-001-02", "p2")])],
        )
        def test_param(n):
            pass
        """
    )
    err = usage_error(project)
    assert "test_project.py::test_function: the test claims T-REQ-001-01 more than once" in err
    assert "test_project.py::test_param[1]: the test claims T-REQ-001-02 more than once" in err


@pytest.mark.covers(
    "SPC-REQ-003-11",
    "two tests, and two IDs on one test, giving the same explanation in other case and spacing stop collection naming both claims",
)
def test_an_explanation_is_given_once(project: Project):
    """Across tests and across IDs, whatever the case, spacing or final full stop."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "the file is written")
        def test_a():
            pass

        @pytest.mark.covers("T-REQ-001-02", "The  file is WRITTEN.")
        def test_b():
            pass

        @pytest.mark.covers("T-REQ-001-03", "the file is read")
        @pytest.mark.covers("T-REQ-001-04", "the file is read")
        def test_c():
            pass
        """
    )
    err = usage_error(project)
    assert (
        "test_project.py::test_b: test_project.py::test_b gives the same explanation for T-REQ-001-02 as "
        "test_project.py::test_a does for T-REQ-001-01" in err
    )
    # pytest gives a function's marks nearest the function first
    assert (
        "test_project.py::test_c gives the same explanation for T-REQ-001-03 as test_project.py::test_c does for T-REQ-001-04"
        in err
    )
