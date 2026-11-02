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

from __future__ import annotations

import pytest

from platformctl.targets.base import PASSTHROUGH, Target, UnsupportedError


def test_capabilities_are_enforced():
    """A target without a capability refuses the command that needs it."""

    class Minimal(Target):
        name = "minimal"
        capabilities = frozenset()

        def generate(self):
            """Generate nothing."""
            return {}

        def service_url(self, service):
            """Have no URL for any service."""
            return None

    target = Minimal()
    with pytest.raises(UnsupportedError, match="`compose --` is not supported on target `minimal`"):
        target.require(PASSTHROUGH, "compose --")
    Minimal.capabilities = frozenset({PASSTHROUGH})
    target.require(PASSTHROUGH, "compose --")
    assert target.generate() == {} and target.service_url("x") is None
