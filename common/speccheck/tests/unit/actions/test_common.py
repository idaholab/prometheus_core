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

"""What check, verify and report share: reading the inputs, the JSON of a status, and the summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from speccheck import evidence, results
from speccheck.actions import _common
from speccheck.specs import Problem
from tests.unit.conftest import err, make_ctx, make_requirement, make_spec, make_specs, namespace, out


def test_paths_are_made_relative_where_possible(tmp_path: Path):
    """Under the current folder: relative; elsewhere: as given."""
    assert _common._relative(str(tmp_path / "a" / "b.jsonl"), tmp_path) == "a/b.jsonl"
    assert _common._relative("/elsewhere/x.jsonl", tmp_path) == "/elsewhere/x.jsonl"
    assert _common._relocate(Problem(str(tmp_path / "x"), 2, "m"), tmp_path) == Problem("x", 2, "m")


def test_the_arguments():
    """Inputs default to none; `--complete` and `--workflow` are the scope."""
    parser = argparse.ArgumentParser()
    _common.add_inputs(parser)
    _common.add_scope(parser)
    assert vars(parser.parse_args([])) == {"inputs": [], "complete": False, "workflow": None}
    args = parser.parse_args(["a", "b", "--complete", "--workflow", "ci"])
    assert (args.inputs, args.complete, args.workflow) == (["a", "b"], True, "ci")


class TestEvaluate:
    """Reading the inputs relative to where speccheck runs, then `evidence.evaluate`."""

    def test_inputs_are_read_relative_to_the_cwd(self, tmp_path: Path):
        """A relative input is under the cwd; sources and problems come back relative to it."""
        unit = results.ResultsFile(producer="unit", results=[results.Result("t", ["T-REQ-001-01"], "passed")])
        results.write(tmp_path / "r" / "unit.jsonl", unit)
        (tmp_path / "r" / "bad.jsonl").write_text("{\n")
        ctx = make_ctx(tmp_path, specs_set=make_specs("It."))
        evaluation = _common.evaluate(ctx, namespace(inputs=["r", "missing.jsonl"]), runtime=True)
        assert [f.source for f in evaluation.files] == ["r/unit.jsonl"]
        assert [str(p) for p in evaluation.problems] == [
            "missing.jsonl: no such results file or folder",
            "r/bad.jsonl:1: not JSON: Expecting property name enclosed in double quotes",
        ]
        assert evaluation.statuses[0].status == "passed"

    def test_an_absolute_input(self, tmp_path: Path):
        """Used as given."""
        path = tmp_path / "elsewhere" / "u.jsonl"
        results.write(path, results.ResultsFile(producer="unit"))
        ctx = make_ctx(tmp_path / "cwd", specs_set=make_specs())
        assert _common.evaluate(ctx, namespace(inputs=[str(path)]), runtime=False).files[0].source == path.as_posix()

    def test_check_has_no_scope(self, tmp_path: Path):
        """`check`'s arguments have no `--complete`, so nothing is expected to report."""
        ctx = make_ctx(tmp_path, specs_set=make_specs("It."))
        evaluation = _common.evaluate(ctx, argparse.Namespace(inputs=[]), runtime=False)
        assert evaluation.missing == [] and evaluation.statuses[0].status == "unclaimed"


def one_status(status: str = "passed", **ci) -> evidence.Evaluation:
    """An evaluation of one requirement with one result from `unit`."""
    requirement = make_requirement(make_spec())
    source = results.ResultsFile(producer="unit", ci=ci or None)
    result = results.Result("tests/t.py::t", ["T-REQ-001-01"], "passed", file="tests/t.py", line=3)
    found = [evidence.Evidence(result, source)]
    return evidence.Evaluation([evidence.Status(requirement, status, found)], [], ["unit"], [])


@pytest.mark.parametrize(
    ("ci", "url"),
    [
        ({"job_url": "https://j", "run_url": "https://r"}, "https://j"),
        ({"run_url": "https://r"}, "https://r"),
        ({"leg": "3.12"}, ""),
        ({}, ""),
    ],
)
def test_evidence_json_links_the_job_then_the_run(ci, url):
    """The job's link, else the run's, else none."""
    item = one_status(**ci).statuses[0].evidence[0]
    assert _common.evidence_json(item)["url"] == url


def test_statuses_json():
    """Every field of a status and its evidence."""
    body = _common.statuses_json(one_status(leg="3.12", job="unit"))
    assert body == [
        {
            "id": "T-REQ-001-01",
            "spec": "001",
            "status": "passed",
            "text": "It.",
            "evidence": [
                {
                    "test": "tests/t.py::t",
                    "kind": "test",
                    "file": "tests/t.py",
                    "line": 3,
                    "outcome": "passed",
                    "producer": "unit",
                    "leg": "3.12",
                    "job": "unit",
                    "url": "",
                }
            ],
            "waiting_on": [],
        }
    ]


class TestFinish:
    """Printing the result of check or verify, and the exit code."""

    def test_clean(self):
        """0, and one line on stdout naming who reported."""
        ctx = make_ctx()
        assert _common.finish(ctx, "verify", one_status()) == 0
        assert (out(ctx), err(ctx)) == ("speccheck verify: 1 requirement: 1 passed; reported: unit\n", "")

    def test_problems_and_missing_producers(self):
        """1, the problems on stderr, then the summary with who was missing."""
        evaluation = one_status()
        evaluation.problems, evaluation.missing = [Problem("a", 1, "bad")], ["docker"]
        ctx = make_ctx()
        assert _common.finish(ctx, "verify", evaluation) == 1
        assert err(ctx).splitlines() == [
            "a:1: bad",
            "speccheck verify: 1 requirement: 1 passed; reported: unit; missing: docker; 1 problem",
        ]

    def test_nobody_reported(self):
        """Without any producer reported or missing, the summary says neither."""
        evaluation = one_status()
        evaluation.reported = []
        ctx = make_ctx()
        _common.finish(ctx, "check", evaluation)
        assert out(ctx) == "speccheck check: 1 requirement: 1 passed\n"
        evaluation.missing = ["docker"]
        ctx = make_ctx()
        _common.finish(ctx, "check", evaluation)
        assert "reported: none; missing: docker" in out(ctx)

    def test_verbose_lists_every_status(self):
        """Before the summary."""
        ctx = make_ctx(verbose=True)
        _common.finish(ctx, "verify", one_status())
        assert out(ctx).splitlines()[0] == "T-REQ-001-01  passed"

    def test_json(self):
        """One object: counts, requirements and producers; nothing else printed."""
        evaluation = one_status()
        evaluation.problems = [Problem("a", 1, "bad")]
        ctx = make_ctx(json_mode=True, verbose=True)
        assert _common.finish(ctx, "verify", evaluation) == 1
        body = json.loads(out(ctx))
        assert (body["command"], body["ok"], body["counts"]["passed"]) == ("verify", False, 1)
        assert body["requirements"] == _common.statuses_json(evaluation)
        assert body["producers"] == {"reported": ["unit"], "missing": []}
        assert body["problems"] == [{"path": "a", "line": 1, "message": "bad", "code": "problem"}]
        assert err(ctx) == ""
