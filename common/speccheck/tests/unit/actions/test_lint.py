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

"""`speccheck lint`, on a spec set built in memory."""

from __future__ import annotations

import argparse
import json

from speccheck.actions import lint
from speccheck.specs import Problem
from tests.unit.conftest import err, make_ctx, make_spec, make_specs, out, spec_set


def test_no_arguments_of_its_own():
    """The parser is left as it was."""
    parser = argparse.ArgumentParser()
    lint.add_arguments(parser)
    assert vars(parser.parse_args([])) == {}


def test_clean():
    """0 and one line, with the counts."""
    ctx = make_ctx(specs_set=make_specs("It."))
    assert lint.run(ctx, argparse.Namespace()) == 0
    assert out(ctx) == "speccheck lint: 1 specs, 1 requirement\n"
    ctx = make_ctx(specs_set=make_specs("A.", "B."))
    lint.run(ctx, argparse.Namespace())
    assert out(ctx) == "speccheck lint: 1 specs, 2 requirements\n"


def test_problems():
    """1, and the problems then the summary on stderr."""
    ctx = make_ctx(specs_set=spec_set(make_spec(), problems=[Problem("specs/001-thing.md", 3, "bad")]))
    assert lint.run(ctx, argparse.Namespace()) == 1
    assert err(ctx).splitlines() == [
        "specs/001-thing.md:3: bad",
        "speccheck lint: 1 specs, 0 requirements; 1 problem",
    ]


def test_json():
    """Every spec with its header and count, and the problems; nothing on stderr."""
    spec = make_spec(status="implemented", title="Thing\x1b")
    ctx = make_ctx(specs_set=make_specs("It.", spec=spec), json_mode=True)
    ctx.specs().problems.append(Problem("specs/x.md", 0, "m"))
    assert lint.run(ctx, argparse.Namespace()) == 1
    body = json.loads(out(ctx))
    assert (body["command"], body["ok"], body["requirements"]) == ("lint", False, 1)
    assert body["specs"] == [{"number": "001", "title": "Thing\x1b", "status": "implemented", "requirements": 1}]
    assert body["problems"] == [{"path": "specs/x.md", "line": 0, "message": "m"}]
    assert err(ctx) == ""
