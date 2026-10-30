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

import io
import json
from pathlib import Path

import pytest

from platformctl import jsonout
from platformctl.paths import PLATFORM_ROOT, Paths
from platformctl.targets import SUPPORTED, check_name
from platformctl.targets.base import PASSTHROUGH, Target, UnsupportedError

# -- paths -------------------------------------------------------------------------------------


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


# -- json contract -----------------------------------------------------------------------------

PLATFORM = {"root": "/p", "project": "x", "version": "v"}


def test_result_shape():
    body = jsonout.result("status", PLATFORM, services=[1])
    assert body == {"schema_version": 1, "command": "status", "ok": True, "platform": PLATFORM, "services": [1]}


def test_error_object_has_every_field():
    body = jsonout.error_object("up", PLATFORM, "port_in_use", "8600 is taken", "run down", "ports-free")
    assert body["ok"] is False
    assert body["error"] == {
        "code": "port_in_use",
        "message": "8600 is taken",
        "hint": "run down",
        "check": "ports-free",
    }
    assert jsonout.error_object("up", PLATFORM, "usage", "m")["error"]["hint"] == ""


def test_error_codes_are_the_fixed_list():
    assert jsonout.ERROR_CODES == (
        "usage",
        "needs_terminal",
        "not_running",
        "docker_unavailable",
        "port_in_use",
        "running_elsewhere",
        "timeout",
        "config_invalid",
        "check_failed",
        "internal",
    )
    with pytest.raises(ValueError, match="unknown error code"):
        jsonout.error_object("up", PLATFORM, "made_up", "m")


def test_exit_codes():
    assert (
        jsonout.EXIT_OK,
        jsonout.EXIT_FAIL,
        jsonout.EXIT_USAGE,
        jsonout.EXIT_NOT_RUNNING,
        jsonout.EXIT_INTERRUPTED,
    ) == (0, 1, 2, 3, 130)


def test_emit_prints_one_scrubbed_object():
    out = io.StringIO()
    jsonout.emit(
        jsonout.result("x", PLATFORM, note="hide-this-value"), out, lambda text: text.replace("hide-this-value", "***")
    )
    assert json.loads(out.getvalue())["note"] == "***"
    assert out.getvalue().count("\n") > 1 and out.getvalue().endswith("}\n")
    plain = io.StringIO()
    jsonout.emit({"a": 1}, plain)
    assert json.loads(plain.getvalue()) == {"a": 1}


# -- targets -----------------------------------------------------------------------------------


def test_check_name():
    assert SUPPORTED == ("compose",)
    assert check_name("compose") == "compose"
    with pytest.raises(UnsupportedError, match="k3d` is not supported yet"):
        check_name("k3d")
    with pytest.raises(UnsupportedError, match="unknown target `nope`"):
        check_name("nope")


def test_capabilities_are_enforced():
    class Minimal(Target):
        name = "minimal"
        capabilities = frozenset()

        def generate(self):
            return {}

        def service_url(self, service):
            return None

    target = Minimal()
    with pytest.raises(UnsupportedError, match="`compose --` is not supported on target `minimal`"):
        target.require(PASSTHROUGH, "compose --")
    Minimal.capabilities = frozenset({PASSTHROUGH})
    target.require(PASSTHROUGH, "compose --")
    assert target.generate() == {} and target.service_url("x") is None
