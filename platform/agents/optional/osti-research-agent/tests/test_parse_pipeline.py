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

"""Tests for the parsing pipeline: automatic OCR selection, cache
round-tripping with path-traversal protection, the PyMuPDF fallback, and the
artifact-cache short circuit.

The docling subprocess is monkeypatched out - these test the ladder's control
flow, not docling itself (that's the @slow golden corpus)."""

import asyncio
import os
import io
import tarfile
from pathlib import Path

from research_agent.core.config import AgentConfig
from research_agent.parsing import pipeline as pp
from research_agent.parsing.artifacts import ParsedPaper, paper_dir

# --- _decide_ocr -----------------------------------------------------------


def test_decide_ocr_forced_modes():
    assert pp._decide_ocr("on", 10, 9999) is True
    assert pp._decide_ocr("off", 0, 0) is False


def test_decide_ocr_auto_detects_scan():
    # pages present but almost no extractable text -> a scan -> OCR
    assert pp._decide_ocr("auto", 5, 10) is True
    # plenty of embedded text -> no OCR
    assert pp._decide_ocr("auto", 5, 5000) is False
    # no pages at all -> nothing to OCR
    assert pp._decide_ocr("auto", None, 0) is False
    assert pp._decide_ocr("auto", 0, 0) is False


# --- tar/untar cache blob --------------------------------------------------


def test_tar_untar_roundtrip(tmp_path):
    src = tmp_path / "src"
    (src / "tables").mkdir(parents=True)
    (src / "paper.md").write_text("hello")
    (src / "tables" / "t.csv").write_text("a,b\n1,2\n")

    blob = pp._tar_dir(src)
    dest = tmp_path / "dest"
    pp._untar_into(blob, dest)

    assert (dest / "paper.md").read_text() == "hello"
    assert (dest / "tables" / "t.csv").read_text() == "a,b\n1,2\n"


def test_untar_rejects_path_traversal(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"pwned"
        info = tarfile.TarInfo(name="../evil.txt")  # tries to escape dest
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    dest = tmp_path / "dest"
    pp._untar_into(buf.getvalue(), dest)

    assert not (tmp_path / "evil.txt").exists()


# --- fallback + cache in parse_paper_pipeline ------------------------------


class FakeArtifactCache:
    def __init__(self):
        self.blobs = {}
        self.figjson = {}

    def get_artifacts(self, key):
        return self.blobs.get(key)

    def put_artifacts(self, key, data, ttl_s):
        self.blobs[key] = data

    def get_figjson(self, source_id, idx):
        return self.figjson.get((source_id, idx))

    def put_figjson(self, source_id, idx, data, ttl_s):
        self.figjson[(source_id, idx)] = data


def test_pipeline_falls_back_to_pymupdf(tmp_path, monkeypatch):
    config = AgentConfig(litellm_base_url="http://unused", workdir=tmp_path)
    monkeypatch.setattr(pp, "_precheck", lambda p: (3, 500))
    async def no_worker(*a, **k):
        return None

    monkeypatch.setattr(pp, "_run_docling_worker", no_worker)
    monkeypatch.setattr(pp, "_pymupdf_text", lambda p: "FALLBACK TEXT")

    parsed = asyncio.run(
        pp.parse_paper_pipeline("dummy.pdf", "42", config, caches=None)
    )

    assert parsed.method == "pymupdf"
    assert parsed.warnings  # records that tables/figures are unavailable
    base = paper_dir(tmp_path, "42")
    assert (base / "paper.md").read_text() == "FALLBACK TEXT"


def test_pipeline_artifact_cache_roundtrip(tmp_path, monkeypatch):
    config = AgentConfig(litellm_base_url="http://unused", workdir=tmp_path)
    cache = FakeArtifactCache()
    calls = []

    async def fake_worker(pdf_path, outdir, options, timeout):
        calls.append(1)
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "paper.md").write_text("cached body")
        parsed = ParsedPaper(
            source_id=options["source_id"], method="docling", char_count=11
        )
        parsed.write_meta(outdir)
        return parsed

    monkeypatch.setattr(pp, "_precheck", lambda p: (2, 500))
    monkeypatch.setattr(pp, "_run_docling_worker", fake_worker)

    p1 = asyncio.run(pp.parse_paper_pipeline("d.pdf", "77", config, caches=cache))
    p2 = asyncio.run(pp.parse_paper_pipeline("d.pdf", "77", config, caches=cache))

    assert len(calls) == 1  # second call served entirely from the artifact cache
    assert p1.source_id == p2.source_id == "77"
    assert "77" in cache.blobs


def _slow_worker(monkeypatch, tmp_path):
    """Swap the worker module for a script that records its pid and sleeps."""
    pid_file = tmp_path / "pid"
    script = tmp_path / "slow.py"
    script.write_text(
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(python, *_args, **kwargs):
        return await real_exec(python, str(script), **kwargs)

    monkeypatch.setattr(pp.asyncio, "create_subprocess_exec", fake_exec)
    return pid_file


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _wait_for_pid(pid_file):
    for _ in range(200):
        if pid_file.exists() and pid_file.read_text():
            return int(pid_file.read_text())
        await asyncio.sleep(0.05)
    raise AssertionError("worker never started")


def test_docling_worker_killed_when_parse_is_cancelled(tmp_path, monkeypatch):
    pid_file = _slow_worker(monkeypatch, tmp_path)

    async def go():
        task = asyncio.create_task(
            pp._run_docling_worker("x.pdf", tmp_path / "out", {}, timeout=60)
        )
        pid = await _wait_for_pid(pid_file)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return pid

    assert not _alive(asyncio.run(go()))


def test_docling_worker_killed_on_timeout(tmp_path, monkeypatch):
    pid_file = _slow_worker(monkeypatch, tmp_path)

    result = asyncio.run(
        pp._run_docling_worker("x.pdf", tmp_path / "out", {}, timeout=1)
    )

    assert result is None
    assert not _alive(int(pid_file.read_text()))


def test_pipeline_passes_the_memory_settings_to_the_worker(tmp_path, monkeypatch):
    config = AgentConfig(
        litellm_base_url="http://unused",
        workdir=tmp_path,
        docling_images_scale=1.0,
        docling_table_mode="fast",
    )
    seen = {}

    async def worker(pdf_path, outdir, options, timeout):
        seen.update(options)
        return None

    monkeypatch.setattr(pp, "_precheck", lambda p: (3, 500))
    monkeypatch.setattr(pp, "_run_docling_worker", worker)
    monkeypatch.setattr(pp, "_pymupdf_text", lambda p: "TEXT")
    asyncio.run(pp.parse_paper_pipeline("d.pdf", "9", config, caches=None))

    assert (seen["images_scale"], seen["table_mode"]) == (1.0, "fast")


def test_oom_killed_worker_is_reported_as_out_of_memory(tmp_path, monkeypatch, caplog):
    script = tmp_path / "oom.py"
    script.write_text("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(python, *_args, **kwargs):
        return await real_exec(python, str(script), **kwargs)

    monkeypatch.setattr(pp.asyncio, "create_subprocess_exec", fake_exec)
    with caplog.at_level("ERROR", logger="research_agent.parsing.pipeline"):
        result = asyncio.run(
            pp._run_docling_worker("x.pdf", tmp_path / "out", {}, timeout=30)
        )

    assert result is None
    (record,) = [r for r in caplog.records if r.levelname == "ERROR"]
    assert "most likely out of memory" in record.getMessage()
    assert "DOCLING_IMAGES_SCALE" in record.getMessage()
