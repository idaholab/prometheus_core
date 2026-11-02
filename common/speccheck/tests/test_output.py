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

"""Text output."""

from __future__ import annotations

import io

import pytest

from speccheck.output import Output
from speccheck.specs import Problem


def make(**kwargs) -> Output:
    """An Output on string streams."""
    return Output(out=io.StringIO(), err=io.StringIO(), **kwargs)


@pytest.mark.covers("SPC-REQ-008-05", "SPC-REQ-001-10")
def test_streams_and_modes():
    """Problems and a failing summary on stderr; info and a clean summary on stdout; control characters escaped."""
    output = make()
    output.info("hi\x1b")
    output.detail("hidden")
    output.problems([Problem("a\n::error::", 1, "m")])
    output.summary("lint", "1 spec", 2)
    output.summary("lint", "1 spec", 0)
    output.error("bad")
    assert output.out.getvalue() == "hi\\x1b\nspeccheck lint: 1 spec\n"
    assert output.err.getvalue() == "a\\n::error:::1: m\nspeccheck lint: 1 spec; 2 problems\nspeccheck: error: bad\n"


@pytest.mark.covers("SPC-REQ-008-02")
def test_quiet_verbose_and_json():
    """`--quiet` keeps problems; `--verbose` adds details; `--json` prints nothing but the object."""
    quiet = make(quiet=True)
    quiet.info("x")
    quiet.summary("lint", "ok", 0)
    quiet.summary("lint", "bad", 1)
    assert quiet.out.getvalue() == "" and quiet.err.getvalue() == "speccheck lint: bad; 1 problem\n"
    verbose = make(verbose=True)
    verbose.detail("shown")
    assert verbose.out.getvalue() == "shown\n"
    json_mode = make(json_mode=True, verbose=True)
    json_mode.info("x")
    json_mode.detail("x")
    json_mode.problems([Problem("a", 1, "m")])
    json_mode.summary("lint", "x", 1)
    assert json_mode.out.getvalue() == json_mode.err.getvalue() == ""
