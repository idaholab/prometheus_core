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
from tests.unit.conftest import err, make_config, make_ctx, make_specs, namespace, out, producer


def test_the_arguments():
    """Results files and the scope."""
    parser = argparse.ArgumentParser()
    verify.add_arguments(parser)
    assert vars(parser.parse_args(["a", "--complete"])) == {"inputs": ["a"], "complete": True, "workflow": None}


def write(tmp_path: Path, outcome: str) -> None:
    """unit.jsonl with one claim of T-REQ-001-01."""
    claim = results.Result("t", ["T-REQ-001-01"], outcome)
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
