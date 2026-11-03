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

import types

from platformctl import actions


def test_discover_finds_every_command_in_a_known_section():
    """Every command is listed, and each is in a section `--help` knows."""
    modules = actions.discover()
    assert {m.NAME for m in modules} >= {"doctor"}
    assert all(m.SECTION in dict(actions.SECTIONS) for m in modules)


def test_a_subcommand_carries_what_the_parser_reads():
    """A `Subcommand` has the same attributes a command module exports, and no aliases by default."""
    sub = actions.Subcommand("x", "does x", lambda parser: None, lambda ctx, args: 0)
    assert (sub.NAME, sub.HELP, sub.ALIASES) == ("x", "does x", ())
    assert sub.run(None, None) == 0


def test_discover_orders_by_section_then_order_then_name(monkeypatch):
    """Discover orders by section then order then name."""

    def module(name, section, order):
        """A fake action module."""
        return types.SimpleNamespace(NAME=name, SECTION=section, ORDER=order)

    mods = {
        "z": module("zeta", "troubleshoot", 10),
        "a": module("alpha", "troubleshoot", 10),
        "u": module("up", "run", 20),
        "d": module("down", "run", 10),
        "c": module("config", "setup", 10),
    }
    monkeypatch.setattr(
        actions.pkgutil,
        "iter_modules",
        lambda path: [types.SimpleNamespace(name=k) for k in mods] + [types.SimpleNamespace(name="helper")],
    )
    monkeypatch.setattr(
        actions.importlib, "import_module", lambda name: mods.get(name.rsplit(".", 1)[1], types.SimpleNamespace())
    )
    assert [m.NAME for m in actions.discover()] == ["down", "up", "config", "alpha", "zeta"]
