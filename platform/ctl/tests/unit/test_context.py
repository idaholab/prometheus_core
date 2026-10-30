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

from platformctl.targets.base import FOREGROUND, PASSTHROUGH, YOUR_AGENTS, UnsupportedError


def test_context_wires_the_adapters(ctx_factory):
    ctx, _, _ = ctx_factory(sets={"PROFILE": "prod"})
    assert ctx.compose.profiles == ["prod"]
    assert ctx.compose.entry_file == ctx.paths.entry_file
    assert ctx.target.name == "compose"
    assert ctx.target.capabilities == {PASSTHROUGH, YOUR_AGENTS, FOREGROUND}
    assert ctx.docker.env["COMPOSE_PROJECT_NAME"] == "prometheus_platform"


def test_no_profile_means_no_frontend(ctx_factory):
    ctx, _, _ = ctx_factory(sets={"PROFILE": ""})
    assert ctx.compose.profiles == []


def test_flags_are_carried(ctx_factory):
    ctx, _, _ = ctx_factory(dry_run=True, yes=True, json_mode=True, debug=True)
    assert (ctx.dry_run, ctx.yes, ctx.json_mode, ctx.debug) == (True, True, True, True)


def test_platform_info(ctx_factory, platform_root):
    ctx, _, _ = ctx_factory()
    assert ctx.platform_info() == {
        "root": str(platform_root),
        "project": "prometheus_platform",
        "version": "2026-10-30-abc1234",
    }


def test_k3d_and_unknown_targets_are_refused(ctx_factory):
    with pytest.raises(UnsupportedError, match="k3d` is not supported yet"):
        ctx_factory(target="k3d")
    with pytest.raises(UnsupportedError, match="k3d"):
        ctx_factory(sets={"PLATFORM_TARGET": "k3d"})


def test_image_source_is_refused(ctx_factory):
    with pytest.raises(UnsupportedError, match="PLATFORM_SOURCE `image` is not supported yet"):
        ctx_factory(sets={"PLATFORM_SOURCE": "image"})


def test_the_target_flag_beats_the_setting(ctx_factory):
    ctx, _, _ = ctx_factory(target="compose", sets={"PLATFORM_TARGET": "k3d"})
    assert ctx.target.name == "compose"
