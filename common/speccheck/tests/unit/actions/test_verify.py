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

"""`speccheck verify`: outcomes count, and `--complete` passes through."""

from __future__ import annotations

import argparse
from pathlib import Path

from speccheck import results
from speccheck.actions import verify
from speccheck.claims import Claim
from tests.unit.conftest import err, make_config, make_ctx, make_specs, namespace, out, producer


def test_the_arguments():
    """Results files, the scope, the job names and the summary."""
    parser = argparse.ArgumentParser()
    verify.add_arguments(parser)
    assert vars(parser.parse_args(["a", "--complete"])) == {
        "inputs": ["a"],
        "complete": True,
        "workflow": None,
        "job_names": None,
        "summary": None,
        "report_url": None,
    }
    args = parser.parse_args(["--summary", "s.md", "--report-url", "https://x", "--job-names", "n.json"])
    assert (args.summary, args.report_url, args.job_names) == ("s.md", "https://x", "n.json")


def write(tmp_path: Path, outcome: str) -> None:
    """unit.jsonl with one claim of T-REQ-001-01."""
    claim = results.Result("t", [Claim("T-REQ-001-01", "t proves it")], outcome)
    results.write(tmp_path / "unit.jsonl", results.ResultsFile(producer="unit", results=[claim]))


def test_a_pass(tmp_path: Path):
    """0, with the summary."""
    write(tmp_path, "passed")
    ctx = make_ctx(tmp_path, specs_set=make_specs("It."))
    assert verify.run(ctx, namespace(inputs=["unit.jsonl"])) == 0
    assert out(ctx) == "speccheck verify: 1 requirement: 1 passed; reported: unit\n"


def test_a_skip_fails(tmp_path: Path):
    """Where `check` would pass, `verify` needs a passing result."""
    write(tmp_path, "skipped")
    ctx = make_ctx(tmp_path, specs_set=make_specs("It."))
    assert verify.run(ctx, namespace(inputs=["unit.jsonl"])) == 1
    assert "T-REQ-001-01 has no passing result: t skipped in unit" in err(ctx)


def test_complete_and_workflow_are_passed_on(tmp_path: Path):
    """A producer of the workflow that didn't report fails `--complete`; one of another workflow doesn't."""
    write(tmp_path, "passed")
    loaded = make_config(producer("unit"), producer("docker", workflows=("other",)))
    ctx = make_ctx(tmp_path, loaded=loaded, specs_set=make_specs("It."))
    assert verify.run(ctx, namespace(inputs=["unit.jsonl"], complete=True)) == 1
    assert "missing: docker" in err(ctx)
    ctx = make_ctx(tmp_path, loaded=loaded, specs_set=make_specs("It."))
    assert verify.run(ctx, namespace(inputs=["unit.jsonl"], complete=True, workflow="ci")) == 0


def test_no_results_files_fail(tmp_path: Path):
    """Nothing read: a problem on the config, naming what was given, whether or not it is complete."""
    (tmp_path / "empty").mkdir()
    ctx = make_ctx(tmp_path, specs_set=make_specs("It."))
    assert verify.run(ctx, namespace(inputs=["empty"])) == 1
    assert "no results files were read (empty), so nothing is proven" in err(ctx)
    ctx = make_ctx(tmp_path, specs_set=make_specs("It."))
    assert verify.run(ctx, namespace()) == 1
    assert "no results files were read (no RESULTS given)" in err(ctx)


def test_the_summary_links_the_report(tmp_path: Path):
    """`--report-url` is linked when it is an artifact of this run's repository."""
    write(tmp_path, "passed")
    env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
    url = "https://github.com/o/r/actions/runs/1/artifacts/2"
    ctx = make_ctx(tmp_path, specs_set=make_specs("It."), env=env)
    assert verify.run(ctx, namespace(inputs=["unit.jsonl"], summary="s.md", report_url=url)) == 0
    assert (
        tmp_path / "s.md"
    ).read_text() == f"**speccheck:** 1 requirement: 1 passed. Full report: [speccheck-report]({url})\n\n"
