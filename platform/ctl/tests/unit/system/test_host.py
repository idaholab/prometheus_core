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

import socket
from pathlib import Path

import pytest

from platformctl.system import host as hostmod
from platformctl.system.docker import Docker
from platformctl.system.host import Host
from platformctl.system.runner import RunnerError
from tests.unit.conftest import FakeRunner

# Recorded output.
LSOF_MAC = """COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
ControlCe 612 me    10u  IPv4 0x1234567890      0t0  TCP *:5000 (LISTEN)
ControlCe 612 me    11u  IPv6 0x1234567891      0t0  TCP *:5000 (LISTEN)
"""
"""A recorded `lsof` listing of AirPlay holding port 5000 on a Mac."""
SS_LINUX = 'LISTEN 0 4096 0.0.0.0:6379 0.0.0.0:* users:(("redis-server",pid=811,fd=6))\n'
"""A recorded `ss -ltnp` line of redis holding port 6379."""
SS_EMPTY = "State Recv-Q Send-Q Local Address:Port Peer Address:Port\n"
"""A recorded `ss -ltnp` listing with no holder."""


def test_parse_lsof_and_ss():
    """The process name is read from recorded `lsof` and `ss` output, or None."""
    assert hostmod.parse_lsof(LSOF_MAC) == "ControlCe"
    assert hostmod.parse_lsof("COMMAND PID\n") is None
    assert hostmod.parse_lsof("COMMAND PID\nnot matching\n") is None
    assert hostmod.parse_ss(SS_LINUX) == "redis-server"
    assert hostmod.parse_ss(SS_EMPTY) is None


# -- ports, against real sockets ---------------------------------------------------------------


def listen(family=socket.AF_INET, address="127.0.0.1"):
    """Open a listening socket on a free port and return it with the port."""
    sock = socket.socket(family, socket.SOCK_STREAM)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.bind((address, 0))
    sock.listen()
    return sock, sock.getsockname()[1]


def free_port() -> int:
    """A port that was free a moment ago on 0.0.0.0 and ::, the addresses `port_free` binds.

    The OS hands out a port that is free on the address asked for. On macOS a port free on
    127.0.0.1 can still be in use on another address, such as a VPN client's outbound
    connection, so `port_free` fails its bind of 0.0.0.0. Pick on 0.0.0.0 and check ::
    too, so the port is free on both.
    """
    while True:
        sock, port = listen(address="0.0.0.0")
        sock.close()
        if not socket.has_ipv6 or not hostmod._ipv6_usable():
            return port
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as six:
            six.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                six.bind(("::", port))
            except OSError:
                continue
        return port


def test_port_free_and_taken_on_ipv4():
    """Port free and taken on ipv4."""
    port = free_port()
    assert hostmod.port_free(port)
    sock, port = listen()
    try:
        assert not hostmod.port_free(port)
    finally:
        sock.close()


def test_port_taken_on_all_interfaces():
    """Port taken on all interfaces."""
    sock, port = listen(address="0.0.0.0")
    try:
        assert not hostmod.port_free(port)
    finally:
        sock.close()


@pytest.mark.skipif(not hostmod._ipv6_usable(), reason="no IPv6 loopback")
def test_port_taken_on_ipv6_only():
    """Port taken on ipv6 only."""
    sock, port = listen(socket.AF_INET6, "::1")
    try:
        assert not hostmod.port_free(port)
    finally:
        sock.close()


@pytest.mark.skipif(not hostmod._ipv6_usable(), reason="no IPv6 loopback")
def test_port_taken_on_ipv6_wildcard():
    """Port taken on ipv6 wildcard."""
    sock, port = listen(socket.AF_INET6, "::")
    try:
        assert not hostmod.port_free(port)
    finally:
        sock.close()


def test_a_holder_on_loopback_only_is_found_by_connecting(monkeypatch):
    """On macOS a bind of 0.0.0.0 can succeed while 127.0.0.1 is held."""
    monkeypatch.setattr(hostmod, "_bind", lambda *_: True)
    monkeypatch.setattr(hostmod, "_ipv6_usable", lambda: False)
    monkeypatch.setattr(hostmod, "_connects", lambda family, address, port: address == "127.0.0.1")
    assert not hostmod.port_free(1234)


def test_port_free_without_ipv6(monkeypatch):
    """On a host without IPv6, a free port is still free."""
    monkeypatch.setattr(hostmod, "_ipv6_usable", lambda: False)
    assert hostmod.port_free(free_port())


def test_ipv6_usable_false_when_bind_fails(monkeypatch):
    """Ipv6 usable false when bind fails."""

    class Broken:
        def __init__(self, *_):
            """Accept and ignore the socket arguments."""
            pass

        def __enter__(self):
            """Enter the context manager."""
            return self

        def __exit__(self, *_):
            """Leave the context manager without hiding errors."""
            return False

        def bind(self, *_):
            """Fail like a host with no IPv6."""
            raise OSError("no ipv6")

    monkeypatch.setattr(hostmod.socket, "socket", Broken)
    assert not hostmod._ipv6_usable()


# -- holders -----------------------------------------------------------------------------------


def make_host(**kw) -> tuple[Host, FakeRunner]:
    """A `Host` over a fake runner."""
    runner = FakeRunner()
    return Host(runner, Docker(runner), **kw), runner


def test_holder_prefers_a_container_with_its_platform_root():
    """Holder prefers a container with its platform root."""
    host, runner = make_host()
    row = '{"Names": "p-backend-1", "Labels": "com.docker.compose.project=p,io.prometheus.platform.root=/a/platform"}'
    runner.reply("docker", "ps", stdout=row)
    assert host.holder(8600) == hostmod.Holder("container", "p-backend-1", "p", "/a/platform")


def test_holder_falls_back_to_the_working_dir_label():
    """Holder falls back to the working dir label."""
    host, runner = make_host()
    row = '{"Names": "old-1", "Labels": "com.docker.compose.project=old,com.docker.compose.project.working_dir=/old"}'
    runner.reply("docker", "ps", stdout=row)
    assert host.holder(8600).root == "/old"


def test_holder_process_from_lsof_then_ss():
    """Holder process from lsof then ss."""
    host, runner = make_host()
    runner.reply("lsof", stdout=LSOF_MAC)
    assert host.holder(5000) == hostmod.Holder("process", "ControlCe")
    runner.reply("lsof", code=1)
    runner.reply("ss", stdout=SS_LINUX)
    assert host.holder(6379) == hostmod.Holder("process", "redis-server")


def test_holder_unknown_when_tools_are_missing_or_find_nothing():
    """Holder unknown when tools are missing or find nothing."""
    host, runner = make_host()
    runner.raises = {"lsof": RunnerError("none"), "ss": RunnerError("none")}
    assert host.holder(1).kind == "unknown"
    runner.raises = {}
    runner.reply("lsof", stdout="COMMAND PID\n")
    runner.reply("ss", stdout=SS_EMPTY)
    assert host.holder(1).kind == "unknown"


# -- OS ----------------------------------------------------------------------------------------


def test_os_flags():
    """`is_mac` and `is_linux` follow the platform name."""
    assert make_host(system="darwin")[0].is_mac
    assert make_host(system="linux")[0].is_linux
    assert not make_host(system="darwin")[0].is_linux
    assert make_host(system="linux2")[0].is_linux


@pytest.mark.parametrize(
    ("system", "release", "wsl", "version"),
    [
        ("linux", "5.15.90.1-microsoft-standard-WSL2", True, 2),
        ("linux", "4.4.0-19041-Microsoft", True, 1),
        ("linux", "6.8.0-generic", False, 0),
        ("darwin", "microsoft", False, 0),
    ],
)
def test_wsl(system, release, wsl, version):
    """WSL 1 and 2 are told apart by the kernel release, and only on Linux."""
    host, _ = make_host(system=system, release_reader=lambda: release + "\n")
    assert (host.is_wsl, host.wsl_version) == (wsl, version)


def test_kernel_release_unreadable():
    """An unreadable kernel release is empty and not WSL."""

    def boom():
        """Fail like a missing `/proc`."""
        raise OSError("no proc")

    host, _ = make_host(system="linux", release_reader=boom)
    assert host.kernel_release() == ""
    assert not host.is_wsl


def test_default_release_reader_reads_proc_or_fails_cleanly():
    """Default release reader reads proc or fails cleanly."""
    host, _ = make_host(system="linux")
    assert isinstance(host.kernel_release(), str)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/mnt/c/Users/me/repo", True),
        ("/mnt/d", True),
        ("/mnt/wsl/x", False),
        ("/home/me", False),
        ("/mnt/cc/x", False),
    ],
)
def test_on_windows_drive(path, expected):
    """Only `/mnt/<single letter>` is a Windows drive."""
    assert Host.on_windows_drive(Path(path)) is expected
