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

"""The Context."""

from __future__ import annotations

import pytest

from speccheck.context import Context
from speccheck.output import Output
from tests.conftest import Repo


@pytest.mark.covers("SPC-REQ-002-01")
def test_the_config_is_loaded_once(repo: Repo):
    """The config is found from the current folder on first use, then kept."""
    ctx = Context(cwd=repo.root, output=Output(), env={})
    first = ctx.config()
    assert ctx.config() is first and first.prefix == "T"
    assert ctx.specs().syntax.head == "T-"
