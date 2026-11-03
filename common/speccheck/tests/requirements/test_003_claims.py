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

from tests.requirements.conftest import EXPECTED, OUTCOMES, Project, outcomes

CHECKED = "speccheck_config = speccheck.toml\nspeccheck_producer = unit\n"
"""Ini options that turn on the collection check."""


def claims(project: Project, results: str = "r.jsonl") -> dict[str, list[dict[str, str]]]:
    """Test name (after the file) -> what it claims, from a results file."""
    return {line["test"].split("::", 1)[1]: line["covers"] for line in project.results_lines(results)[1:]}


def usage_error(project: Project, *args: str) -> str:
    """Run the project's tests asking for a results file, check that collection stopped them, and return stderr.

    Asking for a results file is what turns on the checks that need no specs (003-05).
    """
    run = project.pytest("--speccheck-results=r.jsonl", *args)
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
            "`covers` is on the module (`pytestmark`); move it onto each test, each with its own explanation",
            marks=pytest.mark.covers(
                "SPC-REQ-003-12", "a module-level pytestmark claim stops collection and says to move it onto each test"
            ),
            id="module",
        ),
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01", "c")\nclass TestThing:\n    def test_a(self):\n        pass\n',
            "`covers` is on class `TestThing`; move it onto each test, each with its own explanation",
            marks=pytest.mark.covers("SPC-REQ-003-12", "a claim on a test class stops collection, naming the class"),
            id="class",
        ),
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01", "f")\n@pytest.mark.parametrize("n", [1, 2])\ndef test_a(n):\n    pass\n',
            "`covers` is on the function of a parametrized test; put the claim on each pytest.param(..., marks=...) of one @pytest.mark.parametrize, each with its own explanation",
            marks=pytest.mark.covers(
                "SPC-REQ-003-12",
                "a function claim on a test with two parameters stops collection once, saying to claim per pytest.param",
            ),
            id="parametrized-function",
        ),
        pytest.param(
            '@pytest.mark.parametrize("x", [1])\n'
            '@pytest.mark.parametrize("n", [pytest.param(1, marks=pytest.mark.covers("T-REQ-001-01", "p"))])\n'
            "def test_a(n, x):\n    pass\n",
            "a claiming test has 2 `parametrize` marks; put the claim on each pytest.param(..., marks=...) of one @pytest.mark.parametrize, each with its own explanation",
            marks=pytest.mark.covers(
                "SPC-REQ-003-12", "a claim in one of two stacked parametrize decorators stops collection"
            ),
            id="two-parametrizes",
        ),
        pytest.param(
            '@pytest.fixture(params=["a", "b"])\ndef kind(request):\n    return request.param\n'
            '@pytest.mark.parametrize("n", [pytest.param(1, marks=pytest.mark.covers("T-REQ-001-01", "p"))])\n'
            "def test_a(n, kind):\n    pass\n",
            "a claiming test uses the parametrized fixture `kind`; put the claim on each pytest.param(..., marks=...) of one @pytest.mark.parametrize, each with its own explanation",
            marks=pytest.mark.covers(
                "SPC-REQ-003-12",
                "a claiming test that takes a fixture with params= stops collection, naming the fixture",
            ),
            id="parametrized-fixture",
        ),
        pytest.param(
            '@pytest.fixture(params=["a", "b"])\ndef kind(request):\n    return request.param\n'
            '@pytest.mark.covers("T-REQ-001-01", "f")\n'
            "def test_a(kind):\n    pass\n",
            "`covers` is on the function of a parametrized test; put the claim on each pytest.param(..., marks=...) of one @pytest.mark.parametrize, each with its own explanation",
            marks=pytest.mark.covers(
                "SPC-REQ-003-12",
                "a plain function claim on a test whose only parameters come from a params= fixture stops collection, saying where the claim goes",
            ),
            id="plain-function-with-parametrized-fixture",
        ),
    ],
)
def test_a_mark_that_would_stand_for_several_tests_fails(project: Project, source: str, message: str):
    """With a results file asked for but no speccheck settings, reported once per test function, not per parameter."""
    project.tests("import pytest\n" + source)
    err = usage_error(project)
    assert message in err
    assert "speccheck: 1 claim(s)" in err


def refused_claims(project: Project) -> str:
    """Four inner tests claiming a malformed, an unknown, a retired and a disallowed ID; return the error."""
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
    return usage_error(project)


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "four inner tests claiming malformed, unknown, retired and disallowed IDs stop collection with one message each, naming the test and the ID",
)
def test_a_bad_claim_fails_collection(project: Project):
    """Malformed, unknown, retired and disallowed IDs each stop the session, naming the test and the ID."""
    err = refused_claims(project)
    assert "speccheck: 4 claim(s) the spec folder doesn't allow" in err
    assert "test_project.py:3: test_project.py::test_malformed: `T-REQ-1-1`" in err
    assert "test_project.py::test_unknown: T-REQ-001-09" in err
    assert "test_project.py::test_retired: T-REQ-001-02" in err
    assert "test_project.py::test_not_allowed: T-REQ-001-01" in err


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "with the check on and no results path, an inner test claiming an unknown ID stops collection as a usage error, naming the test and the ID, and writes no file",
)
def test_the_check_needs_no_results_file(project: Project):
    """The configuration alone turns the check on; asking for a results file is not what does it."""
    project.spec("- T-REQ-001-01: One.")
    project.ini(CHECKED)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-09", "unknown")\ndef test_a():\n    pass\n')
    run = project.pytest()
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    assert "test_project.py::test_a: T-REQ-001-09 isn't in any spec" in run.stderr.str()
    assert not list(project.root.rglob("*.jsonl"))


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "with the check on, an inner test claiming a requirement of a spec whose status is retired stops collection, naming the test and the ID",
)
def test_a_claim_in_a_retired_spec_fails_collection(project: Project):
    """A requirement is retired when its whole spec is, not only when its bullet says so."""
    project.spec("- T-REQ-001-01: One.", status="retired")
    project.ini(CHECKED)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "it passes")\ndef test_a():\n    pass\n')
    run = project.pytest()
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    assert "test_project.py::test_a: T-REQ-001-01 is retired; claim what replaced it" in run.stderr.str()


@pytest.mark.covers(
    "SPC-REQ-003-13",
    "the four refusal messages show the ID form, the spec to add to, to claim the replacement, and the producers specs key",
)
def test_a_refused_claim_says_how_to_fix_it(project: Project):
    """Each message ends with what to do about that kind of ID."""
    err = refused_claims(project)
    assert "`T-REQ-1-1` is not an ID of this folder; IDs read like `T-REQ-001-01`" in err
    assert "T-REQ-001-09 isn't in any spec; check the number, or add it to spec 001" in err
    assert "T-REQ-001-02 is retired; claim what replaced it" in err
    assert "which producer `unit` may not claim; add it to `producers.unit.specs`" in err


@pytest.mark.covers(
    "SPC-REQ-003-03",
    "with the collection check on and no results path, an inner test claiming a known, allowed ID runs and passes, so a correct claim is let through where the bad ones above are refused",
)
def test_a_good_claim_passes_collection(project: Project):
    """The same check lets a correct claim through, locally, with no results file asked for."""
    project.spec("- T-REQ-001-01: One.")
    project.ini(CHECKED)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "it passes")\ndef test_a():\n    pass\n')
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.covers(
    "SPC-REQ-003-14",
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
                "an inner mark with an ID and no explanation stops collection with the message that covers takes two strings",
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
        pytest.param(
            'pytest.mark.covers(3, "x")',
            "`covers` takes two strings; got 3, 'x'",
            marks=pytest.mark.covers(
                "SPC-REQ-003-04", "an inner mark whose ID is the number 3 stops collection, showing both values"
            ),
            id="id-not-a-string",
        ),
        pytest.param(
            'pytest.mark.covers("T-REQ-001-01", "x", how="y")',
            "`covers` takes the ID and how the test proves it, not keywords (how)",
            marks=pytest.mark.covers(
                "SPC-REQ-003-04", "an inner mark with two strings and a how= keyword stops collection"
            ),
            id="two-strings-and-a-keyword",
        ),
    ],
)
def test_a_malformed_mark_fails_collection(project: Project, mark: str, message: str):
    """With a results file asked for but no speccheck settings."""
    project.tests(f"import pytest\n@{mark}\ndef test_a():\n    pass\n")
    assert message in usage_error(project)


@pytest.mark.covers(
    "SPC-REQ-003-05",
    "with no speccheck settings, a nonsense ID, a one-argument mark and a TODO explanation collect, and the inner run "
    "reports pytest's own passed, failed and skipped, writing no file",
)
def test_unconfigured_the_plugin_changes_nothing(project: Project):
    """No config and no results path: no claim is checked, outcomes are pytest's, no file is written.

    Run with nothing asked for, unlike `usage_error`, which always asks for a results file.
    """
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("NOT-AN-ID", "passes")
        def test_passes():
            pass

        @pytest.mark.covers("T-REQ-001-01")
        def test_fails():
            assert False

        @pytest.mark.covers("T-REQ-001-01", "TODO")
        def test_skips():
            pytest.skip("no")
        """
    )
    project.pytest().assert_outcomes(passed=1, failed=1, skipped=1)
    assert not list(project.root.rglob("*.jsonl"))


@pytest.mark.covers(
    "SPC-REQ-003-05",
    "with no speccheck settings and no results file, a class-level mark, a repeated ID and a repeated explanation all collect and run, with pytest's own passed and failed",
)
def test_unconfigured_nothing_is_checked_even_what_a_results_file_would_refuse(project: Project):
    """Placement, a repeated claim and a repeated explanation are failures only once a results file is asked for."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "the class")
        class TestThing:
            def test_a(self):
                pass

        @pytest.mark.covers("T-REQ-001-02", "first")
        @pytest.mark.covers("T-REQ-001-02", "second")
        def test_twice():
            assert False

        @pytest.mark.covers("T-REQ-001-03", "same words")
        def test_one():
            pytest.skip("no")

        @pytest.mark.covers("T-REQ-001-04", "same words")
        def test_two():
            pass
        """
    )
    project.pytest().assert_outcomes(passed=2, failed=1, skipped=1)
    assert not list(project.root.rglob("*.jsonl"))


@pytest.mark.covers(
    "SPC-REQ-003-05",
    "with only a results file asked for, a claim of an ID that no spec has is accepted and written as passed, because claims are not compared with any spec",
)
def test_results_only_never_compares_ids_with_a_spec(project: Project):
    """An unknown ID, a retired one and one a producer may not claim all collect: there is no config to say."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Retired. Gone.")
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-009-09", "an ID that no spec has")
        def test_unknown():
            pass

        @pytest.mark.covers("T-REQ-001-02", "an ID that is retired")
        def test_retired():
            pass

        @pytest.mark.covers("NOT-AN-ID", "an ID of no form")
        def test_nonsense():
            pass
        """
    )
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=3)
    assert outcomes(project, "r.jsonl") == {
        "test_unknown": "passed",
        "test_retired": "passed",
        "test_nonsense": "passed",
    }


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01", "a")\n@pytest.mark.covers("T-REQ-001-01", "b")\ndef test_a():\n    pass\n',
            "the test claims T-REQ-001-01 more than once",
            marks=pytest.mark.covers(
                "SPC-REQ-003-05", "with only a results file asked for, a test claiming one ID twice stops collection"
            ),
            id="repeated-id",
        ),
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01", "same words")\ndef test_a():\n    pass\n'
            '@pytest.mark.covers("T-REQ-001-02", "Same  words.")\ndef test_b():\n    pass\n',
            "gives the same explanation for T-REQ-001-02 as test_project.py::test_a does for T-REQ-001-01",
            marks=pytest.mark.covers(
                "SPC-REQ-003-05",
                "with only a results file asked for, two tests giving one explanation in other case and spacing stop collection",
            ),
            id="repeated-explanation",
        ),
        pytest.param(
            '@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n',
            "`covers` takes two strings",
            marks=pytest.mark.covers(
                "SPC-REQ-003-05", "with only a results file asked for, a one-argument mark stops collection"
            ),
            id="malformed-mark",
        ),
    ],
)
def test_results_only_still_refuses_what_needs_no_spec(project: Project, source: str, message: str):
    """Each of these needs no spec to be judged, so a results file alone is enough to refuse it."""
    project.tests("import pytest\n" + source)
    assert message in usage_error(project)


@pytest.mark.covers(
    "SPC-REQ-003-05",
    "asking only for a results file, an explanation copied from a spec bullet is accepted, while a TODO explanation and a class-level mark still stop collection",
)
def test_unconfigured_only_the_spec_free_checks_run(project: Project):
    """With a results file but no config there are no specs to compare against; the checks that need none run."""
    project.spec("- T-REQ-001-01: The thing MUST work.")
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "The thing MUST work.")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=1)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", "TODO")\ndef test_a():\n    pass\n')
    assert "is a placeholder ('TODO')" in usage_error(project)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "c")\nclass TestThing:\n    def test_a(self):\n        pass\n'
    )
    assert "`covers` is on class `TestThing`; move it onto each test" in usage_error(project)


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
    "SPC-REQ-003-06",
    "beside a test that only mentions two IDs, a test that really claims one is counted, so only the other and the mention are unclaimed",
)
def test_a_real_claim_is_counted_beside_a_mention(project: Project):
    """Without this, 'a mention is not a claim' would also hold if claims were never counted."""
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Two.\n- T-REQ-001-03: Three.")
    project.tests(
        """\
        import pytest

        def test_mentions():
            \"\"\"Covers T-REQ-001-02.\"\"\"
            # Covers T-REQ-001-03

        @pytest.mark.covers("T-REQ-001-01", "the real claim")
        def test_claims():
            pass
        """
    )
    project.ini("speccheck_producer = unit\n")
    project.pytest("--collect-only", "-q", "--speccheck-results=c.jsonl")
    run = project.speccheck("check", "c.jsonl", "--json")
    status = {item["id"]: item["status"] for item in run.json()["requirements"]}
    assert status == {"T-REQ-001-01": "claimed", "T-REQ-001-02": "unclaimed", "T-REQ-001-03": "unclaimed"}


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


@pytest.mark.covers(
    "SPC-REQ-003-08",
    "an explanation of 400 letters separated by runs of three spaces, over 1000 characters raw and 799 once collapsed, is accepted and written collapsed",
)
def test_the_length_is_checked_after_collapsing(project: Project):
    """The limit counts the collapsed text, so padding doesn't push a short explanation over it."""
    raw = "   ".join(["a"] * 400)
    collapsed = " ".join(["a"] * 400)
    assert len(raw) > 1000 and len(collapsed) <= 1000
    project.tests(f"import pytest\n@pytest.mark.covers('T-REQ-001-01', {raw!r})\ndef test_a():\n    pass\n")
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=1)
    assert claims(project)["test_a"] == [{"id": "T-REQ-001-01", "how": collapsed}]


@pytest.mark.covers(
    "SPC-REQ-003-08",
    "a TODO explanation padded with a space and a newline is trimmed before it is checked, so it is refused as a placeholder",
)
def test_padding_is_trimmed_before_the_placeholder_check(project: Project):
    """` TODO\\n` is not the whole text until its ends are trimmed."""
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01", " TODO\\n")\ndef test_a():\n    pass\n')
    assert "the explanation for T-REQ-001-01 is a placeholder ('TODO')" in usage_error(project)


@pytest.mark.parametrize(
    ("how", "message"),
    [
        pytest.param(
            "   \n\t ",
            "the explanation for T-REQ-001-01 is empty",
            marks=[
                pytest.mark.covers(
                    "SPC-REQ-003-17", "an explanation of only spaces, a newline and a tab is empty once collapsed"
                ),
                pytest.mark.covers(
                    "SPC-REQ-003-08",
                    "a whitespace-only explanation collapses to nothing before it is checked, so it is refused as empty",
                ),
            ],
            id="empty",
        ),
        pytest.param(
            "x " * 500 + "y",
            "the explanation for T-REQ-001-01 is 1001 characters; the limit is 1000",
            marks=pytest.mark.covers(
                "SPC-REQ-003-17", "a 1001-character explanation stops collection, giving its length and the limit"
            ),
            id="too-long",
        ),
        pytest.param(
            "  t-req-001-01 ",
            "the explanation for T-REQ-001-01 is just the ID",
            marks=pytest.mark.covers(
                "SPC-REQ-003-17", "an explanation that is the claimed ID in lower case, padded with spaces, is refused"
            ),
            id="the-id",
        ),
        pytest.param(
            "tbd",
            "the explanation for T-REQ-001-01 is a placeholder ('tbd')",
            marks=pytest.mark.covers(
                "SPC-REQ-003-17", "a lower-case tbd is refused as a placeholder, quoted in the message"
            ),
            id="placeholder-tbd",
        ),
        pytest.param(
            "...",
            "the explanation for T-REQ-001-01 is a placeholder ('...')",
            marks=pytest.mark.covers(
                "SPC-REQ-003-17", "three dots as the whole explanation are refused as a placeholder"
            ),
            id="placeholder-dots",
        ),
        pytest.param(
            "FIXME",
            "the explanation for T-REQ-001-01 is a placeholder ('FIXME')",
            marks=pytest.mark.covers("SPC-REQ-003-17", "FIXME as the whole explanation is refused as a placeholder"),
            id="placeholder-fixme",
        ),
        pytest.param(
            "-",
            "the explanation for T-REQ-001-01 is a placeholder ('-')",
            marks=pytest.mark.covers("SPC-REQ-003-17", "a single hyphen as the whole explanation is refused"),
            id="placeholder-hyphen",
        ),
        pytest.param(
            "TODO",
            "the explanation for T-REQ-001-01 is a placeholder ('TODO')",
            marks=pytest.mark.covers("SPC-REQ-003-17", "upper-case TODO as the whole explanation is refused"),
            id="placeholder-upper-todo",
        ),
        pytest.param(
            "\n  ToDo\t\n",
            "the explanation for T-REQ-001-01 is a placeholder ('ToDo')",
            marks=pytest.mark.covers(
                "SPC-REQ-003-17", "a mixed-case ToDo padded with newlines, spaces and a tab is refused once collapsed"
            ),
            id="placeholder-padded",
        ),
        pytest.param(
            "x" * 1001,
            "the explanation for T-REQ-001-01 is 1001 characters; the limit is 1000",
            marks=pytest.mark.covers("SPC-REQ-003-17", "an unbroken 1001-character explanation is refused"),
            id="one-over",
        ),
    ],
)
def test_an_unusable_explanation_fails_collection(project: Project, how: str, message: str):
    """With a results file asked for but no speccheck settings; the message names the test and the ID."""
    project.tests(f"import pytest\n@pytest.mark.covers('T-REQ-001-01', {how!r})\ndef test_a():\n    pass\n")
    err = usage_error(project)
    assert f"test_project.py::test_a: {message}" in err


@pytest.mark.covers("SPC-REQ-003-17", "an explanation of exactly 1000 characters is accepted and written whole")
def test_an_explanation_of_exactly_1000_characters_is_accepted(project: Project):
    """The limit is 1000, so 1000 passes; the 1001 above is refused."""
    project.tests(f"import pytest\n@pytest.mark.covers('T-REQ-001-01', {'x' * 1000!r})\ndef test_a():\n    pass\n")
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=1)
    assert claims(project)["test_a"] == [{"id": "T-REQ-001-01", "how": "x" * 1000}]


@pytest.mark.covers(
    "SPC-REQ-003-17",
    "with a results file asked for, an explanation that only contains a placeholder word, like 'TODO list is cleared', is accepted and written as given",
)
def test_a_placeholder_word_inside_an_explanation_is_fine(project: Project):
    """Only the whole text counts as a placeholder."""
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "TODO list is cleared")\ndef test_a():\n    pass\n'
    )
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=1)
    assert claims(project)["test_a"] == [{"id": "T-REQ-001-01", "how": "TODO list is cleared"}]


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
    "an explanation copying the text of a requirement in a second spec, one the producer may not claim, is refused naming that requirement",
)
def test_an_explanation_copying_a_requirement_in_another_spec_fails(project: Project):
    """'Any requirement in the folder' reaches across specs, including those the producer can't claim."""
    project.write("speccheck.toml", "specs = 'specs'\nid-prefix = 'T'\n[producers.unit]\nspecs = ['001']\n")
    project.write("specs/000-index.md", "# Index\n\n- [001](001-thing.md)\n- [002](002-other.md)\n")
    project.spec("- T-REQ-001-01: One.")
    project.spec("- T-REQ-002-01: The other spec MUST hold.", number="002", name="002-other.md")
    project.ini(CHECKED)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "The other spec must hold")\ndef test_a():\n    pass\n'
    )
    err = usage_error(project)
    assert (
        "test_project.py::test_a: the explanation for T-REQ-001-01 is the text of T-REQ-002-01; "
        "describe how the test proves T-REQ-001-01" in err
    )


@pytest.mark.covers(
    "SPC-REQ-003-09",
    "an explanation equal to the text of a requirement in a spec whose status is retired is accepted",
)
def test_a_retired_specs_requirement_text_is_not_compared(project: Project):
    """A requirement is retired when its spec is, so its text is free to use."""
    project.write("specs/000-index.md", "# Index\n\n- [001](001-thing.md)\n- [002](002-old.md)\n")
    project.spec("- T-REQ-001-01: One.")
    project.spec("- T-REQ-002-01: The old spec MUST hold.", number="002", name="002-old.md", status="retired")
    project.ini(CHECKED)
    project.tests(
        'import pytest\n@pytest.mark.covers("T-REQ-001-01", "The old spec MUST hold.")\ndef test_a():\n    pass\n'
    )
    project.pytest().assert_outcomes(passed=1)


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
    fix = "; give one explanation, or split the test"
    assert f"test_project.py::test_function: the test claims T-REQ-001-01 more than once{fix}" in err
    assert f"test_project.py::test_param[1]: the test claims T-REQ-001-02 more than once{fix}" in err


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


@pytest.mark.covers(
    "SPC-REQ-003-07",
    "an inner run where teardown errors after a failed call is written error, pytest.xfail() in setup is xfailed, and a teardown skip after a failed call stays failed",
)
def test_the_less_common_merges(project: Project):
    """A failed call then a broken teardown; an xfail raised in setup; a skipped teardown after a failed call."""
    project.tests(
        """\
        import pytest

        @pytest.fixture
        def broken_teardown():
            yield
            raise RuntimeError("teardown")

        @pytest.fixture
        def xfails_in_setup():
            pytest.xfail("known problem")

        @pytest.fixture
        def skips_in_teardown():
            yield
            pytest.skip("teardown")

        @pytest.mark.covers("T-REQ-001-01", "inner failed call, then a broken teardown")
        def test_failed_then_broken_teardown(broken_teardown):
            assert False

        @pytest.mark.covers("T-REQ-001-02", "inner xfail raised while setting up")
        def test_xfail_in_setup(xfails_in_setup):
            pass

        @pytest.mark.covers("T-REQ-001-03", "inner failed call, then a teardown that skips")
        def test_failed_then_skipped_teardown(skips_in_teardown):
            assert False
        """
    )
    project.pytest("--speccheck-results=r.jsonl")
    assert outcomes(project, "r.jsonl") == {
        "test_failed_then_broken_teardown": "error",
        "test_xfail_in_setup": "xfailed",
        "test_failed_then_skipped_teardown": "failed",
    }


@pytest.mark.covers(
    "SPC-REQ-003-11",
    "two tests claiming the same ID with the same explanation stop collection, naming both tests and the ID",
)
def test_the_same_id_and_explanation_in_two_tests_fails(project: Project):
    """Not the same claim twice: two tests that happen to claim one ID in the same words."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-001-01", "the file is written")
        def test_a():
            pass

        @pytest.mark.covers("T-REQ-001-01", "The file is written.")
        def test_b():
            pass
        """
    )
    assert (
        "test_project.py::test_b gives the same explanation for T-REQ-001-01 as "
        "test_project.py::test_a does for T-REQ-001-01" in usage_error(project)
    )


@pytest.mark.covers(
    "SPC-REQ-003-16",
    "a --collect-only run of the same inner file writes every claiming test as collected",
)
def test_collect_only_writes_collected(project: Project):
    """Nothing runs, so every claim is `collected`."""
    project.tests(OUTCOMES)
    project.pytest("--collect-only", "-q", "--speccheck-results=c.jsonl")
    assert set(outcomes(project, "c.jsonl").values()) == {"collected"}
    assert len(outcomes(project, "c.jsonl")) == len(EXPECTED)


RERUN_CONFTEST = """\
from _pytest.runner import runtestprotocol


def pytest_runtest_protocol(item, nextitem):
    # What a rerun plugin does: the whole setup, call and teardown again, every report logged
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    for _ in range(2):
        for report in runtestprotocol(item, nextitem=nextitem, log=False):
            item.ihook.pytest_runtest_logreport(report=report)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
"""
"""A conftest that runs every test twice, the way a rerun plugin does."""

RERUN_TESTS = """\
import pytest

ATTEMPTS = []


@pytest.fixture
def breaks_on_the_first_attempt():
    yield
    ATTEMPTS.append(1)
    if len(ATTEMPTS) == 1:
        raise RuntimeError("teardown, first attempt only")


@pytest.mark.covers("T-REQ-001-01", "inner claim 15 of T-REQ-001-01")
def test_error_then_clean(breaks_on_the_first_attempt):
    pass


CALLS = []


@pytest.mark.covers("T-REQ-001-01", "inner claim 17 of T-REQ-001-01")
def test_fails_then_passes():
    CALLS.append(1)
    assert len(CALLS) > 1
"""
"""A teardown error on the first attempt only, and a call that fails once."""


@pytest.mark.covers(
    "SPC-REQ-003-15",
    "a rerun plugin's clean second attempt after a teardown error stays error, and a call that fails then passes is passed",
)
def test_an_error_stays_through_a_rerun(project: Project):
    """A teardown error on attempt 1 stays `error` though attempt 2 is clean; a failed call doesn't stick."""
    project.write("conftest.py", RERUN_CONFTEST)
    project.tests(RERUN_TESTS)
    project.pytest("--speccheck-results=r.jsonl")
    assert outcomes(project, "r.jsonl") == {
        "test_error_then_clean": "error",
        "test_fails_then_passes": "passed",
    }


@pytest.mark.covers(
    "SPC-REQ-003-15",
    "a rerun plugin's clean second attempt after a setup error on the first stays error",
)
def test_a_setup_error_stays_through_a_rerun(project: Project):
    """The error is in setup this time, and the second attempt runs clean all the way through."""
    project.write("conftest.py", RERUN_CONFTEST)
    project.tests(
        """\
        import pytest

        ATTEMPTS = []

        @pytest.fixture
        def breaks_setup_once():
            ATTEMPTS.append(1)
            if len(ATTEMPTS) == 1:
                raise RuntimeError("setup, first attempt only")

        @pytest.mark.covers("T-REQ-001-01", "inner setup error on the first attempt only")
        def test_setup_error_then_clean(breaks_setup_once):
            pass
        """
    )
    project.pytest("--speccheck-results=r.jsonl")
    assert outcomes(project, "r.jsonl") == {"test_setup_error_then_clean": "error"}


@pytest.mark.covers(
    "SPC-REQ-003-07",
    "one inner run with setup and teardown errors, skips in call and setup, xfail and xpass writes each test's merged outcome, and a skip in teardown after a passing call leaves it passed",
)
def test_each_test_gets_one_merged_outcome(project: Project):
    """Setup, call and teardown merged into one outcome per claiming test."""
    project.tests(OUTCOMES)
    project.pytest("--speccheck-results=r.jsonl", "-k", "not test_deselected and not claims_nothing")
    assert outcomes(project, "r.jsonl") == EXPECTED
