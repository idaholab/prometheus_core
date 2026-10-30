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

"""`urllib` helpers. Loopback URLs bypass any proxy, so HTTP_PROXY can't break health checks.

Never prints request headers or bodies.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlparse

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _opener(url: str) -> urllib.request.OpenerDirector:
    host = urlparse(url).hostname or ""
    if host in _LOOPBACK:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def status(url: str, timeout: float = 5.0, headers: dict[str, str] | None = None) -> int | None:
    """The HTTP status of a GET, or None when nothing answers."""
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with _opener(url).open(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait(
    url: str,
    timeout: float,
    *,
    interval: float = 1.0,
    ok: Callable[[int], bool] = lambda code: 200 <= code < 400,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll `url` until `ok(status)` or the timeout passes."""
    deadline = clock() + timeout
    while True:
        code = status(url, timeout=min(5.0, max(timeout, 1.0)))
        if code is not None and ok(code):
            return True
        if clock() >= deadline:
            return False
        sleep(interval)
