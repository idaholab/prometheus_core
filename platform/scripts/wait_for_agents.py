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

"""Wait until every given agent has registered with the running LiteLLM proxy.

Each argument is an agent directory holding an ``agent_card.json``. The agent's
registry name is derived from the card the same way the SDK does
(``AgentRegistryClient.agent_name``). Polls ``GET /v1/agents`` on
``LITELLM_LOCAL_PORT`` with ``LITELLM_MASTER_KEY``, both read from the
environment or else from .env, until all are listed or the timeout passes.

A container's /health only shows that uvicorn is serving; registration runs in
the background and an agent keeps running even if it gives up, so this is the
check that the platform can actually route to it.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def env_value(name: str, default: str | None = None) -> str | None:
    if value := os.environ.get(name):
        return value
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and value.strip():
                return value.strip()
    return default


def registry_name(agent_dir: Path) -> str:
    card = json.loads((agent_dir / "agent_card.json").read_text())
    return card["name"].lower().replace(" ", "-")


def registered(url: str, master_key: str) -> set[str]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {master_key}"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return {agent["agent_name"] for agent in json.load(response)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("agent_dirs", nargs="+", type=Path, help="agent directories with an agent_card.json")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait (default: 300)")
    parser.add_argument("--interval", type=float, default=5, help="seconds between polls (default: 5)")
    args = parser.parse_args()

    master_key = env_value("LITELLM_MASTER_KEY")
    if not master_key:
        print(f"[ERROR] LITELLM_MASTER_KEY is not set in the environment or {ENV}.", file=sys.stderr)
        return 1
    url = f"http://localhost:{env_value('LITELLM_LOCAL_PORT', '9977')}/v1/agents"

    expected = {registry_name(d) for d in args.agent_dirs}
    print(f"Waiting up to {args.timeout:.0f}s for {len(expected)} agent(s) to register at {url}:")
    for name in sorted(expected):
        print(f"  {name}")

    deadline = time.monotonic() + args.timeout
    found: set[str] = set()
    while True:
        try:
            found = registered(url, master_key) & expected
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"  registry not ready: {e}")
        if found == expected:
            print(f"All {len(expected)} agent(s) registered.")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(args.interval)

    print(f"\n[ERROR] Agent(s) not registered after {args.timeout:.0f}s:", file=sys.stderr)
    for name in sorted(expected - found):
        print(f"  {name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
