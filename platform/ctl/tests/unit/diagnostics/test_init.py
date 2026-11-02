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

from platformctl.diagnostics import default_registry


def test_default_registry_is_valid_and_has_the_planned_ids():
    """Default registry is valid and has the planned ids."""
    registry = default_registry()
    ids = [c.id for c in registry.checks]
    assert ids == [
        "docker",
        "build-cache-store",
        "platform-env",
        "base-image-pin",
        "env-hides-environment",
        "env-derived-keys",
        "env-file",
        "ports-free",
        "checkout-path",
    ]
    for c in registry.checks:
        assert c.fix_kind in ("safe", "yes", "you")
        assert c.tags and set(c.tags) <= {"preflight", "diagnose"}
