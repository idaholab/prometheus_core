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

"""The Context: the config found and loaded once, and the specs read from it."""

from __future__ import annotations

from pathlib import Path

import pytest

from speccheck import context
from speccheck.context import Context
from speccheck.output import Output
from tests.unit.conftest import make_config, make_specs


def test_the_config_is_found_from_the_cwd_and_kept(monkeypatch: pytest.MonkeyPatch):
    """`find(--config, cwd)` then `load`, on first use only."""
    calls = []
    loaded = make_config(prefix="X")
    monkeypatch.setattr(context.config_module, "find", lambda explicit, cwd: calls.append((explicit, cwd)) or Path("c"))
    monkeypatch.setattr(context.config_module, "load", lambda path: loaded)
    ctx = Context(cwd=Path("/w"), output=Output(), env={}, config_path="c.toml")
    assert ctx.config() is loaded and ctx.config() is loaded
    assert calls == [("c.toml", Path("/w"))]


def test_the_specs_come_from_the_configs_folder(monkeypatch: pytest.MonkeyPatch):
    """With the config's prefix and index setting, paths relative to the cwd."""
    calls = []
    specs = make_specs()
    monkeypatch.setattr(context.specs_module, "load", lambda *args: calls.append(args) or specs)
    loaded = make_config(prefix="X")
    loaded.require_index = False
    ctx = Context(cwd=Path("/w"), output=Output(), env={}, _config=loaded)
    assert ctx.specs() is specs
    assert calls == [(loaded.specs_dir, Path("/w"), "X", False)]
