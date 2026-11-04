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

"""`speccheck check`: claims only, outcomes not looked at."""

from __future__ import annotations

import argparse
from pathlib import Path

from speccheck import results
from speccheck.actions import check
from speccheck.claims import Claim
from tests.unit.conftest import err, make_ctx, make_specs, namespace, out


def test_the_arguments():
    """Results files, and no scope."""
    parser = argparse.ArgumentParser()
    check.add_arguments(parser)
    assert vars(parser.parse_args(["a"])) == {"inputs": ["a"], "summary": None, "report_url": None}


def test_a_failed_claim_is_enough(tmp_path: Path):
    """`check` sees the claim, not the outcome; the unclaimed requirement is the problem."""
    claim = results.Result("t", [Claim("T-REQ-001-01", "t claims it")], "failed", file="t.py", line=1)
    results.write(tmp_path / "c.jsonl", results.ResultsFile(producer="unit", results=[claim]))
    ctx = make_ctx(tmp_path, specs_set=make_specs("One.", "Two."))
    assert check.run(ctx, namespace(inputs=["c.jsonl"])) == 1
    assert (
        err(ctx).splitlines()[-1]
        == "speccheck check: 2 requirements: 1 unclaimed, 1 claimed; reported: unit; 1 problem"
    )


def test_clean(tmp_path: Path):
    """Exit 0 with the summary line."""
    ctx = make_ctx(tmp_path, specs_set=make_specs("It. (unimplemented: later)"))
    assert check.run(ctx, namespace()) == 0
    assert out(ctx) == "speccheck check: 1 requirement: 1 unimplemented\n"
