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

"""`deeplynx setup`: point the platform at the local DeepLynx from `docker-compose.deeplynx.yml`.

1. Start the DeepLynx services and wait until the server answers on its host port.
2. If `.env` already holds an API key this server accepts, for a project that still exists, stop.
3. Otherwise find the project `Prometheus` or create it, and generate an API key.
4. Write the `DEEPLYNX_*` settings to `.env`.

The server runs with authentication disabled, so creating the project and the key needs no
credentials. After `make down-v` the DeepLynx database is gone and the next run creates both again.
"""

from __future__ import annotations

import argparse

from platformctl import jsonout
from platformctl.actions import Subcommand
from platformctl.context import Context
from platformctl.system import envfile
from platformctl.system.deeplynx import INTERNAL_URL, ORG_ID, PROJECT_NAME, DeepLynx, DeepLynxError

NAME = "deeplynx"
"""The command's name."""
HELP = "Set up the local DeepLynx"
"""The command's one-line description in `--help`."""
SECTION = "setup"
"""The `--help` section the command is listed in."""
ORDER = 30
"""Where the command sits within its section; lower is listed first."""

SERVICES = ("deeplynx-postgres", "deeplynx-server", "deeplynx-ui")
"""The compose services `deeplynx setup` starts, and nothing else."""
COMPOSE_FILE = "docker-compose.deeplynx.yml"
"""The compose file that defines them."""


def add_setup_arguments(parser: argparse.ArgumentParser) -> None:
    """Add `deeplynx setup`'s options: how long to wait for the server, and whether to start it."""
    parser.add_argument(
        "--timeout", type=float, default=300, metavar="SECONDS", help="How long to wait for the server (default: 300)"
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Don't start the DeepLynx containers; only wait for the server that is already running",
    )


def _fail(ctx: Context, code: str, message: str, hint: str = "") -> int:
    """Report a failure as JSON or as an error line on stderr; the exit code is 1."""
    out = ctx.output
    if ctx.json_mode:
        jsonout.emit(
            jsonout.error_object("deeplynx setup", ctx.platform_info(), code, message, hint),
            out.out,
            out.scrubber.scrub,
        )
    else:
        out.error(message, hint or None)
    return jsonout.EXIT_FAIL


def _done(ctx: Context, ui: str, **fields) -> int:
    """With `--json`, print the one result object for a setup that succeeded (no key or secret); return 0."""
    if ctx.json_mode:
        out = ctx.output
        body = jsonout.result("deeplynx setup", ctx.platform_info(), ui=ui, **fields)
        jsonout.emit(body, out.out, out.scrubber.scrub)
    return jsonout.EXIT_OK


def start_services(ctx: Context) -> bool:
    """Start only the DeepLynx services, from just the files they need, with `up -d --wait`.

    Only these start, so the platform's agents compose file isn't regenerated; the start target that
    follows reuses them. Returns whether Compose succeeded.
    """
    done = ctx.compose.up(
        SERVICES, build=False, wait=ctx.config.int("WAIT_TIMEOUT"), files=("docker-compose.yml", COMPOSE_FILE)
    )
    return done.ok


def run_setup(ctx: Context, args: argparse.Namespace) -> int:
    """Set up DeepLynx in `.env` if it isn't already; return the exit code."""
    paths, out = ctx.paths, ctx.output
    if not ctx.config.flag("LOCAL_DEEPLYNX"):
        return _fail(
            ctx,
            "config_invalid",
            "LOCAL_DEEPLYNX is not true; set it to run DeepLynx locally.",
            "Run ./platformctl config init --local-deeplynx",
        )
    if not paths.env.exists():
        return _fail(ctx, "config_invalid", f"{paths.env} does not exist.", "Run ./platformctl config init")
    if ctx.dry_run:
        out.info("Would start " + ", ".join(SERVICES) + f", then save a project and API key in {paths.env.name}.")
        return _done(ctx, "", dry_run=True)
    if not args.no_start and not start_services(ctx):
        return _fail(ctx, "docker_unavailable", "Starting DeepLynx failed.", "Run ./platformctl doctor")

    port = ctx.config.int("DEEPLYNX_SERVER_PORT")
    api = f"http://localhost:{port}/api/v1"
    client = DeepLynx(api)
    out.info(f"[1/3] Waiting for the DeepLynx server on port {port} ...")
    if not client.wait_healthy(args.timeout):
        return _fail(
            ctx,
            "timeout",
            f"DeepLynx didn't answer at {api}/health within {args.timeout:.0f}s.",
            "Run ./platformctl doctor",
        )
    ui = f"http://localhost:{ctx.config.int('DEEPLYNX_UI_PORT')}"
    current = envfile.read(paths.env)
    if client.configured(current):
        out.info(f"DeepLynx is already set up in {paths.env.name}.")
        out.info(f"\nDeepLynx UI: {ui}")
        return _done(ctx, ui, already_configured=True, project_id=int(current["DEEPLYNX_PROJECT_ID"]))

    try:
        out.info(f"[2/3] Finding the project {PROJECT_NAME!r} ...")
        project_id, created = client.find_or_create_project()
        if created:
            out.info(f"Created the DeepLynx project {PROJECT_NAME!r} (ID {project_id}).")
        out.info("[3/3] Creating an API key ...")
        key, secret = client.create_key()
    except DeepLynxError as exc:
        return _fail(ctx, "config_invalid", f"Setting up DeepLynx at {api}: {exc}")

    out.scrubber.add_all([key, secret])
    envfile.update(
        paths.env,
        {
            "DEEPLYNX_BASE_URL": INTERNAL_URL,
            "DEEPLYNX_KEY": key,
            "DEEPLYNX_SECRET": secret,
            "DEEPLYNX_JWT_TOKEN": "",
            "DEEPLYNX_ORG_ID": str(ORG_ID),
            "DEEPLYNX_PROJECT_ID": str(project_id),
            "DEEPLYNX_DATA_SOURCE_ID": "",
        },
    )
    out.info(f"Saved a new DeepLynx API key for project {project_id} in {paths.env.name}.")
    out.info(f"\nDeepLynx UI: {ui}")
    return _done(ctx, ui, already_configured=False, project_id=project_id, project_created=created)


SUBCOMMANDS = [
    Subcommand(
        "setup",
        "Start the local DeepLynx and save a project and API key for it in .env",
        add_setup_arguments,
        run_setup,
    ),
]
"""The subcommands of `deeplynx`."""
