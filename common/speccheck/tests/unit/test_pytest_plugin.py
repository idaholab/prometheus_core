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

"""The pytest plugin, tested by running real inner pytest sessions through `pytester`.

These are the parts that can only fail in a real run: marker levels, the collection check, the
outcome of every kind of test, xdist, and writing the file only when asked.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from speccheck import pytest_plugin, results
from tests.conftest import CONFIG, Repo, spec

INNER_SPEC = """\
- T-REQ-001-01: One.
- T-REQ-001-02: Two.
- T-REQ-001-03: Three.
- T-REQ-001-04: Four.
- T-REQ-001-05: Five.
- T-REQ-001-06: Retired. Gone.
"""
"""The requirements the inner projects claim."""

OUTCOMES_TESTS = """\
import pytest

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")

@pytest.fixture
def broken_setup():
    raise RuntimeError("setup")

@pytest.mark.covers("T-REQ-001-01")
def test_passes():
    pass

@pytest.mark.covers("T-REQ-001-02")
def test_skipped():
    pytest.skip("not today")

@pytest.mark.covers("T-REQ-001-03")
@pytest.mark.xfail(reason="known")
def test_xfailed():
    assert False

@pytest.mark.covers("T-REQ-001-04")
def test_teardown_fails(broken_teardown):
    pass

@pytest.mark.covers("T-REQ-001-05")
def test_deselected_one():
    pass

@pytest.mark.covers("T-REQ-001-05")
def test_setup_fails(broken_setup):
    pass

@pytest.mark.covers("T-REQ-001-05")
@pytest.mark.xfail(reason="known")
def test_xpassed():
    pass

@pytest.mark.covers("T-REQ-001-05")
def test_fails():
    assert False

@pytest.mark.covers("T-REQ-001-05")
@pytest.mark.skipif(True, reason="never")
def test_skipped_in_setup():
    pass

def test_claims_nothing():
    pass
"""
"""An inner test file with one claiming test of every outcome."""


def project(pytester: pytest.Pytester, tests: str = OUTCOMES_TESTS, *, ini: str = "") -> Path:
    """An inner project: config, specs, and a test file. `ini` adds pytest ini options."""
    pytester.makefile(".toml", speccheck=CONFIG)
    pytester.mkdir("specs")
    (pytester.path / "specs" / "000-index.md").write_text("- [001](001-thing.md)\n")
    (pytester.path / "specs" / "001-thing.md").write_text(spec(INNER_SPEC))
    pytester.makeini(f"[pytest]\naddopts = -p no:cacheprovider\n{ini}")
    pytester.makepyfile(test_inner=tests)
    return pytester.path


def outcomes(path: Path) -> dict[str, str]:
    """Test name -> outcome, from a results file."""
    parsed, problems = results.read(path)
    assert problems == []
    return {r.test.split("::")[1]: r.outcome for r in parsed.results}


def test_the_marker_is_registered(pytester: pytest.Pytester):
    """`--strict-markers` accepts `covers` with no config at all, and `--markers` lists it."""
    pytester.makepyfile('import pytest\n@pytest.mark.covers("X")\ndef test_a():\n    pass\n')
    pytester.runpytest("--strict-markers").assert_outcomes(passed=1)
    assert "covers(*ids)" in pytester.runpytest("--markers").stdout.str()


def test_marks_on_every_level_add_up(pytester: pytest.Pytester):
    """Module, class, function and parameter marks, each ID once."""
    tests = """\
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
    project(pytester, tests)
    path = pytester.path / "r.jsonl"
    pytester.runpytest(f"--speccheck-results={path}").assert_outcomes(passed=3)
    parsed, _ = results.read(path)
    covers = {r.test.split("::", 1)[1]: r.covers for r in parsed.results}
    assert covers == {
        "TestThing::test_method": ["T-REQ-001-03", "T-REQ-001-01", "T-REQ-001-02"],
        "test_param[1]": ["T-REQ-001-01"],
        "test_param[2]": ["T-REQ-001-04", "T-REQ-001-01"],
    }


class TestCollectionCheck:
    """With `speccheck_config`, a bad claim fails collection."""

    def test_bad_claims_fail_collection(self, pytester: pytest.Pytester):
        """Malformed, unknown and retired IDs, each with the test and what to do."""
        tests = """\
import pytest

@pytest.mark.covers("T-REQ-1-1")
def test_malformed():
    pass

@pytest.mark.covers("T-REQ-001-09")
def test_unknown():
    pass

@pytest.mark.covers("T-REQ-001-06")
def test_retired():
    pass
"""
        project(pytester, tests, ini="speccheck_config = speccheck.toml\nspeccheck_producer = unit\n")
        run = pytester.runpytest()
        assert run.ret == pytest.ExitCode.USAGE_ERROR
        err = run.stderr.str()
        assert "speccheck: 3 claim(s) the spec folder doesn't allow" in err
        assert "test_inner.py:3: test_inner.py::test_malformed: `T-REQ-1-1` is not an ID of this folder" in err
        assert "test_inner.py::test_unknown: T-REQ-001-09 isn't in any spec" in err
        assert "test_inner.py::test_retired: T-REQ-001-06 is retired; claim what replaced it" in err

    def test_a_producer_limited_to_other_specs(self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
        """SPECCHECK_PRODUCER picks the producer whose `specs` limit applies."""
        project(
            pytester,
            'import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n',
            ini="speccheck_config = speccheck.toml\n",
        )
        (pytester.path / "speccheck.toml").write_text(CONFIG + '\n[producers.other]\nspecs = ["002"]\n')
        monkeypatch.setenv("SPECCHECK_PRODUCER", "other")
        run = pytester.runpytest()
        assert run.ret == pytest.ExitCode.USAGE_ERROR
        assert "which producer `other` may not claim" in run.stderr.str()
        monkeypatch.setenv("SPECCHECK_PRODUCER", "unit")
        pytester.runpytest().assert_outcomes(passed=1)

    def test_a_good_claim_and_no_producer(self, pytester: pytest.Pytester):
        """Without a producer, only the ID itself is checked."""
        project(
            pytester,
            'import pytest\n@pytest.mark.covers("T-REQ-001-01")\ndef test_a():\n    pass\n',
            ini="speccheck_config = speccheck.toml\n",
        )
        pytester.runpytest().assert_outcomes(passed=1)

    @pytest.mark.parametrize(
        ("setup", "message"),
        [
            ("speccheck_config = missing.toml\n", "missing.toml: can't read the config"),
            ("speccheck_config = speccheck.toml\nspeccheck_producer = nobody\n", "producer `nobody` isn't declared"),
            ("speccheck_config = speccheck.toml\nspeccheck_producer = publish\n", "`publish` is a [ci] job"),
        ],
    )
    def test_config_errors(self, pytester: pytest.Pytester, setup: str, message: str):
        """A missing config, an unknown producer, or a CI job as a test run, stop the session."""
        project(pytester, "def test_a():\n    pass\n", ini=setup)
        (pytester.path / "speccheck.toml").write_text(CONFIG + '\n[ci.publish]\ncovers = ["T-REQ-001-01"]\n')
        run = pytester.runpytest()
        assert run.ret == pytest.ExitCode.USAGE_ERROR
        assert message in run.stderr.str()


@pytest.mark.parametrize(
    ("mark", "message"),
    [
        ("pytest.mark.covers()", "`covers` needs at least one ID"),
        ("pytest.mark.covers(3)", "`covers` IDs are strings"),
        ('pytest.mark.covers("")', "`covers` IDs are strings"),
        ('pytest.mark.covers("T-REQ-001-01", why="x")', "`covers` takes IDs only, not keywords (why)"),
    ],
)
def test_malformed_marks_fail_collection(pytester: pytest.Pytester, mark: str, message: str):
    """Even without a config: the mark itself is wrong."""
    pytester.makepyfile(f"import pytest\n@{mark}\ndef test_a():\n    pass\n")
    run = pytester.runpytest()
    assert run.ret == pytest.ExitCode.USAGE_ERROR
    assert message in run.stderr.str()


def test_unconfigured_it_does_nothing(pytester: pytest.Pytester):
    """No config, no results path: nothing is checked or written, and outcomes are pytest's own."""
    project(pytester)
    run = pytester.runpytest("-k", "not deselected_one")
    run.assert_outcomes(passed=3, failed=1, skipped=2, xfailed=1, xpassed=1, errors=2, deselected=1)
    assert sorted(p.name for p in pytester.path.iterdir() if p.suffix == ".jsonl") == []


def test_a_docstring_mention_is_not_a_claim(pytester: pytest.Pytester):
    """Only the marker counts."""
    project(pytester, 'def test_a():\n    """Covers T-REQ-001-01."""\n    # Covers T-REQ-001-02\n')
    path = pytester.path / "r.jsonl"
    pytester.runpytest(f"--speccheck-results={path}").assert_outcomes(passed=1)
    assert results.read(path)[0].results == []


def test_every_outcome_is_recorded(pytester: pytest.Pytester):
    """Each phase merged into one outcome; skipped and deselected tests are written too."""
    project(pytester)
    path = pytester.path / "r.jsonl"
    # Deselecting a test that claims nothing too: it is still not written
    pytester.runpytest(f"--speccheck-results={path}", "-k", "not deselected_one and not claims_nothing")
    assert outcomes(path) == {
        "test_passes": "passed",
        "test_skipped": "skipped",
        "test_xfailed": "xfailed",
        "test_teardown_fails": "error",
        "test_deselected_one": "deselected",
        "test_setup_fails": "error",
        "test_xpassed": "xpassed",
        "test_fails": "failed",
        "test_skipped_in_setup": "skipped",
    }


@pytest.mark.parametrize(
    ("phases", "expected"),
    [
        ([("setup", "passed", False), ("call", "passed", False), ("teardown", "passed", False)], "passed"),
        ([("setup", "passed", False), ("call", "passed", False), ("teardown", "failed", False)], "error"),
        ([("setup", "passed", False), ("call", "passed", False), ("teardown", "skipped", False)], "passed"),
        ([("setup", "failed", False), ("teardown", "passed", False)], "error"),
        ([("setup", "skipped", False), ("teardown", "passed", False)], "skipped"),
        ([("setup", "skipped", True)], "xfailed"),
        ([("setup", "passed", False), ("call", "failed", False), ("teardown", "failed", False)], "error"),
        ([("setup", "passed", True), ("call", "skipped", True)], "xfailed"),
        ([("setup", "passed", True), ("call", "passed", True)], "xpassed"),
    ],
)
def test_phases_merge(phases, expected):
    """Every phase combination: an error in setup or teardown wins; a teardown skip changes nothing."""

    def report(when: str, outcome: str, xfail: bool) -> SimpleNamespace:
        """A fake TestReport for one phase."""
        fake = SimpleNamespace(
            when=when, passed=outcome == "passed", failed=outcome == "failed", skipped=outcome == "skipped"
        )
        if xfail:
            fake.wasxfail = "reason"
        return fake

    outcome = "collected"
    for when, result, xfail in phases:
        outcome = pytest_plugin.merge(outcome, report(when, result, xfail))
    assert outcome == expected


def test_collect_only_writes_collected(pytester: pytest.Pytester):
    """`--collect-only` runs nothing, so every claim is `collected`."""
    project(pytester)
    path = pytester.path / "c.jsonl"
    pytester.runpytest("--collect-only", "-q", f"--speccheck-results={path}")
    assert set(outcomes(path).values()) == {"collected"}


class TestWritingOnlyWhenAsked:
    """The option, the variable, and no file after an interrupted session."""

    def test_the_environment_variable(self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
        """SPECCHECK_RESULTS, relative to where pytest was started, and the producer from SPECCHECK_PRODUCER."""
        project(pytester)
        monkeypatch.setenv("SPECCHECK_RESULTS", "out/r.jsonl")
        monkeypatch.setenv("SPECCHECK_PRODUCER", "unit")
        pytester.runpytest("-q")
        parsed, _ = results.read(pytester.path / "out" / "r.jsonl")
        assert parsed.producer == "unit" and parsed.runner.startswith("pytest ") and parsed.started.endswith("Z")
        assert parsed.ci is None

    def test_the_producer_defaults(self, pytester: pytest.Pytester):
        """From the ini option, else `local`."""
        project(pytester, "def test_a():\n    pass\n", ini="speccheck_producer = unit\n")
        pytester.runpytest("--speccheck-results=a.jsonl")
        assert results.read(pytester.path / "a.jsonl")[0].producer == "unit"
        pytester.makeini("[pytest]\n")
        pytester.runpytest("--speccheck-results=b.jsonl")
        assert results.read(pytester.path / "b.jsonl")[0].producer == "local"

    def test_an_interrupted_session_leaves_no_file(self, pytester: pytest.Pytester):
        """A KeyboardInterrupt mid-run: no file, so verify reports the producer as missing."""
        project(
            pytester, "import pytest\n@pytest.mark.covers('T-REQ-001-01')\ndef test_a():\n    raise KeyboardInterrupt\n"
        )
        # In a subprocess: an in-process KeyboardInterrupt would reach the outer session's tracer too
        run = pytester.runpytest_subprocess("--speccheck-results=r.jsonl")
        assert run.ret == pytest.ExitCode.INTERRUPTED
        assert not (pytester.path / "r.jsonl").exists()

    def test_a_usage_error_leaves_no_file(self, pytester: pytest.Pytester):
        """A bad claim stops the session before it runs, and nothing is written."""
        project(pytester, "import pytest\n@pytest.mark.covers()\ndef test_a():\n    pass\n")
        pytester.runpytest("--speccheck-results=r.jsonl")
        assert not (pytester.path / "r.jsonl").exists()


def test_xdist_writes_once_from_the_controller(pytester: pytest.Pytester):
    """With two workers, one file with every test's real outcome, not a worker's `collected`."""
    project(pytester)
    path = pytester.path / "x.jsonl"
    pytester.runpytest_subprocess("-p", "xdist", "-n", "2", f"--speccheck-results={path}", "-k", "not deselected_one")
    assert outcomes(path) == {
        "test_passes": "passed",
        "test_skipped": "skipped",
        "test_xfailed": "xfailed",
        "test_teardown_fails": "error",
        "test_deselected_one": "deselected",
        "test_setup_fails": "error",
        "test_xpassed": "xpassed",
        "test_fails": "failed",
        "test_skipped_in_setup": "skipped",
    }
    assert [p.name for p in pytester.path.glob("*.jsonl")] == ["x.jsonl"]


def test_a_worker_never_writes(pytester: pytest.Pytester):
    """The write hook returns early on a worker, which has `workerinput`."""
    config = SimpleNamespace(workerinput={})
    recorder = pytest_plugin.Recorder.__new__(pytest_plugin.Recorder)
    recorder.config, recorder.claims = config, {}
    recorder.pytest_sessionfinish(None, 0)  # would fail on getoption if it went on


def test_merging_workers_keeps_the_run_outcome():
    """Every worker collects every test; the one that ran it has the real outcome."""
    recorder = pytest_plugin.Recorder.__new__(pytest_plugin.Recorder)
    recorder.claims = {}
    claim = {"covers": ["X"], "file": "f", "line": 1}

    def node(outcome: str) -> SimpleNamespace:
        """A finished worker that reports one claim."""
        return SimpleNamespace(workeroutput={pytest_plugin.WORKER_KEY: {"t": {**claim, "outcome": outcome}}})

    for outcome in ("collected", "passed", "collected", "deselected"):
        recorder.pytest_testnodedown(node(outcome), None)
    assert recorder.claims["t"]["outcome"] == "passed"
    recorder.pytest_testnodedown(SimpleNamespace(), None)


def test_a_ci_run_writes_the_context(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    """In GitHub Actions the header carries the run, and links to it."""
    project(pytester, "def test_a():\n    pass\n")
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "9",
        "GITHUB_RUN_ATTEMPT": "1",
        "SPECCHECK_LEG": "3.12",
    }.items():
        monkeypatch.setenv(name, value)
    pytester.runpytest("--speccheck-results=r.jsonl")
    header = json.loads((pytester.path / "r.jsonl").read_text().splitlines()[0])
    assert header["ci"]["leg"] == "3.12"
    assert header["ci"]["run_url"] == "https://github.com/o/r/actions/runs/9/attempts/1"


def test_a_skipped_claim_fails_verify_and_a_passing_one_passes(
    pytester: pytest.Pytester, repo: Repo, monkeypatch: pytest.MonkeyPatch
):
    """End to end: an inner run writes the file, and `verify` on it decides the requirement."""
    tests = """\
import os
import pytest

@pytest.mark.covers("T-REQ-001-01")
def test_it():
    if os.environ.get("SKIP_IT"):
        pytest.skip("skipped on purpose")
"""
    project(pytester, tests, ini="speccheck_config = speccheck.toml\nspeccheck_producer = unit\n")
    (pytester.path / "specs" / "001-thing.md").write_text(spec("- T-REQ-001-01: One."))
    repo.root = pytester.path

    pytester.runpytest("--speccheck-results=pass.jsonl").assert_outcomes(passed=1)
    run = repo.run("verify", "--complete", "pass.jsonl")
    assert run.code == 0, run.err
    assert "1 requirement: 1 passed" in run.out

    monkeypatch.setenv("SKIP_IT", "1")
    pytester.runpytest("--speccheck-results=skip.jsonl").assert_outcomes(skipped=1)
    run = repo.run("verify", "--complete", "skip.jsonl")
    assert run.code == 1
    assert "T-REQ-001-01 has no passing result: test_inner.py::test_it skipped in unit" in run.err
