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

"""The host: whether a port is free and who holds it, the OS, WSL, and where the checkout is."""

from __future__ import annotations

import re
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from platformctl.system.docker import Docker
from platformctl.system.runner import Runner, RunnerError


def _bind(family: int, address: str, port: int) -> bool:
    """True when nothing holds `address`. No SO_REUSEADDR: it hides holders on macOS."""
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            sock.bind((address, port))
        except OSError:
            return False
    return True


def _connects(family: int, address: str, port: int) -> bool:
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((address, port)) == 0


def port_free(port: int) -> bool:
    """Free on 0.0.0.0 and :: (bind), and nothing answers on 127.0.0.1 or ::1 (connect).

    A bind alone misses a holder on ::1 only (Vite binds `localhost` there) and, on macOS,
    one on 127.0.0.1 when binding 0.0.0.0.
    """
    if not _bind(socket.AF_INET, "0.0.0.0", port):
        return False
    ipv6 = socket.has_ipv6 and _ipv6_usable()
    if ipv6 and not _bind(socket.AF_INET6, "::", port):
        return False
    if _connects(socket.AF_INET, "127.0.0.1", port):
        return False
    return not (ipv6 and _connects(socket.AF_INET6, "::1", port))


def _ipv6_usable() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.bind(("::1", 0))
        return True
    except OSError:
        return False


_LSOF = re.compile(r"^(?P<name>\S+)\s+(?P<pid>\d+)\s")
_SS = re.compile(r'users:\(\("(?P<name>[^"]+)"')

# Ports with a well-known holder on a stock laptop.
KNOWN_HOLDERS = {5000: "AirPlay Receiver on macOS (System Settings > General > AirDrop & Handoff)"}


@dataclass
class Holder:
    kind: str  # container | process | unknown
    name: str = ""
    project: str = ""
    root: str = ""


def parse_lsof(text: str) -> str | None:
    """The process name from `lsof -nP -iTCP:<port> -sTCP:LISTEN`."""
    for line in text.splitlines()[1:]:
        match = _LSOF.match(line)
        if match:
            return match["name"]
    return None


def parse_ss(text: str) -> str | None:
    """The process name from `ss -ltnp`."""
    match = _SS.search(text)
    return match["name"] if match else None


@dataclass
class Host:
    runner: Runner
    docker: Docker
    system: str = sys.platform
    release_reader: Callable[[], str] = lambda: Path("/proc/sys/kernel/osrelease").read_text()

    # -- OS ------------------------------------------------------------

    @property
    def is_mac(self) -> bool:
        return self.system == "darwin"

    @property
    def is_linux(self) -> bool:
        return self.system.startswith("linux")

    def kernel_release(self) -> str:
        try:
            return self.release_reader().strip()
        except OSError:
            return ""

    @property
    def is_wsl(self) -> bool:
        return self.is_linux and "microsoft" in self.kernel_release().lower()

    @property
    def wsl_version(self) -> int:
        """1 or 2; 0 when not on WSL. WSL2's kernel release has `WSL2` in it."""
        if not self.is_wsl:
            return 0
        return 2 if "wsl2" in self.kernel_release().lower() else 1

    @staticmethod
    def on_windows_drive(path: Path) -> bool:
        """A checkout under `/mnt/<drive>` (WSL), where chmod and file watching misbehave."""
        return re.match(r"^/mnt/[a-z]($|/)", str(path)) is not None

    # -- ports ---------------------------------------------------------

    def holder(self, port: int) -> Holder:
        """Name who holds `port`: a container (with its platform labels), else a process."""
        containers = self.docker.holders(port)
        if containers:
            first = containers[0]
            return Holder("container", first["name"], first["project"], first["root"] or first["working_dir"])
        for argv, parse in (
            (["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], parse_lsof),
            (["ss", "-ltnp", f"sport = :{port}"], parse_ss),
        ):
            try:
                done = self.runner.run(argv, timeout=10)
            except RunnerError:
                continue
            name = parse(done.stdout) if done.ok else None
            if name:
                return Holder("process", name)
        return Holder("unknown")
