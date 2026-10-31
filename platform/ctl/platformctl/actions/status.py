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

"""`status`: is the running platform answering on its host ports, and is every agent registered?

The service-state half of `status` (what is running, URLs, open chat turns) arrives with step 3a. This
step has the check `make check` ran: `--wait` repeats it until it passes or the timeout does.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

from platformctl import compose_files, jsonout, readiness
from platformctl.context import Context

NAME = "status"
"""The command's name."""
HELP = "Check the running platform answers and every agent is registered"
"""The command's one-line description in `--help`."""
SECTION = "run"
"""The `--help` section the command is listed in."""
ORDER = 50
"""Where the command sits within its section; lower is listed first."""

DEFAULT_TIMEOUT = 300
"""Seconds `--wait` waits when neither `--timeout` nor `CHECK_TIMEOUT` says otherwise."""
INTERVAL = 5
"""Seconds between polls."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add `status`'s options: whether to wait, and for how long."""
    parser.add_argument("--wait", action="store_true", help="Repeat the check until it passes or the timeout passes")
    parser.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS", help="How long --wait waits (default: CHECK_TIMEOUT)"
    )


def _frontend_port(ctx: Context) -> int | None:
    """The host port of the frontend the profile selects, or None when there is no frontend."""
    profile = ctx.config.frontend_profile()
    return ctx.config.int({"dev": "FRONTEND_DEV_PORT", "prod": "FRONTEND_PROD_PORT"}[profile]) if profile else None


def build_items(ctx: Context) -> list[readiness.Readiness]:
    """Everything to wait for: the backend, the frontend and its proxy, and the registered agents."""
    backend = f"http://localhost:{ctx.config.int('BACKEND_PORT')}"
    items = [readiness.Readiness("backend", readiness.http_ok(f"{backend}/healthz"), "ports-free")]
    if (port := _frontend_port(ctx)) is not None:
        frontend = f"http://localhost:{port}"
        items.append(readiness.Readiness("frontend", readiness.http_ok(f"{frontend}/"), "ports-free"))
        items.append(
            readiness.Readiness("frontend /api proxy", readiness.http_ok(f"{frontend}/api/setup/status"), "ports-free")
        )
    secret = ctx.config.get("AGENT_SECRET")
    if not secret:
        return items
    folders = compose_files.generated_agent_dirs(ctx.paths.root)
    expected = {readiness.registry_name(folder) for folder in folders if (folder / "agent_card.json").exists()}
    items.append(
        readiness.Readiness(
            f"{len(expected)} agent(s) registered",
            readiness.agents_registered(f"{backend}/v1/agents", secret, expected),
            "platform-env",
        )
    )
    return items


def _report(ctx: Context, failures: dict[str, str], items: list[readiness.Readiness], timeout: float) -> int:
    """Print what never passed, with the `doctor` check that explains each, as JSON or text; return 1."""
    out = ctx.output
    by_name = {item.name: item for item in items}
    if ctx.json_mode:
        problems = [
            {"name": name, "reason": reason, "doctor_check": by_name[name].doctor_check}
            for name, reason in failures.items()
        ]
        error = {
            "code": "timeout",
            "message": f"Not ready after {timeout:.0f}s: " + "; ".join(f"{p['name']}: {p['reason']}" for p in problems),
            "hint": "./platformctl doctor",
        }
        body = jsonout.result("status", ctx.platform_info(), ok=False, error=error, waiting_for=problems)
        jsonout.emit(body, out.out, out.scrubber.scrub)
        return jsonout.EXIT_FAIL
    out.write(f"\n[ERROR] Not ready after {timeout:.0f}s:", err=True)
    for name, reason in failures.items():
        out.write(f"  {name}: {reason}", err=True)
    checks = sorted({by_name[name].doctor_check for name in failures if by_name[name].doctor_check})
    if checks:
        out.write("Run: ./platformctl doctor " + " ".join(checks), err=True)
    return jsonout.EXIT_FAIL


def _json_ok(ctx: Context, items: list[readiness.Readiness]) -> int:
    """Print the one JSON object for a platform that is ready; return 0."""
    out = ctx.output
    body = jsonout.result("status", ctx.platform_info(), ready=True, checks=[item.name for item in items])
    jsonout.emit(body, out.out, out.scrubber.scrub)
    return jsonout.EXIT_OK


def run(
    ctx: Context,
    args: argparse.Namespace,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Check the platform once, or with `--wait` until it is ready or the timeout passes; 0 when ready, else 1."""
    out = ctx.output
    timeout = (args.timeout if args.timeout is not None else ctx.config.int("CHECK_TIMEOUT")) if args.wait else 0
    items = build_items(ctx)
    if not ctx.config.get("AGENT_SECRET"):
        return _fail_without_secret(ctx)
    if args.wait:
        out.info(f"Waiting up to {timeout:.0f}s for the platform:")
        for item in items:
            out.info(f"  {item.name}")
    started = clock()

    def on_ok(item: readiness.Readiness) -> None:
        """Say that one thing is ready."""
        out.info(f"  [OK] {item.name}")

    def tick(seconds: float) -> None:
        """Say what is still pending and how long is left, then wait."""
        out.debug(f"  waiting, {max(0.0, timeout - (clock() - started)):.0f}s left")
        sleep(seconds)

    try:
        failures = readiness.poll(items, timeout, INTERVAL, on_ok=on_ok, sleep=tick, clock=clock)
    except readiness.AuthError as exc:
        return _fail(ctx, "check_failed", f"{exc}: it is not the AGENT_SECRET the platform was started with")
    if failures:
        return _report(ctx, failures, items, timeout)
    if ctx.json_mode:
        return _json_ok(ctx, items)
    out.info("The platform is up.")
    return jsonout.EXIT_OK


def _fail_without_secret(ctx: Context) -> int:
    """`AGENT_SECRET` is needed to ask the registry which agents are registered."""
    return _fail(
        ctx,
        "config_invalid",
        f"AGENT_SECRET is not set in the environment or {ctx.paths.env}.",
        "Run ./platformctl config init",
    )


def _fail(ctx: Context, code: str, message: str, hint: str = "") -> int:
    """Report a failure as JSON or as an error block on stderr; the exit code is 1."""
    out = ctx.output
    if ctx.json_mode:
        jsonout.emit(
            jsonout.error_object("status", ctx.platform_info(), code, message, hint), out.out, out.scrubber.scrub
        )
    else:
        out.write("\n[ERROR] " + message + ("\n        " + hint if hint else "") + "\n", err=True)
    return jsonout.EXIT_FAIL
