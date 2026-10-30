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

"""Checks on the host: free ports, and where the checkout lives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from platformctl.diagnostics.base import (
    FAIL,
    FIX_YES,
    FIX_YOU,
    PASS,
    TAG_DIAGNOSE,
    TAG_PREFLIGHT,
    WARN,
    Check,
    Result,
)
from platformctl.system import host as hostmod

if TYPE_CHECKING:
    from platformctl.context import Context

# Setting -> what the port is for. DeepLynx ports only count with LOCAL_DEEPLYNX.
PLATFORM_PORTS = (
    ("FRONTEND_DEV_PORT", "the chat UI"),
    ("BACKEND_PORT", "the backend"),
    ("REDIS_LOCAL_PORT", "Valkey"),
)


def _ports(ctx: Context) -> list[tuple[str, int, str]]:
    ports = [(name, ctx.config.int(name), what) for name, what in PLATFORM_PORTS]
    if ctx.config.flag("PROMETHEUS_SYSTEM_TESTING"):
        ports.append(("CLIENT_AGENT_PORT", ctx.config.int("CLIENT_AGENT_PORT"), "the client agent"))
    if ctx.config.flag("LOCAL_DEEPLYNX"):
        ports.append(("DEEPLYNX_SERVER_PORT", ctx.config.int("DEEPLYNX_SERVER_PORT"), "the DeepLynx API"))
        ports.append(("DEEPLYNX_UI_PORT", ctx.config.int("DEEPLYNX_UI_PORT"), "the DeepLynx UI"))
    return ports


def _describe(holder: hostmod.Holder) -> str:
    if holder.kind == "container":
        origin = f" (project {holder.project}, from {holder.root})" if holder.project else ""
        return f"container {holder.name}{origin}"
    if holder.kind == "process":
        return f"the process {holder.name}"
    return "another process"


def check_ports_free(ctx: Context) -> Result:
    taken: list[str] = []
    fixes: list[str] = []
    for name, port, what in _ports(ctx):
        if hostmod.port_free(port):
            continue
        holder = ctx.host.holder(port)
        if holder.kind == "container" and holder.project == ctx.config.project:
            continue  # the platform's own containers: restart must not trip on itself
        taken.append(f"{port} ({what}) is held by {_describe(holder)}")
        known = hostmod.KNOWN_HOLDERS.get(port)
        if known and ctx.host.is_mac and holder.kind != "container":
            fixes.append(f"Turn off {known}, then run this again.")
        elif holder.kind == "container" and holder.root:
            fixes.append(f"Run `./platformctl down` in {holder.root}.")
        else:
            fixes.append(f"Free port {port}, or choose another: set {name}=<free port> in .env.")
    if taken:
        return Result(FAIL, "; ".join(taken), " ".join(dict.fromkeys(fixes)))
    return Result(PASS, f"{len(_ports(ctx))} ports are free")


def check_checkout_path(ctx: Context) -> Result:
    problems: list[str] = []
    fixes: list[str] = []
    if ctx.host.wsl_version == 1:
        problems.append("this is WSL 1, which cannot run Docker")
        fixes.append("Convert the distro: `wsl --set-version <distro> 2` (in Windows).")
    shim = ctx.paths.shim
    if shim.exists() and b"\r" in shim.read_bytes():
        problems.append("the platformctl shim has CRLF line endings")
        fixes.append("Run `git add --renormalize .`, or re-clone with `git config --global core.autocrlf input`.")
    if ctx.host.on_windows_drive(ctx.paths.root):
        problems.append("the checkout is on a Windows drive (/mnt/<drive>), where file modes and watching misbehave")
        fixes.append("Clone it inside the Linux filesystem (for example ~/projects) instead.")
    if problems:
        return Result(WARN, "; ".join(problems), " ".join(fixes))
    return Result(PASS, "the checkout location is fine")


PORTS_FREE = Check("ports-free", "laptop", (TAG_PREFLIGHT, TAG_DIAGNOSE), check_ports_free, fix_kind=FIX_YES)
CHECKOUT_PATH = Check("checkout-path", "laptop", (TAG_PREFLIGHT, TAG_DIAGNOSE), check_checkout_path, fix_kind=FIX_YOU)
