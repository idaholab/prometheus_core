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

from tests.unit.conftest import make_context


def test_service_urls(ctx_factory):
    ctx, _, _ = ctx_factory(sets={"BACKEND_PORT": "9000"})
    assert ctx.target.service_url("backend") == "http://localhost:9000"
    assert ctx.target.service_url("frontend-dev") == "http://localhost:5150"
    assert ctx.target.service_url("admin-db") is None


def test_generate_writes_the_files_with_the_cache_when_the_store_allows(ctx_factory, platform_root):
    ctx, _, _ = ctx_factory()
    written = ctx.target.generate()
    assert set(written) == {"entry", "env", "agents"}
    assert "docker-compose.build-cache.yml" in (platform_root / "docker-compose.platform.yml").read_text()
    assert "BUILD_CACHE_PLATFORM=arm64" in (platform_root / ".platform.env").read_text()
    assert ctx.target.build_cache_on()


def test_generate_turns_the_cache_off_without_the_containerd_store(platform_root, runner):
    runner.reply("docker", "info", stdout='{"ServerVersion": "27", "Architecture": "x86_64", "DriverStatus": []}')
    ctx, _, _ = make_context(platform_root, runner)
    ctx.target.generate()
    assert "build-cache" not in (platform_root / "docker-compose.platform.yml").read_text()
    assert "USE_BUILD_CACHE=false" in (platform_root / ".platform.env").read_text()
    assert not ctx.target.build_cache_on()


def test_generate_respects_use_build_cache_false(ctx_factory, platform_root):
    ctx, _, _ = ctx_factory(sets={"USE_BUILD_CACHE": "false"})
    ctx.target.generate()
    assert "USE_BUILD_CACHE=false" in (platform_root / ".platform.env").read_text()
