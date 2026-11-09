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

"""The host-wide rate gate: one request at a time, spaced by the interval,
across tasks, threads and processes."""

import asyncio
import multiprocessing
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from research_agent import osti_client, rate_gate
from research_agent.rate_gate import RateGate

pytestmark = pytest.mark.skipif(rate_gate.fcntl is None, reason="needs fcntl (POSIX)")

_PDF = b"%PDF-1.5\n... body ..."


def _record_spans(gate: RateGate, n: int):
    """Run n gated requests concurrently; return their (start, end) times."""
    spans = []

    async def one():
        async with gate.slot():
            start = time.time()
            await asyncio.sleep(0.02)
            spans.append((start, time.time()))

    async def main():
        await asyncio.gather(*(one() for _ in range(n)))

    asyncio.run(main())
    return sorted(spans)


def _assert_spaced(spans, interval):
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert start >= end, "requests overlapped"
        assert start - end >= interval - 0.02, "requests closer than the interval"


def test_async_requests_never_overlap_and_are_spaced(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    spans = _record_spans(RateGate("t", 0.15), 3)
    _assert_spaced(spans, 0.15)


def test_threads_share_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    gate = RateGate("t", 0.15)
    spans, lock = [], threading.Lock()

    def one():
        with gate.slot_sync():
            start = time.time()
            time.sleep(0.02)
            with lock:
                spans.append((start, time.time()))

    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _assert_spaced(sorted(spans), 0.15)


def _child(directory, interval, out):
    os.environ["RATE_GATE_DIR"] = directory
    gate = RateGate("t", interval)
    with gate.slot_sync():
        start = time.time()
        time.sleep(0.05)
        out.put((start, time.time()))


def test_separate_processes_share_the_gate(tmp_path):
    # The agent server and `python -m evals` are separate processes in one
    # container; the gate must space their requests too.
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    procs = [
        ctx.Process(target=_child, args=(str(tmp_path), 0.3, out)) for _ in range(2)
    ]
    for p in procs:
        p.start()
    spans = sorted(out.get(timeout=30) for _ in procs)
    for p in procs:
        p.join(timeout=30)
    _assert_spaced(spans, 0.3)


def test_the_interval_holds_after_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    gate = RateGate("t", 0.2)
    with pytest.raises(RuntimeError):
        with gate.slot_sync():
            raise RuntimeError("request failed")
    start = time.monotonic()
    with gate.slot_sync():
        pass
    assert time.monotonic() - start >= 0.18


def test_a_clock_that_went_back_waits_at_most_one_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    gate = RateGate("t", 0.2)
    gate.path.write_text(f"{time.time() + 3600:.6f}")  # last request "in the future"
    start = time.monotonic()
    with gate.slot_sync():
        pass
    assert time.monotonic() - start < 1.0


def test_a_zero_interval_does_not_wait_or_touch_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    gate = RateGate("t", 0.0)
    with gate.slot_sync():
        pass
    asyncio.run(_enter(gate))
    assert not gate.path.exists()


async def _enter(gate):
    async with gate.slot():
        pass


def test_without_fcntl_the_gate_still_spaces_within_a_process(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    monkeypatch.setattr(rate_gate, "fcntl", None)
    gate = RateGate("t", 0.15)
    with gate.slot_sync():
        pass
    start = time.monotonic()
    asyncio.run(_enter(gate))
    assert time.monotonic() - start >= 0.13
    assert not gate.path.exists()


def test_an_unreadable_gate_file_counts_as_no_previous_request(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    gate = RateGate("t", 5.0)
    gate.path.write_text("not a time")
    start = time.monotonic()
    with gate.slot_sync():
        pass
    assert time.monotonic() - start < 1.0


def test_a_failed_write_to_the_gate_file_does_not_fail_the_request(tmp_path, monkeypatch):
    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path))
    gate = RateGate("t", 0.2)

    def broken_write(fd, data):
        raise OSError("disk full")

    monkeypatch.setattr(rate_gate.os, "write", broken_write)
    with gate.slot_sync():
        pass  # the request itself went through


# --- PDF downloads ----------------------------------------------------------


def _ok_session():
    resp = MagicMock(status_code=200, headers={"Content-Type": "application/pdf"}, content=_PDF)
    session = MagicMock()
    session.get.return_value = resp
    return session


@pytest.mark.parametrize(
    "url, gated",
    [
        ("https://arxiv.org/pdf/2101.00001", True),
        ("http://export.arxiv.org/pdf/2101.00001v1", True),
        ("https://www.osti.gov/servlets/purl/1", False),
        ("https://evilarxiv.org/pdf/x", False),
    ],
)
def test_only_arxiv_downloads_are_gated(url, gated):
    assert (osti_client._download_gate(url) is osti_client.ARXIV_PDF_GATE) is gated


def test_arxiv_pdf_downloads_are_spaced(tmp_path, monkeypatch):
    monkeypatch.setattr(osti_client.ARXIV_PDF_GATE, "interval_s", 0.2)
    with patch.object(osti_client.requests, "Session", return_value=_ok_session()):
        assert osti_client.download_pdf_from_url(
            "https://arxiv.org/pdf/1", str(tmp_path / "1.pdf")
        )
        start = time.monotonic()
        assert osti_client.download_pdf_from_url(
            "https://arxiv.org/pdf/2", str(tmp_path / "2.pdf")
        )
    assert time.monotonic() - start >= 0.18


def test_other_hosts_and_cached_pdfs_do_not_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(osti_client.ARXIV_PDF_GATE, "interval_s", 30.0)
    cache = MagicMock()
    cache.get_pdf.return_value = _PDF
    start = time.monotonic()
    with patch.object(osti_client.requests, "Session", return_value=_ok_session()):
        # A cached arXiv PDF makes no request, so it does not take a turn.
        assert osti_client.download_pdf_from_url(
            "https://arxiv.org/pdf/1", str(tmp_path / "1.pdf"), cache=cache
        )
        assert osti_client.download_pdf_from_url(
            "https://zenodo.org/record/1/files/a.pdf", str(tmp_path / "2.pdf")
        )
    assert time.monotonic() - start < 1.0
