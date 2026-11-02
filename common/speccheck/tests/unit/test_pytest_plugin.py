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

"""The pytest plugin's functions and hooks, called directly with fake items, reports and configs.

Two small pytester runs at the end check the wiring the fakes can't: that pytest loads the plugin,
calls its hooks by their names, and stops a session on a bad claim. Every outcome, xdist, and the
CI context in a real run are proven in tests/requirements/test_003 and test_004.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from speccheck import pytest_plugin, results
from speccheck.pytest_plugin import CLAIMS, WORKER_KEY
from tests.unit.conftest import ci_job, make_config, make_specs, producer


def item(*marks: pytest.MarkDecorator, nodeid: str = "t.py::test_a", line: int | None = 2) -> SimpleNamespace:
    """A fake test item carrying real `covers` marks, closest first, at `t.py` line `line` (0-based)."""
    found = [m.mark for m in marks]
    return SimpleNamespace(
        nodeid=nodeid,
        location=("t.py", line, "test_a"),
        iter_markers=lambda name: [m for m in found if m.name == name],
    )


def report(when: str, outcome: str, *, xfail: bool = False, nodeid: str = "t.py::test_a") -> SimpleNamespace:
    """A fake TestReport for one phase."""
    fake = SimpleNamespace(
        nodeid=nodeid, when=when, passed=outcome == "passed", failed=outcome == "failed", skipped=outcome == "skipped"
    )
    if xfail:
        fake.wasxfail = "reason"
    return fake


def fake_config(tmp_path: Path, *, ini: dict[str, str] | None = None, option: str | None = None, **attrs: Any):
    """A fake pytest config: ini values, the `--speccheck-results` option, and an empty claims stash."""
    ini = ini or {}
    return SimpleNamespace(
        getini=lambda name: ini.get(name, ""),
        getoption=lambda name: option,
        invocation_params=SimpleNamespace(dir=tmp_path),
        inipath=tmp_path / "pytest.ini",
        rootpath=tmp_path,
        stash={CLAIMS: {}},
        **attrs,
    )


covers = pytest.mark.covers
"""The marker, for building marks."""


class TestOptions:
    """What the plugin adds to pytest's command line and ini file, and what `configure` sets up."""

    def test_addoption(self):
        """`--speccheck-results`, `speccheck_config` and `speccheck_producer`."""
        added: dict[str, list] = {"options": [], "ini": []}
        group = SimpleNamespace(addoption=lambda *args, **kwargs: added["options"].append(args[0]))
        parser = SimpleNamespace(getgroup=lambda name: group, addini=lambda name, *rest: added["ini"].append(name))
        pytest_plugin.pytest_addoption(parser)
        assert added == {"options": ["--speccheck-results"], "ini": ["speccheck_config", "speccheck_producer"]}

    @pytest.mark.parametrize("worker", [False, True])
    def test_configure(self, tmp_path: Path, worker: bool):
        """The marker line, an empty claims dict, a Recorder; a worker shares its claims in `workeroutput`."""
        lines, registered = [], []
        config = SimpleNamespace(
            addinivalue_line=lambda key, line: lines.append((key, line)),
            stash={},
            pluginmanager=SimpleNamespace(register=lambda plugin, name: registered.append((plugin, name))),
        )
        if worker:
            config.workeroutput = {}
        pytest_plugin.pytest_configure(config)
        assert lines[0][0] == "markers" and lines[0][1].startswith("covers(*ids):")
        assert config.stash[CLAIMS] == {}
        recorder, name = registered[0]
        assert isinstance(recorder, pytest_plugin.Recorder) and recorder.claims is config.stash[CLAIMS]
        assert name == f"speccheck-recorder-{id(config)}"
        if worker:
            assert config.workeroutput[WORKER_KEY] is config.stash[CLAIMS]


class TestMarks:
    """Reading the `covers` marks of one test."""

    def test_ids_add_up_in_order_each_once(self):
        """Closest first, as pytest's `iter_markers` gives them; a repeat is dropped."""
        assert pytest_plugin.ids_of(item(covers("A", "B"), covers("C", "A"))) == ["A", "B", "C"]
        assert pytest_plugin.ids_of(item()) == []

    @pytest.mark.parametrize(
        ("marks", "message"),
        [
            ([covers("A")], ""),
            ([covers()], "`covers` needs at least one ID"),
            ([covers(3)], '`covers` IDs are strings, such as "SPC-REQ-001-01"; got 3'),
            ([covers("")], "`covers` IDs are strings, such as \"SPC-REQ-001-01\"; got ''"),
            ([covers("A", why="x", how="y")], "`covers` takes IDs only, not keywords (how, why)"),
            ([covers("A"), covers()], "`covers` needs at least one ID"),
        ],
    )
    def test_bad_args(self, marks, message):
        """The first malformed mark on any level, or ""."""
        assert pytest_plugin._bad_args(item(*marks)) == message

    def test_where_is_one_based(self):
        """pytest's 0-based line, plus one; 0 when pytest doesn't know it."""
        assert pytest_plugin._where(item(line=2)) == ("t.py", 3)
        assert pytest_plugin._where(item(line=None)) == ("t.py", 0)


class TestChecker:
    """The collection check, built from `speccheck_config`."""

    @pytest.fixture
    def loaded(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        """The config and specs the checker sees, instead of reading files; what it asked for."""
        asked: dict = {}
        cfg = make_config(producer("unit"), producer("other", may_claim=("002",)), ci_job("publish", "T-REQ-001-01"))

        def load(path):
            """Note the path; return the config."""
            asked["config"] = path
            return cfg

        def load_specs(*args):
            """Note the arguments; return one spec of one requirement."""
            asked["specs"] = args
            return make_specs("It.")

        monkeypatch.setattr(pytest_plugin.config_module, "load", load)
        monkeypatch.setattr(pytest_plugin.specs_module, "load", load_specs)
        return asked

    def test_without_a_config_there_is_no_check(self, tmp_path: Path):
        """None, and nothing is read."""
        assert pytest_plugin._checker(fake_config(tmp_path)) is None

    def test_the_config_is_beside_the_ini_file(self, tmp_path: Path, loaded: dict):
        """Relative to the ini file's folder, else the rootdir; the specs relative to the same place."""
        config = fake_config(tmp_path / "ini", ini={"speccheck_config": "speccheck.toml"})
        check = pytest_plugin._checker(config)
        assert loaded["config"] == tmp_path / "ini" / "speccheck.toml"
        assert loaded["specs"][1] == tmp_path / "ini"
        assert check("T-REQ-001-01") == "" and "isn't in any spec" in check("T-REQ-001-09")
        config.inipath = None
        pytest_plugin._checker(config)
        assert loaded["config"] == tmp_path / "ini" / "speccheck.toml"

    def test_the_producer_limits_the_claims(self, tmp_path: Path, loaded: dict, monkeypatch: pytest.MonkeyPatch):
        """From SPECCHECK_PRODUCER first, else the ini option."""
        config = fake_config(tmp_path, ini={"speccheck_config": "c.toml", "speccheck_producer": "unit"})
        assert pytest_plugin._checker(config)("T-REQ-001-01") == ""
        monkeypatch.setenv("SPECCHECK_PRODUCER", "other")
        assert "producer `other` may not claim" in pytest_plugin._checker(config)("T-REQ-001-01")

    @pytest.mark.parametrize(
        ("name", "message"),
        [
            ("nobody", "speccheck: producer `nobody` isn't declared in {path} (declared: other, publish, unit)"),
            ("publish", "speccheck: `publish` is a [ci] job in {path}, not a test run"),
        ],
    )
    def test_a_bad_producer_stops_the_session(self, tmp_path: Path, loaded: dict, name, message):
        """An undeclared producer, or a CI job, as a test run."""
        config = fake_config(tmp_path, ini={"speccheck_config": "c.toml", "speccheck_producer": name})
        with pytest.raises(pytest.UsageError) as raised:
            pytest_plugin._checker(config)
        assert str(raised.value) == message.format(path=tmp_path / "c.toml")

    def test_no_producers_declared(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """The message says none are."""
        monkeypatch.setattr(pytest_plugin.config_module, "load", lambda path: make_config())
        monkeypatch.setattr(pytest_plugin.specs_module, "load", lambda *args: make_specs())
        config = fake_config(tmp_path, ini={"speccheck_config": "c.toml", "speccheck_producer": "x"})
        with pytest.raises(pytest.UsageError, match=r"\(declared: none\)"):
            pytest_plugin._checker(config)

    def test_a_config_error_stops_the_session(self, tmp_path: Path):
        """A missing config is a usage error, not a traceback."""
        config = fake_config(tmp_path, ini={"speccheck_config": "missing.toml"})
        with pytest.raises(pytest.UsageError, match="speccheck: .*missing.toml: can't read the config"):
            pytest_plugin._checker(config)


class TestCollection:
    """`pytest_collection_modifyitems`: recording claims, and failing on bad ones."""

    def collect(self, config, *items, checker=None, monkeypatch: pytest.MonkeyPatch) -> dict:
        """Run the hook with `checker` standing in for `_checker`; the claims recorded."""
        monkeypatch.setattr(pytest_plugin, "_checker", lambda config: checker)
        pytest_plugin.pytest_collection_modifyitems(None, config, list(items))
        return config.stash[CLAIMS]

    def test_claims_are_recorded_as_collected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Each claiming test with its IDs and place; a test that claims nothing is left out."""
        config = fake_config(tmp_path)
        claims = self.collect(config, item(covers("A", "B")), item(nodeid="t.py::test_b"), monkeypatch=monkeypatch)
        assert claims == {"t.py::test_a": {"covers": ["A", "B"], "file": "t.py", "line": 3, "outcome": "collected"}}

    def test_without_a_config_ids_are_not_checked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Any string is recorded."""
        claims = self.collect(fake_config(tmp_path), item(covers("anything")), monkeypatch=monkeypatch)
        assert claims["t.py::test_a"]["covers"] == ["anything"]

    def test_every_bad_claim_is_listed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A malformed mark and each disallowed ID, at the test, with control characters written out."""
        items = [
            item(covers(), nodeid="t.py::test_empty"),
            item(covers("ok", "bad\n::error::"), nodeid="t.py::test_bad", line=9),
        ]
        with pytest.raises(pytest.UsageError) as raised:
            self.collect(
                fake_config(tmp_path), *items, checker=lambda id_: "" if id_ == "ok" else "no", monkeypatch=monkeypatch
            )
        assert str(raised.value).splitlines() == [
            "speccheck: 2 claim(s) the spec folder doesn't allow:",
            "t.py:3: t.py::test_empty: `covers` needs at least one ID",
            "t.py:10: t.py::test_bad: no",
        ]


@pytest.mark.parametrize(
    ("when", "outcome", "xfail", "expected"),
    [
        ("call", "passed", False, "passed"),
        ("call", "passed", True, "xpassed"),
        ("call", "skipped", False, "skipped"),
        ("call", "skipped", True, "xfailed"),
        ("call", "failed", False, "failed"),
        ("setup", "passed", False, None),
        ("setup", "failed", False, "error"),
        ("setup", "skipped", False, "skipped"),
        ("setup", "skipped", True, "xfailed"),
        ("teardown", "passed", False, None),
        ("teardown", "failed", False, "error"),
    ],
)
def test_phase_outcome(when, outcome, xfail, expected):
    """What one phase says: a passing setup or teardown says nothing."""
    assert pytest_plugin.phase_outcome(report(when, outcome, xfail=xfail)) == expected


@pytest.mark.parametrize(
    ("phases", "expected"),
    [
        ([("setup", "passed"), ("call", "passed"), ("teardown", "passed")], "passed"),
        ([("setup", "passed"), ("call", "passed"), ("teardown", "failed")], "error"),
        ([("setup", "passed"), ("call", "passed"), ("teardown", "skipped")], "passed"),
        ([("setup", "failed"), ("teardown", "passed")], "error"),
        ([("setup", "skipped"), ("teardown", "passed")], "skipped"),
        ([("setup", "passed"), ("call", "failed"), ("teardown", "failed")], "error"),
        ([("setup", "failed"), ("teardown", "skipped")], "error"),
    ],
)
def test_phases_merge(phases, expected):
    """An error in setup or teardown wins; a teardown skip changes nothing."""
    outcome = "collected"
    for when, result in phases:
        outcome = pytest_plugin.merge(outcome, report(when, result))
    assert outcome == expected


CLAIM = {"covers": ["T-REQ-001-01"], "file": "t.py", "line": 3}
"""One recorded claim, without its outcome."""


class TestRecorder:
    """The session's hooks, on a fake config."""

    def recorder(self, tmp_path: Path, **kwargs) -> pytest_plugin.Recorder:
        """A Recorder on a fake config holding one claim, still `collected`."""
        recorder = pytest_plugin.Recorder(fake_config(tmp_path, **kwargs))
        recorder.claims["t.py::test_a"] = {**CLAIM, "outcome": "collected"}
        return recorder

    def test_deselected(self, tmp_path: Path):
        """A deselected claiming test is marked; one that claims nothing is ignored."""
        recorder = self.recorder(tmp_path)
        recorder.pytest_deselected([item(), item(nodeid="other")])
        assert recorder.claims["t.py::test_a"]["outcome"] == "deselected" and "other" not in recorder.claims

    def test_logreport_merges_each_phase(self, tmp_path: Path):
        """Into the claiming test's outcome; another test's report changes nothing."""
        recorder = self.recorder(tmp_path)
        for phase in (report("setup", "passed"), report("call", "failed"), report("call", "passed", nodeid="other")):
            recorder.pytest_runtest_logreport(phase)
        assert recorder.claims["t.py::test_a"]["outcome"] == "failed" and "other" not in recorder.claims

    def test_merging_workers_keeps_the_run_outcome(self, tmp_path: Path):
        """Every worker collects every test; the one that ran it has the real outcome; deselected beats collected."""
        recorder = self.recorder(tmp_path)

        def node(nodeid: str, outcome: str) -> SimpleNamespace:
            """A finished worker that reports one claim."""
            return SimpleNamespace(workeroutput={WORKER_KEY: {nodeid: {**CLAIM, "outcome": outcome}}})

        for outcome in ("deselected", "collected", "passed", "collected", "deselected"):
            recorder.pytest_testnodedown(node("t.py::test_a", outcome), None)
        assert recorder.claims["t.py::test_a"]["outcome"] == "passed"
        recorder.pytest_testnodedown(node("t.py::new", "collected"), None)
        assert recorder.claims["t.py::new"]["outcome"] == "collected"
        recorder.pytest_testnodedown(SimpleNamespace(), None)  # a worker that crashed has no workeroutput

    def test_sessionfinish_writes_the_file(self, tmp_path: Path):
        """Sorted by test, with the producer from the ini option, the runner and the start time."""
        recorder = self.recorder(tmp_path, option="out/r.jsonl", ini={"speccheck_producer": "unit"})
        recorder.claims["a.py::test_first"] = {**CLAIM, "outcome": "passed"}
        recorder.pytest_sessionstart(None)
        recorder.pytest_sessionfinish(None, pytest.ExitCode.TESTS_FAILED)
        parsed, problems = results.read(tmp_path / "out" / "r.jsonl")
        assert problems == []
        assert (parsed.producer, parsed.ci, parsed.started) == ("unit", None, recorder.started)
        assert parsed.runner == f"pytest {pytest.__version__}" and parsed.started.endswith("Z")
        assert [(r.test, r.outcome, r.file, r.line) for r in parsed.results] == [
            ("a.py::test_first", "passed", "t.py", 3),
            ("t.py::test_a", "collected", "t.py", 3),
        ]

    def test_the_producer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """SPECCHECK_PRODUCER, else the ini option, else `local`; the CI context from the environment."""
        recorder = self.recorder(tmp_path, option="a.jsonl")
        recorder.pytest_sessionfinish(None, 0)
        assert results.read(tmp_path / "a.jsonl")[0].producer == "local"
        monkeypatch.setenv("SPECCHECK_PRODUCER", "env")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        recorder.pytest_sessionfinish(None, 0)
        parsed = results.read(tmp_path / "a.jsonl")[0]
        assert parsed.producer == "env" and parsed.ci is not None

    @pytest.mark.parametrize("status", list(pytest_plugin.NO_WRITE))
    def test_no_file_after_an_unfinished_session(self, tmp_path: Path, status):
        """Interrupted, crashed or a usage error: the run proves nothing."""
        self.recorder(tmp_path, option="r.jsonl").pytest_sessionfinish(None, status)
        assert list(tmp_path.iterdir()) == []

    def test_no_file_when_not_asked_or_on_a_worker(self, tmp_path: Path):
        """Without a path, or on an xdist worker, which has `workerinput`."""
        self.recorder(tmp_path).pytest_sessionfinish(None, 0)
        self.recorder(tmp_path, option="r.jsonl", workerinput={}).pytest_sessionfinish(None, 0)
        assert list(tmp_path.iterdir()) == []


class TestResultsPath:
    """Where the file goes."""

    def test_the_option_then_the_variable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """`--speccheck-results` wins over SPECCHECK_RESULTS; relative to where pytest started."""
        assert pytest_plugin.results_path(fake_config(tmp_path)) is None
        monkeypatch.setenv("SPECCHECK_RESULTS", "env.jsonl")
        assert pytest_plugin.results_path(fake_config(tmp_path)) == tmp_path / "env.jsonl"
        assert pytest_plugin.results_path(fake_config(tmp_path, option="opt.jsonl")) == tmp_path / "opt.jsonl"

    def test_an_absolute_path(self, tmp_path: Path):
        """As given."""
        path = tmp_path / "elsewhere" / "r.jsonl"
        assert pytest_plugin.results_path(fake_config(Path("/start"), option=str(path))) == path


class TestWiring:
    """pytest loads the plugin and calls its hooks by name."""

    def test_a_run_records_its_claims(self, pytester: pytest.Pytester):
        """The marker is registered, and a real session writes its claims with their outcomes."""
        pytester.makepyfile(
            'import pytest\n@pytest.mark.covers("X")\ndef test_a():\n    pass\n'
            '@pytest.mark.covers("Y")\ndef test_b():\n    pass\n'
        )
        pytester.runpytest("--strict-markers", "-k", "not test_b", "--speccheck-results=r.jsonl").assert_outcomes(
            passed=1, deselected=1
        )
        parsed, _ = results.read(pytester.path / "r.jsonl")
        assert [(r.covers, r.outcome) for r in parsed.results] == [(["X"], "passed"), (["Y"], "deselected")]

    def test_a_bad_mark_stops_the_session(self, pytester: pytest.Pytester):
        """The collection hook's UsageError reaches pytest as a usage error."""
        pytester.makepyfile("import pytest\n@pytest.mark.covers()\ndef test_a():\n    pass\n")
        run = pytester.runpytest()
        assert run.ret == pytest.ExitCode.USAGE_ERROR and "`covers` needs at least one ID" in run.stderr.str()
