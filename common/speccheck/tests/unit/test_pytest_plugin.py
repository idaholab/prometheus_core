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

from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

from speccheck import pytest_plugin, results
from speccheck.claims import Claim
from speccheck.pytest_plugin import CLAIMS, WORKER_KEY
from tests.unit.conftest import ci_job, make_config, make_specs, producer

FUNCTION = SimpleNamespace(name="test_a")
"""The node a function's own marks sit on (anything that isn't a Module or a Class)."""


def node_of(kind: type, name: str) -> Any:
    """A bare pytest Module or Class node, enough for `isinstance` and `.name`, built without a session."""
    fake = type(f"Fake{kind.__name__}", (kind,), {"name": name, "__doc__": "A node that needs no session."})
    return object.__new__(fake)


def item(
    *marks: pytest.MarkDecorator,
    nodeid: str = "t.py::test_a",
    line: int | None = 2,
    on: Any = FUNCTION,
    params: dict[str, Any] | None = None,
    param_marks: tuple[pytest.MarkDecorator, ...] = (),
    parametrize: tuple[pytest.MarkDecorator, ...] = (),
) -> SimpleNamespace:
    """A fake test item carrying real marks, closest first, at `t.py` line `line` (0-based).

    `marks` sit on `on` (the function by default); `param_marks` are its parameter's own, so it has a
    `callspec` with `params` whenever either `params` or `param_marks` is given.
    """
    own = [m.mark for m in param_marks]
    placed = [(on, m.mark) for m in marks] + [(FUNCTION, m) for m in own]
    found = [mark for _, mark in placed] + [m.mark for m in parametrize]
    fake = SimpleNamespace(
        nodeid=nodeid,
        name=nodeid.split("::")[-1],
        originalname=nodeid.split("::")[-1].split("[")[0],
        parent=SimpleNamespace(nodeid=nodeid.split("::")[0]),
        location=("t.py", line, "test_a"),
        iter_markers=lambda name=None: [m for m in found if name is None or m.name == name],
        iter_markers_with_node=lambda name: [(n, m) for n, m in placed if m.name == name],
    )
    if params is not None or own:
        fake.callspec = SimpleNamespace(marks=own, params=params or {})
    return fake


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
        assert lines[0][0] == "markers" and lines[0][1].startswith("covers(id, how):")
        assert config.stash[CLAIMS] == {}
        recorder, name = registered[0]
        assert isinstance(recorder, pytest_plugin.Recorder) and recorder.claims is config.stash[CLAIMS]
        assert name == f"speccheck-recorder-{id(config)}"
        if worker:
            assert config.workeroutput[WORKER_KEY] is config.stash[CLAIMS]


class TestMarks:
    """Reading the `covers` marks of one test."""

    def test_claims_in_order_collapsed(self):
        """Closest first, as pytest's `iter_markers` gives them, each explanation's whitespace collapsed."""
        found, problems = pytest_plugin.claims_of(item(covers("A", "  one\n two "), covers("B", "three")))
        assert (found, problems) == ([Claim("A", "one two"), Claim("B", "three")], [])
        assert pytest_plugin.claims_of(item()) == ([], [])

    def test_bad_claims_are_left_out(self):
        """A malformed mark, an unusable explanation and a repeated ID are problems; the rest still count."""
        found, problems = pytest_plugin.claims_of(
            item(covers("A"), covers("B", "TODO"), covers("C", "fine"), covers("C", "again"))
        )
        assert found == [Claim("C", "fine")]
        assert problems == [
            '`covers` takes two strings, the ID and how the test proves it, such as covers("T-REQ-001-01", "...")',
            "the explanation for B is a placeholder ('TODO'); say how the test proves it",
            "the test claims C more than once; give one explanation, or split the test",
        ]

    @pytest.mark.parametrize(
        ("mark", "message"),
        [
            (covers("A", "how"), ""),
            (covers(), "`covers` takes two strings, the ID and how the test proves it"),
            (covers("A", "b", "c"), "`covers` takes two strings, the ID and how the test proves it"),
            (covers("A", 3), "`covers` takes two strings; got 'A', 3"),
            (covers("", "how"), "`covers` needs an ID"),
            (
                covers("A", why="x", how="y"),
                "`covers` takes the ID and how the test proves it, not keywords (how, why)",
            ),
        ],
    )
    def test_shape(self, mark, message):
        """Exactly two strings, the first not empty, and no keywords."""
        assert pytest_plugin.shape_problem(mark.mark).startswith(message) and (
            message or not pytest_plugin.shape_problem(mark.mark)
        )

    def test_a_plain_function_or_one_parameter_is_fine(self):
        """A function's own mark with no parameters, and a parameter's own mark in one parametrize."""
        assert pytest_plugin.placement_problem(item(covers("A", "a"))) == ""
        one = item(params={"n": 1}, param_marks=(covers("A", "a"),), parametrize=(pytest.mark.parametrize("n", [1]),))
        assert pytest_plugin.placement_problem(one) == ""

    @pytest.mark.parametrize(
        ("fake", "message"),
        [
            (
                lambda: item(covers("A", "a"), on=node_of(pytest.Module, "t.py")),
                "`covers` is on the module (`pytestmark`); move it onto each test",
            ),
            (
                lambda: item(covers("A", "a"), on=node_of(pytest.Class, "TestThing")),
                "`covers` is on class `TestThing`; move it onto each test",
            ),
            (
                lambda: item(covers("A", "a"), params={"n": 1}, parametrize=(pytest.mark.parametrize("n", [1]),)),
                "`covers` is on the function of a parametrized test",
            ),
            (
                lambda: item(
                    params={"n": 1, "x": 2},
                    param_marks=(covers("A", "a"),),
                    parametrize=(pytest.mark.parametrize("n", [1]), pytest.mark.parametrize("x", [2])),
                ),
                "a claiming test has 2 `parametrize` marks",
            ),
            (
                lambda: item(
                    params={"n": 1, "kind": "a", "other": "b"},
                    param_marks=(covers("A", "a"),),
                    parametrize=(pytest.mark.parametrize("n", [1]),),
                ),
                "a claiming test uses the parametrized fixture `kind`, `other`",
            ),
        ],
    )
    def test_a_mark_that_stands_for_several_tests(self, fake, message):
        """Module, class, a function on a parametrized test, two parametrizes, a parametrized fixture."""
        assert pytest_plugin.placement_problem(fake()).startswith(message)

    @pytest.mark.parametrize(
        ("mark", "names"),
        [
            (pytest.mark.parametrize("a, b", []), ["a", "b"]),
            (pytest.mark.parametrize(("a", "b"), []), ["a", "b"]),
            (pytest.mark.parametrize(["a"], []), ["a"]),
            (pytest.mark.parametrize(argnames="a,b", argvalues=[]), ["a", "b"]),
        ],
    )
    def test_argnames(self, mark, names):
        """Every way `parametrize` takes its names: a comma string, a tuple, a list, or by keyword."""
        assert pytest_plugin._argnames(mark.mark) == names

    def test_function_id_drops_the_parameter(self):
        """So a misplaced mark is reported once per function."""
        assert pytest_plugin._function_id(item(nodeid="t.py::test_a[2]")) == "t.py::test_a"
        bare = SimpleNamespace(nodeid="t.py::test_a", name="test_a", parent=None)
        assert pytest_plugin._function_id(bare) == "t.py::test_a"
        rootless = SimpleNamespace(nodeid="test_a", name="test_a", parent=SimpleNamespace(nodeid=""))
        assert pytest_plugin._function_id(rootless) == "test_a"

    def test_where_is_one_based(self):
        """pytest's 0-based line, plus one; 0 when pytest doesn't know it."""
        assert pytest_plugin._where(item(line=2)) == ("t.py", 3)
        assert pytest_plugin._where(item(line=None)) == ("t.py", 0)

    def test_where_uses_forward_slashes(self, monkeypatch: pytest.MonkeyPatch):
        """The file is stored with `/` even where the OS separator is `\\`, so results read the same everywhere."""
        monkeypatch.setattr(pytest_plugin, "Path", PureWindowsPath)
        windows = SimpleNamespace(location=("tests\\x.py", 0, "test_a"))
        assert pytest_plugin._where(windows) == ("tests/x.py", 1)


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
        config = fake_config(tmp_path / "ini", ini={"speccheck_config": "speccheck.toml", "speccheck_producer": "unit"})
        check = pytest_plugin._checker(config)
        assert loaded["config"] == tmp_path / "ini" / "speccheck.toml"
        assert loaded["specs"][1] == tmp_path / "ini"
        assert check(Claim("T-REQ-001-01", "h")) == ""
        assert "isn't in any spec" in check(Claim("T-REQ-001-09", "h"))
        assert "is the text of T-REQ-001-01" in check(Claim("T-REQ-001-01", "it"))
        config.inipath = None
        pytest_plugin._checker(config)
        assert loaded["config"] == tmp_path / "ini" / "speccheck.toml"

    def test_the_producer_limits_the_claims(self, tmp_path: Path, loaded: dict, monkeypatch: pytest.MonkeyPatch):
        """From SPECCHECK_PRODUCER first, else the ini option."""
        config = fake_config(tmp_path, ini={"speccheck_config": "c.toml", "speccheck_producer": "unit"})
        assert pytest_plugin._checker(config)(Claim("T-REQ-001-01", "h")) == ""
        monkeypatch.setenv("SPECCHECK_PRODUCER", "other")
        assert "producer `other` may not claim" in pytest_plugin._checker(config)(Claim("T-REQ-001-01", "h"))

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

    def test_no_producer_stops_the_session(self, tmp_path: Path, loaded: dict):
        """A configured run with no producer would skip the which-specs check, so it names both ways to set one."""
        config = fake_config(tmp_path, ini={"speccheck_config": "c.toml"})
        with pytest.raises(pytest.UsageError) as raised:
            pytest_plugin._checker(config)
        assert str(raised.value) == (
            "speccheck: no producer set; set `speccheck_producer` in the ini options or $SPECCHECK_PRODUCER "
            f"(declared in {tmp_path / 'c.toml'}: other, publish, unit)"
        )

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
        """Each claiming test with its claims and place; a test that claims nothing is left out."""
        config = fake_config(tmp_path)
        claims = self.collect(
            config,
            item(covers("A", "how a"), covers("B", "how b")),
            item(nodeid="t.py::test_b"),
            monkeypatch=monkeypatch,
        )
        assert claims == {
            "t.py::test_a": {
                "covers": [{"id": "A", "how": "how a"}, {"id": "B", "how": "how b"}],
                "file": "t.py",
                "line": 3,
                "outcome": "collected",
            }
        }

    def test_without_a_config_ids_are_not_checked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Any string is recorded."""
        claims = self.collect(fake_config(tmp_path), item(covers("anything", "h")), monkeypatch=monkeypatch)
        assert claims["t.py::test_a"]["covers"] == [{"id": "anything", "how": "h"}]

    def test_every_bad_claim_is_listed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Malformed marks, misplaced ones (once per function), checker refusals and repeats, with control characters written out."""
        module = node_of(pytest.Module, "t.py")
        items = [
            item(covers(), nodeid="t.py::test_empty"),
            item(covers("ok", "fine"), covers("bad\n::error::", "b"), nodeid="t.py::test_bad", line=9),
            item(covers("A", "m"), on=module, nodeid="t.py::test_p[1]", params={"n": 1}),
            item(covers("A", "m"), on=module, nodeid="t.py::test_p[2]", params={"n": 2}),
            item(covers("C", "fine"), nodeid="t.py::test_copy", line=20),
        ]
        with pytest.raises(pytest.UsageError) as raised:
            self.collect(
                fake_config(tmp_path),
                *items,
                checker=lambda claim: "" if claim.id in ("ok", "C") else "no",
                monkeypatch=monkeypatch,
            )
        assert str(raised.value).splitlines() == [
            "speccheck: 4 claim(s) the spec folder doesn't allow:",
            't.py:3: t.py::test_empty: `covers` takes two strings, the ID and how the test proves it, such as covers("T-REQ-001-01", "...")',
            "t.py:10: t.py::test_bad: no",
            "t.py:3: t.py::test_p: `covers` is on the module (`pytestmark`); move it onto each test, each with its own explanation",
            "t.py:21: t.py::test_copy: t.py::test_copy gives the same explanation for C as t.py::test_bad does for ok; "
            "each claim says how its own test proves its requirement",
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


CLEAN_ATTEMPT = [("setup", "passed"), ("call", "passed"), ("teardown", "passed")]
"""A second attempt of the same test, as a rerun plugin sends it, that passes."""


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
        # A rerun plugin sends a second setup, call and teardown for the same test: an error stays
        ([("setup", "passed"), ("call", "passed"), ("teardown", "failed")] + CLEAN_ATTEMPT, "error"),
        ([("setup", "failed"), ("teardown", "passed")] + CLEAN_ATTEMPT, "error"),
        ([("setup", "passed"), ("call", "failed"), ("teardown", "passed")] + CLEAN_ATTEMPT, "passed"),
    ],
)
def test_phases_merge(phases, expected):
    """An error in setup or teardown wins, even over a later clean attempt; a teardown skip changes nothing."""
    outcome = "collected"
    for when, result in phases:
        outcome = pytest_plugin.merge(outcome, report(when, result))
    assert outcome == expected


CLAIM = {"covers": [{"id": "T-REQ-001-01", "how": "h"}], "file": "t.py", "line": 3}
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

    def test_written_claims_carry_their_explanations(self, tmp_path: Path):
        """The results file holds each claim's ID and how."""
        recorder = self.recorder(tmp_path, option="r.jsonl")
        recorder.pytest_sessionfinish(None, 0)
        assert results.read(tmp_path / "r.jsonl")[0].results[0].covers == [Claim("T-REQ-001-01", "h")]

    def test_root_is_pytests_root_from_the_repository(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """In CI, pytest's root from `GITHUB_WORKSPACE`; `.` when they're the same folder."""
        (tmp_path / "sub").mkdir()
        recorder = self.recorder(tmp_path / "sub", option=str(tmp_path / "r.jsonl"))
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        recorder.pytest_sessionfinish(None, 0)
        assert results.read(tmp_path / "r.jsonl")[0].root == "sub"
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path / "sub"))
        recorder.pytest_sessionfinish(None, 0)
        assert results.read(tmp_path / "r.jsonl")[0].root == "."

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

    def test_an_unwritable_file_is_a_usage_error(self, tmp_path: Path):
        """A file where the folder should be: pytest reports it as a usage error, not a traceback."""
        (tmp_path / "blocker").write_text("a file")
        recorder = self.recorder(tmp_path, option="blocker/r.jsonl")
        with pytest.raises(pytest.UsageError, match="speccheck: can't write the results file: .*blocker"):
            recorder.pytest_sessionfinish(None, 0)

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
            'import pytest\n@pytest.mark.covers("X", "a passes")\ndef test_a():\n    pass\n'
            '@pytest.mark.covers("Y", "b is left out")\ndef test_b():\n    pass\n'
        )
        pytester.runpytest("--strict-markers", "-k", "not test_b", "--speccheck-results=r.jsonl").assert_outcomes(
            passed=1, deselected=1
        )
        parsed, _ = results.read(pytester.path / "r.jsonl")
        assert [(r.covers, r.outcome) for r in parsed.results] == [
            ([Claim("X", "a passes")], "passed"),
            ([Claim("Y", "b is left out")], "deselected"),
        ]

    def test_a_bad_mark_stops_the_session(self, pytester: pytest.Pytester):
        """The collection hook's UsageError reaches pytest as a usage error."""
        pytester.makepyfile("import pytest\n@pytest.mark.covers()\ndef test_a():\n    pass\n")
        run = pytester.runpytest()
        assert run.ret == pytest.ExitCode.USAGE_ERROR and "`covers` takes two strings" in run.stderr.str()
