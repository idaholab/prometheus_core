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

from pathlib import Path

from platformctl.paths import PLATFORM_ROOT, Paths


def test_platform_root_comes_from_the_tools_location_not_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Paths.default().root == PLATFORM_ROOT
    assert (PLATFORM_ROOT / "platformctl").is_file()
    assert PLATFORM_ROOT.name == "platform"


def test_agent_is_separate_from_the_platform(tmp_path):
    paths = Paths.default(agent=tmp_path)
    assert paths.agent == tmp_path.resolve()
    assert paths.root == PLATFORM_ROOT
    assert Paths.default().agent is None


def test_every_path_is_under_the_root():
    root = Path("/p/platform")
    paths = Paths(root)
    for name in (
        "env",
        "env_example",
        "compose_base",
        "entry_file",
        "platform_env",
        "agents_file",
        "override_file",
        "shim",
    ):
        assert getattr(paths, name).parent == root
    assert paths.sdk == Path("/p/sdk")
    assert paths.entry_file.name == "docker-compose.platform.yml"
