#!/usr/bin/env python3
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

"""Wait until the running platform is reachable from the host and every agent is registered.

Polls, until all pass or the timeout passes:

- the backend's ``/healthz`` on ``--backend-port``
- with ``--frontend-port``, the frontend's index and ``/api/setup/status``
  through its ``/api`` proxy, which reaches the backend and admin-db
- the backend's agent registry, ``GET /v1/agents`` on ``--backend-port`` with
  ``AGENT_SECRET`` (read from the environment or else from .env), until every
  given agent is listed

Each agent argument is a directory holding an ``agent_card.json``. Its registry
name is derived from the card the same way the SDK does
(``AgentRegistryClient.agent_name``).

``docker compose up --wait`` covers the container healthchecks, which probe from
inside each container. This covers what they can't see: the published host
ports, the frontend's proxy, and registry registration, which runs in the
background while an agent keeps serving even if it gives up.

Standard library only. Run from anywhere; .env resolves relative to this file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from init_env import ENV, values


class AuthError(Exception):
    """A credential was rejected, so polling again cannot help."""


def env_value(name: str, default: str | None = None) -> str | None:
    """Look up ``name`` in the environment, then .env, else return ``default``.

    Args:
        name: Variable name, e.g. ``AGENT_SECRET``.
        default: Returned when the variable is unset or blank in both places.

    Returns:
        The first non-blank value found, or ``default``.
    """
    return os.environ.get(name) or (values(ENV.read_text()).get(name) if ENV.exists() else None) or default


def registry_name(agent_dir: Path) -> str:
    """Return the name the agent registers under in the registry, from its agent card.

    Args:
        agent_dir: Agent directory holding an ``agent_card.json``.

    Returns:
        The card's ``name``, lowercased with spaces as hyphens, as the SDK
        derives it.
    """
    card = json.loads((agent_dir / "agent_card.json").read_text())
    return card["name"].lower().replace(" ", "-")


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    """GET ``url`` and return the body.

    Args:
        url: URL to fetch.
        headers: Extra request headers.

    Returns:
        The response body.

    Raises:
        urllib.error.HTTPError: The response status is not 2xx.
        urllib.error.URLError: The connection failed or timed out.
    """
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def registered(url: str, agent_secret: str) -> set[str]:
    """Return the agent names the registry lists.

    Args:
        url: The registry's ``/v1/agents`` URL.
        agent_secret: ``AGENT_SECRET``, sent as a Bearer token.

    Returns:
        Each entry's ``agent_name``; malformed entries are skipped.

    Raises:
        AuthError: The registry answered 401 or 403.
        ValueError: The body is not a JSON list.
        urllib.error.URLError: Any other HTTP or connection failure.
    """
    try:
        entries = json.loads(get(url, {"Authorization": f"Bearer {agent_secret}"}))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError(f"The agent registry rejected AGENT_SECRET: {e}") from e
        raise
    if not isinstance(entries, list):
        raise ValueError(f"unexpected /v1/agents response: {type(entries).__name__}")
    return {
        entry["agent_name"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("agent_name"), str)
    }


def agents_check(url: str, agent_secret: str, expected: set[str]) -> Callable[[], str | None]:
    """Make a check that passes once every expected agent is registered.

    Args:
        url: The registry's ``/v1/agents`` URL.
        agent_secret: ``AGENT_SECRET``.
        expected: Registry names that must all be listed.

    Returns:
        A check for ``main()`` to poll.
    """

    def check() -> str | None:
        """Return None if every agent is registered, else which ones are missing.

        Raises:
            The same exceptions as ``registered()``.
        """
        missing = expected - registered(url, agent_secret)
        return f"not registered: {', '.join(sorted(missing))}" if missing else None

    return check


def http_check(url: str) -> Callable[[], str | None]:
    """Make a check that passes once ``url`` answers with a 2xx status.

    Args:
        url: URL to fetch.

    Returns:
        A check for ``main()`` to poll.
    """

    def check() -> str | None:
        """Return None on a 2xx status.

        Raises:
            The same exceptions as ``get()``.
        """
        get(url)
        return None

    return check


def main() -> int:
    """Poll every check until all pass or the timeout passes.

    Each check runs every ``--interval`` seconds until it passes, after which
    it is dropped. A rejected agent secret ends the run at once.

    Returns:
        0 once every check passes; 1 on a timeout, a rejected or missing
        agent secret.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("agent_dirs", nargs="*", type=Path, help="agent directories with an agent_card.json")
    parser.add_argument("--backend-port", type=int, required=True, help="host port of the backend")
    parser.add_argument("--frontend-port", type=int, help="host port of the frontend; omit if none is running")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait (default: 300)")
    parser.add_argument("--interval", type=float, default=5, help="seconds between polls (default: 5)")
    args = parser.parse_args()

    checks: dict[str, Callable[[], str | None]] = {
        "backend": http_check(f"http://localhost:{args.backend_port}/healthz"),
    }
    if args.frontend_port:
        frontend = f"http://localhost:{args.frontend_port}"
        checks["frontend"] = http_check(f"{frontend}/")
        checks["frontend /api proxy"] = http_check(f"{frontend}/api/setup/status")
    if args.agent_dirs:
        agent_secret = env_value("AGENT_SECRET")
        if not agent_secret:
            print(f"[ERROR] AGENT_SECRET is not set in the environment or {ENV}.", file=sys.stderr)
            return 1
        expected = {registry_name(d) for d in args.agent_dirs}
        checks[f"{len(expected)} agent(s) registered"] = agents_check(
            f"http://localhost:{args.backend_port}/v1/agents", agent_secret, expected
        )

    print(f"Waiting up to {args.timeout:.0f}s for the platform:")
    for name in checks:
        print(f"  {name}")

    deadline = time.monotonic() + args.timeout
    failures: dict[str, str] = {}
    while True:
        for name, check in list(checks.items()):
            try:
                failure = check()
            except AuthError as e:
                print(f"[ERROR] {e}", file=sys.stderr)
                return 1
            except (urllib.error.URLError, OSError, ValueError) as e:
                failure = str(e)
            if failure is None:
                print(f"  [OK] {name}")
                del checks[name]
                failures.pop(name, None)
            else:
                failures[name] = failure
        if not checks:
            print("The platform is up.")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(args.interval)

    print(f"\n[ERROR] Not ready after {args.timeout:.0f}s:", file=sys.stderr)
    for name, failure in failures.items():
        print(f"  {name}: {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
