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

"""Is the running platform reachable from the host, and is every agent registered?

Ported from `scripts/check_platform.py`. `docker compose up --wait` covers the container healthchecks,
which probe from inside each container. These checks cover what they can't see: the published host
ports, the frontend's proxy, and registry registration, which runs in the background while an agent
keeps serving even if it gives up.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from platformctl.system import http

OK = ""
"""What a check returns when it passes; anything else says what is missing."""


class AuthError(Exception):
    """The registry rejected `AGENT_SECRET`, so polling again cannot help."""


@dataclass(frozen=True)
class Readiness:
    """One thing to wait for: a name, and a function that returns `OK` or says what is missing."""

    name: str
    """What is being waited for, such as `backend`."""
    check: Callable[[], str]
    """Returns `OK` once it holds, else a short reason."""
    doctor_check: str = ""
    """The `doctor` check that explains a failure, or an empty string."""


def poll(
    items: list[Readiness],
    timeout: float,
    interval: float,
    *,
    on_ok: Callable[[Readiness], None] = lambda item: None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, str]:
    """Check every item until all pass or `timeout` seconds pass; return the reasons for those that never did.

    An item is dropped once it passes (`on_ok` is told). Every item is tried at least once, even with
    a timeout of 0. A rejected agent secret (`AuthError`) ends the run at once.
    """
    pending = {item.name: item for item in items}
    failures: dict[str, str] = {}
    deadline = clock() + timeout
    while True:
        for name, item in list(pending.items()):
            reason = item.check()
            if reason == OK:
                on_ok(item)
                del pending[name]
                failures.pop(name, None)
            else:
                failures[name] = reason
        if not pending or clock() >= deadline:
            return failures
        sleep(interval)


def registry_name(agent_dir: Path) -> str:
    """The name the agent registers under, from its `agent_card.json`, as the SDK derives it."""
    card = json.loads((agent_dir / "agent_card.json").read_text())
    return card["name"].lower().replace(" ", "-")


def registered(url: str, agent_secret: str) -> set[str]:
    """The agent names the registry lists; malformed entries are skipped.

    Raises `AuthError` for a 401 or 403, and `ValueError` when the answer is not a JSON list or
    nothing answers.
    """
    code, entries = http.request_json("GET", url, headers={"Authorization": f"Bearer {agent_secret}"}, timeout=10)
    if code in (401, 403):
        raise AuthError("The agent registry rejected AGENT_SECRET")
    if code != 200:
        raise ValueError("the registry did not answer" if code is None else f"the registry answered HTTP {code}")
    if not isinstance(entries, list):
        raise ValueError(f"unexpected /v1/agents response: {type(entries).__name__}")
    return {
        entry["agent_name"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("agent_name"), str)
    }


def http_ok(url: str) -> Callable[[], str]:
    """A check that passes once `url` answers with a 2xx status."""

    def check() -> str:
        """`OK` on a 2xx; else the status, or that nothing answered."""
        code = http.status(url, timeout=10)
        if code is None:
            return "no answer"
        return OK if 200 <= code < 300 else f"HTTP {code}"

    return check


def agents_registered(url: str, agent_secret: str, expected: set[str]) -> Callable[[], str]:
    """A check that passes once every expected agent is registered; extra agents are fine."""

    def check() -> str:
        """`OK`, or `not registered:` and the missing names; a failed lookup says why."""
        try:
            missing = expected - registered(url, agent_secret)
        except ValueError as exc:
            return str(exc)
        return f"not registered: {', '.join(sorted(missing))}" if missing else OK

    return check
