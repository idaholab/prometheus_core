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

"""Finding the action modules."""

from __future__ import annotations

from speccheck import actions


def test_discover_finds_every_command_in_order():
    """Every module with a NAME, in section then ORDER order, each with the full interface; helpers are skipped."""
    modules = actions.discover()
    assert [m.NAME for m in modules] == ["lint", "check", "verify", "report", "record"]
    sections = {section for section, _ in actions.SECTIONS}
    for module in modules:
        assert module.SECTION in sections
        assert isinstance(module.HELP, str) and isinstance(module.ORDER, int)
        assert callable(module.add_arguments) and callable(module.run)
