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

"""What check, verify and report share."""

from __future__ import annotations

from pathlib import Path

from speccheck.actions import _common
from speccheck.specs import Problem


def test_paths_are_made_relative_where_possible(tmp_path: Path):
    """Under the current folder: relative; elsewhere: as given."""
    assert _common._relative(str(tmp_path / "a" / "b.jsonl"), tmp_path) == "a/b.jsonl"
    assert _common._relative("/elsewhere/x.jsonl", tmp_path) == "/elsewhere/x.jsonl"
    assert _common._relocate(Problem(str(tmp_path / "x"), 2, "m"), tmp_path) == Problem("x", 2, "m")
