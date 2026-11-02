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


def claims(project: Project, results: str = "r.jsonl") -> dict[str, list[str]]:
    """Test name (after the file) -> the IDs it claims, from a results file."""
    return {line["test"].split("::", 1)[1]: line["covers"] for line in project.results_lines(results)[1:]}


@pytest.mark.covers("SPC-REQ-003-01")
def test_strict_markers_accept_covers(project: Project):
    """A project with --strict-markers and no speccheck settings runs a marked test, and `--markers` lists it."""
    project.ini("", addopts="--strict-markers")
    project.tests('import pytest\n@pytest.mark.covers("ANYTHING")\ndef test_a():\n    pass\n')
    project.pytest().assert_outcomes(passed=1)
    listing = project.pytest("--markers")
    assert listing.ret == 0 and "@pytest.mark.covers(*ids)" in listing.stdout.str()


@pytest.mark.covers("SPC-REQ-003-02")
def test_marks_on_every_level_add_up(project: Project):
    """Module, class, method and parameter marks, each ID once, in the results file."""
    project.spec("- T-REQ-001-01: A.\n- T-REQ-001-02: B.\n- T-REQ-001-03: C.\n- T-REQ-001-04: D.")
    project.tests(
        """\
        import pytest
        pytestmark = pytest.mark.covers("T-REQ-001-01")

        @pytest.mark.covers("T-REQ-001-02")
        class TestThing:
            @pytest.mark.covers("T-REQ-001-03", "T-REQ-001-01")
            def test_method(self):
                pass

        @pytest.mark.parametrize("n", [1, pytest.param(2, marks=pytest.mark.covers("T-REQ-001-04"))])
        def test_param(n):
            pass
        """
    )
    project.pytest("--speccheck-results=r.jsonl").assert_outcomes(passed=3)
    assert claims(project) == {
        "TestThing::test_method": ["T-REQ-001-03", "T-REQ-001-01", "T-REQ-001-02"],
        "test_param[1]": ["T-REQ-001-01"],
        "test_param[2]": ["T-REQ-001-04", "T-REQ-001-01"],
    }


@pytest.mark.covers("SPC-REQ-003-03")
def test_a_bad_claim_fails_collection_with_what_to_do(project: Project):
    """Malformed, unknown, retired and disallowed IDs each stop the session, naming the test."""
    project.write("speccheck.toml", "specs = 'specs'\nid-prefix = 'T'\n[producers.unit]\nspecs = ['002']\n")
    project.spec("- T-REQ-001-01: One.\n- T-REQ-001-02: Retired. Gone.")
    project.ini(CHECKED)
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("T-REQ-1-1")
        def test_malformed():
            pass

        @pytest.mark.covers("T-REQ-001-09")
        def test_unknown():
            pass

        @pytest.mark.covers("T-REQ-001-02")
        def test_retired():
            pass

        @pytest.mark.covers("T-REQ-001-01")
        def test_not_allowed():
            pass
        """
    )
    run = project.pytest()
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    err = run.stderr.str()
    assert "speccheck: 4 claim(s) the spec folder doesn't allow" in err
    assert "test_project.py:3: test_project.py::test_malformed: `T-REQ-1-1` is not an ID of this folder" in err
    assert "test_project.py::test_unknown: T-REQ-001-09 isn't in any spec; check the number" in err
    assert "test_project.py::test_retired: T-REQ-001-02 is retired; claim what replaced it" in err
    assert "test_project.py::test_not_allowed: T-REQ-001-01 is in spec 001, which producer `unit` may not claim" in err


@pytest.mark.covers("SPC-REQ-003-03")
def test_a_good_claim_passes_collection(project: Project):
    """The same check lets a correct claim through, locally, with no results file asked for."""
    project.spec("- T-REQ-001-01: One.")
    project.ini(CHECKED)
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n')
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.covers("SPC-REQ-003-03")
def test_a_configured_run_needs_a_producer(project: Project, monkeypatch: pytest.MonkeyPatch):
    """With `speccheck_config` and no producer, collection fails and names both ways to set one; either works."""
    project.spec("- T-REQ-001-01: One.")
    project.ini("speccheck_config = speccheck.toml\n")
    project.tests('import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n')
    monkeypatch.delenv("SPECCHECK_PRODUCER", raising=False)
    run = project.pytest()
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    err = run.stderr.str()
    assert "no producer set" in err and "`speccheck_producer`" in err and "$SPECCHECK_PRODUCER" in err
    monkeypatch.setenv("SPECCHECK_PRODUCER", "unit")
    project.pytest().assert_outcomes(passed=1)


@pytest.mark.covers("SPC-REQ-003-04")
@pytest.mark.parametrize(
    ("mark", "message"),
    [
        ("pytest.mark.covers()", "`covers` needs at least one ID"),
        ("pytest.mark.covers(3)", "`covers` IDs are strings"),
        ('pytest.mark.covers("T-REQ-001-01", why="x")', "`covers` takes IDs only, not keywords (why)"),
    ],
)
def test_a_malformed_mark_fails_collection(project: Project, mark: str, message: str):
    """Even with no speccheck settings."""
    project.tests(f"import pytest\n@{mark}\ndef test_a():\n    pass\n")
    run = project.pytest()
    assert run.ret == pytest.ExitCode.USAGE_ERROR and message in run.stderr.str()


@pytest.mark.covers("SPC-REQ-003-05")
def test_unconfigured_the_plugin_changes_nothing(project: Project):
    """No config and no results path: a bad ID passes collection, outcomes are pytest's, no file is written."""
    project.tests(
        """\
        import pytest

        @pytest.mark.covers("NOT-AN-ID")
        def test_passes():
            pass

        @pytest.mark.covers("T-REQ-001-01")
        def test_fails():
            assert False

        @pytest.mark.covers("T-REQ-001-01")
        def test_skips():
            pytest.skip("no")
        """
    )
    project.pytest().assert_outcomes(passed=1, failed=1, skipped=1)
    assert not list(project.root.rglob("*.jsonl"))


@pytest.mark.covers("SPC-REQ-003-06")
def test_a_mention_is_not_a_claim(project: Project):
    """A docstring and a comment that name an ID leave the requirement unclaimed."""
    project.spec("- T-REQ-001-01: One.")
    project.tests('def test_a():\n    """Covers T-REQ-001-01."""\n    # Covers T-REQ-001-01\n')
    project.pytest("--collect-only", "-q", "--speccheck-results=c.jsonl")
    run = project.speccheck("check", "c.jsonl")
    assert run.code == 1 and "T-REQ-001-01 is not claimed" in run.err
