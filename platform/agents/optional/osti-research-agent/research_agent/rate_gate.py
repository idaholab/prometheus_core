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

"""A request gate shared by every process on one host.

arXiv asks for at most one request every 3 seconds, one connection at a
time, across all of a client's machines. An in-process timer covers only one
process, but the agent server and ``python -m evals`` run side by side in the
same container. This gate keeps the time of the last request in a file and
holds an exclusive ``flock`` on it: a caller waits for the lock, waits out
the rest of the interval, makes its request while still holding the lock, and
records when the request ended. Requests through one gate therefore never
overlap and never start less than the interval after the previous one ended,
whichever process makes them.

The file lives in ``RATE_GATE_DIR`` (default: the system temp directory), so
the gate covers the processes that share that directory - one container, or
several containers given the same volume. It cannot see other hosts.
Without ``fcntl`` (not POSIX) it only spaces requests within one process.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - not POSIX
    fcntl = None  # type: ignore[assignment]

# How often an async caller retries a lock another caller holds.
_POLL_S = 0.05


class RateGate:
    """One request at a time, each starting at least ``interval_s`` after the
    previous one through this gate ended."""

    def __init__(self, name: str, interval_s: float):
        self.name = name
        self.interval_s = interval_s
        self._last = 0.0  # used only without fcntl

    @property
    def path(self) -> Path:
        directory = Path(os.getenv("RATE_GATE_DIR") or tempfile.gettempdir())
        return directory / f"research-agent-{self.name}.gate"

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold the gate for one request made inside the ``async with``."""
        if self.interval_s <= 0:
            yield
            return
        fd = self._open()
        try:
            if fd is not None:
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(_POLL_S)
            await asyncio.sleep(self._wait_s(fd))
            try:
                yield
            finally:
                self._record(fd)
        finally:
            if fd is not None:
                os.close(fd)  # also releases the lock

    @contextlib.contextmanager
    def slot_sync(self) -> Iterator[None]:
        """Blocking ``slot`` for synchronous code (e.g. inside a worker thread)."""
        if self.interval_s <= 0:
            yield
            return
        fd = self._open()
        try:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            time.sleep(self._wait_s(fd))
            try:
                yield
            finally:
                self._record(fd)
        finally:
            if fd is not None:
                os.close(fd)

    def _open(self) -> Optional[int]:
        if fcntl is None:
            return None
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(path, os.O_RDWR | os.O_CREAT, 0o666)

    def _wait_s(self, fd: Optional[int]) -> float:
        # Wall-clock time, because it is shared between processes. Capped at
        # one interval so a clock that went back cannot stall the gate.
        last = self._last if fd is None else _read_last(fd)
        return max(0.0, min(self.interval_s - (time.time() - last), self.interval_s))

    def _record(self, fd: Optional[int]) -> None:
        now = time.time()
        self._last = now
        if fd is None:
            return
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, f"{now:.6f}".encode())
        except OSError:
            pass


def _read_last(fd: int) -> float:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        return float(os.read(fd, 64).decode().strip() or 0.0)
    except (OSError, ValueError):
        return 0.0
