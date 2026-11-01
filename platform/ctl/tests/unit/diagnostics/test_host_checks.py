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

from platformctl.diagnostics import host_checks as hc
from platformctl.diagnostics.base import FAIL, PASS, WARN
from platformctl.system import host as hostmod
from tests.unit.conftest import make_context


def ctx_for(root, runner, *, system="darwin", release="", sets=None, env=None):
    """A context on a pretend OS and kernel release."""
    ctx, _, _ = make_context(root, runner, env, sets)
    ctx.host.system = system
    ctx.host.release_reader = lambda: release
    return ctx


@pytest.fixture
def taken(monkeypatch):
    """Make the given ports 'taken' and name their holders."""
    state: dict[int, hostmod.Holder] = {}
    monkeypatch.setattr(hostmod, "port_free", lambda port: port not in state)
    monkeypatch.setattr(hostmod.Host, "holder", lambda self, port: state[port])
    return state


def test_all_ports_free(platform_root, runner, taken):
    """With nothing on the ports, the check passes and counts three."""
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner))
    assert (result.status, result.evidence) == (PASS, "3 ports are free")


def test_ports_follow_the_settings(platform_root, runner, taken):
    """The ports checked follow the port settings and the features turned on."""
    ctx = ctx_for(
        platform_root,
        runner,
        sets={"BACKEND_PORT": "9000", "PROMETHEUS_SYSTEM_TESTING": "true", "LOCAL_DEEPLYNX": "true"},
    )
    assert [(n, p) for n, p, _ in hc._ports(ctx)] == [
        ("FRONTEND_DEV_PORT", 5150),
        ("BACKEND_PORT", 9000),
        ("REDIS_LOCAL_PORT", 6379),
        ("CLIENT_AGENT_PORT", 8001),
        ("DEEPLYNX_SERVER_PORT", 5000),
        ("DEEPLYNX_UI_PORT", 3000),
    ]


@pytest.mark.parametrize(
    ("profile", "frontend"),
    [("dev", ("FRONTEND_DEV_PORT", 5150)), ("prod", ("FRONTEND_PROD_PORT", 8080)), ("", None), ("other", None)],
)
def test_the_frontend_port_follows_the_profile(platform_root, runner, taken, profile, frontend):
    """`PROFILE=prod` publishes 8080, and a blank `PROFILE` (no frontend) publishes nothing to check."""
    ctx = ctx_for(platform_root, runner, sets={"PROFILE": profile})
    checked = [(n, p) for n, p, _ in hc._ports(ctx)]
    assert checked[:1] == ([frontend] if frontend else [("BACKEND_PORT", 8600)])
    assert len(checked) == (3 if frontend else 2)


def test_a_busy_dev_port_is_not_a_problem_without_a_frontend(platform_root, runner, taken):
    """The `up deeplynx` job runs with `PROFILE=` and 5150 may be in use: no false FAIL."""
    taken[5150] = hostmod.Holder("process", "node")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner, sets={"PROFILE": ""}))
    assert (result.status, result.evidence) == (PASS, "2 ports are free")
    prod = hc.PORTS_FREE.run(ctx_for(platform_root, runner, sets={"PROFILE": "prod"}))
    assert prod.status == PASS  # 8080, not 5150


def test_a_busy_prod_port_is_a_problem_with_the_prod_profile(platform_root, runner, taken):
    """With `PROFILE=prod`, 8080 is checked and its fix names `FRONTEND_PROD_PORT`."""
    taken[8080] = hostmod.Holder("process", "node")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner, sets={"PROFILE": "prod"}))
    assert result.status == FAIL and "FRONTEND_PROD_PORT" in result.fix


def test_a_process_holding_a_port(platform_root, runner, taken):
    """A process holding a port."""
    taken[6379] = hostmod.Holder("process", "redis-server")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner))
    assert result.status == FAIL
    assert result.evidence == "6379 (Valkey) is held by the process redis-server"
    assert result.fix == "Free port 6379, or choose another: set REDIS_LOCAL_PORT=<free port> in .env."


def test_airplay_on_macos_gets_its_own_fix(platform_root, runner, taken):
    """Airplay on macos gets its own fix."""
    taken[5000] = hostmod.Holder("process", "ControlCe")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner, sets={"LOCAL_DEEPLYNX": "true"}))
    assert "AirPlay Receiver" in result.fix and "Turn off" in result.fix


def test_port_5000_on_linux_is_just_a_busy_port(platform_root, runner, taken):
    """Port 5000 on linux is just a busy port."""
    taken[5000] = hostmod.Holder("process", "something")
    result = hc.PORTS_FREE.run(
        ctx_for(platform_root, runner, system="linux", release="6.8", sets={"LOCAL_DEEPLYNX": "true"})
    )
    assert "AirPlay" not in result.fix and "DEEPLYNX_SERVER_PORT" in result.fix


def test_another_platform_is_named_with_the_fix_to_stop_it(platform_root, runner, taken):
    """Another platform is named with the fix to stop it."""
    taken[8600] = hostmod.Holder("container", "other-backend-1", "other_project", "/x/platform")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner))
    assert "container other-backend-1 (project other_project, from /x/platform)" in result.evidence
    assert result.fix == "Run `./platformctl down` in /x/platform."


def test_a_container_without_a_project(platform_root, runner, taken):
    """A container without a project."""
    taken[8600] = hostmod.Holder("container", "loose", "", "")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner))
    assert result.evidence == "8600 (the backend) is held by container loose"
    assert "BACKEND_PORT" in result.fix


def test_the_platforms_own_containers_do_not_count(platform_root, runner, taken):
    """The platforms own containers do not count."""
    taken[8600] = hostmod.Holder("container", "prometheus_platform-backend-1", "prometheus_platform", "/here")
    assert hc.PORTS_FREE.run(ctx_for(platform_root, runner)).status == PASS


def test_unknown_holder_and_repeated_fixes_are_listed_once(platform_root, runner, taken):
    """Unknown holder and repeated fixes are listed once."""
    taken[8600] = hostmod.Holder("unknown")
    taken[5150] = hostmod.Holder("unknown")
    result = hc.PORTS_FREE.run(ctx_for(platform_root, runner))
    assert result.evidence.count("another process") == 2
    assert result.fix.count("Free port") == 2  # different ports, different fixes


# -- checkout-path -----------------------------------------------------------------------------


def test_checkout_path_ok(platform_root, runner):
    """A normal checkout with an LF shim passes."""
    (platform_root / "platformctl").write_bytes(b"#!/bin/sh\n")
    result = hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner))
    assert (result.status, result.evidence) == (PASS, "the checkout location is fine")


def test_checkout_path_without_a_shim_is_fine(platform_root, runner):
    """Checkout path without a shim is fine."""
    assert hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner)).status == PASS


def test_crlf_in_the_shim(platform_root, runner):
    """A shim with CRLF line endings warns, with the fix for an existing checkout."""
    (platform_root / "platformctl").write_bytes(b"#!/bin/sh\r\nexit 0\r\n")
    result = hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner))
    assert result.status == WARN and "CRLF" in result.evidence
    assert "git add --renormalize ." in result.fix and "core.autocrlf input" in result.fix


@pytest.mark.parametrize("name", ["Makefile", ".env.example", ".env"])
def test_crlf_in_a_file_make_or_the_tool_reads(platform_root, runner, name):
    """Make reads `LOCAL_SDK=true\\r` as another value, so a CRLF Makefile, example or `.env` warns by name."""
    (platform_root / name).write_bytes(b"A=1\r\nB=2\r\n")
    result = hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner))
    assert result.status == WARN and f"{name} has CRLF line endings" in result.evidence
    assert "git add --renormalize ." in result.fix and "carriage returns" in result.fix


def test_crlf_in_several_files_names_them_all(platform_root, runner):
    """More than one file is listed together."""
    (platform_root / "Makefile").write_bytes(b"all:\r\n")
    (platform_root / ".env").write_bytes(b"A=1\r\n")
    result = hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner))
    assert "Makefile, .env have CRLF line endings" in result.evidence


def test_lf_files_do_not_warn(platform_root, runner):
    """A Makefile, example and `.env` with LF endings pass."""
    for name in ("Makefile", ".env.example", ".env"):
        (platform_root / name).write_bytes(b"A=1\nB=2\n")
    assert hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner)).status == PASS


def test_wsl1(platform_root, runner):
    """WSL 1 warns, because it can't run Docker."""
    result = hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner, system="linux", release="4.4.0-19041-Microsoft"))
    assert result.status == WARN and "WSL 1" in result.evidence and "set-version" in result.fix


def test_checkout_on_a_windows_drive(platform_root, runner, monkeypatch):
    """Checkout on a windows drive."""
    monkeypatch.setattr(hostmod.Host, "on_windows_drive", staticmethod(lambda path: True))
    result = hc.CHECKOUT_PATH.run(
        ctx_for(platform_root, runner, system="linux", release="5.15-microsoft-standard-WSL2")
    )
    assert result.status == WARN and "/mnt/<drive>" in result.evidence and "Linux filesystem" in result.fix


def test_all_problems_are_listed_together(platform_root, runner, monkeypatch):
    """All problems are listed together."""
    (platform_root / "platformctl").write_bytes(b"x\r\n")
    monkeypatch.setattr(hostmod.Host, "on_windows_drive", staticmethod(lambda path: True))
    result = hc.CHECKOUT_PATH.run(ctx_for(platform_root, runner, system="linux", release="4.4-Microsoft"))
    assert result.evidence.count(";") == 2
