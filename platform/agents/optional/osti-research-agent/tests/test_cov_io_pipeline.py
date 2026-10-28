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
"""Tests for the parse ladder's PyMuPDF helpers, worker exits and cache paths."""

import asyncio
import sys
import types
from pathlib import Path

import pymupdf

from research_agent.core.config import AgentConfig
from research_agent.parsing import pipeline as pp
from research_agent.parsing.artifacts import FigureArtifact, ParsedPaper, paper_dir


def _make_pdf(path: Path, pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return str(path)


# --- _pymupdf ------------------------------------------------------------------


def test_pymupdf_falls_back_to_fitz_module(monkeypatch):
    fake_fitz = types.ModuleType("fitz")
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    assert pp._pymupdf() is fake_fitz


def test_pymupdf_is_none_when_neither_module_imports(monkeypatch):
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", None)

    assert pp._pymupdf() is None
    assert pp._precheck("any.pdf") == (None, 0)
    assert pp._pymupdf_text("any.pdf") == ""


def test_pymupdf_returns_the_real_module():
    assert pp._pymupdf() is pymupdf


# --- _precheck / _pymupdf_text ---------------------------------------------------


def test_precheck_counts_pages_and_head_chars(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", ["alpha", "beta", "gamma", "delta"])

    page_count, chars = pp._precheck(pdf)

    assert page_count == 4
    # Only the first three pages are sampled.
    assert chars == len("alpha\n") + len("beta\n") + len("gamma\n")


def test_precheck_reports_unreadable_pdf_as_unknown(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")

    assert pp._precheck(str(bad)) == (None, 0)


def test_pymupdf_text_joins_every_page(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf", ["first page", "second page"])

    text = pp._pymupdf_text(pdf)

    assert "first page" in text and "second page" in text
    assert text.index("first page") < text.index("second page")


def test_pymupdf_text_is_empty_for_unreadable_pdf(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"garbage")

    assert pp._pymupdf_text(str(bad)) == ""


def test_pymupdf_text_keeps_going_when_one_page_fails(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def get_text(self):
            return self.text

    class Doc:
        page_count = 3

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def load_page(self, i):
            if i == 1:
                raise RuntimeError("corrupt page")
            return Page(f"page{i}")

    fake = types.SimpleNamespace(open=lambda path: Doc())
    monkeypatch.setattr(pp, "_pymupdf", lambda: fake)

    assert pp._pymupdf_text("x.pdf") == "page0\n\n\n\npage2"


# --- _run_docling_worker exit handling -------------------------------------------


class FakeProc:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._out = (stdout, stderr)

    async def communicate(self):
        return self._out


def _fake_exec(monkeypatch, proc=None, raises=None, seen=None):
    async def fake(*cmd, **kwargs):
        if seen is not None:
            seen["cmd"] = cmd
            seen["options"] = Path(cmd[-1]).read_text()
        if raises is not None:
            raise raises
        return proc

    monkeypatch.setattr(pp.asyncio, "create_subprocess_exec", fake)


def test_worker_launch_failure_returns_none(tmp_path, monkeypatch):
    seen = {}
    _fake_exec(monkeypatch, raises=OSError("no python"), seen=seen)

    out = asyncio.run(pp._run_docling_worker("x.pdf", tmp_path, {"a": 1}, timeout=5))

    assert out is None
    assert seen["options"] == '{"a": 1}'
    assert not Path(seen["cmd"][-1]).exists()  # options file cleaned up


def test_worker_nonzero_exit_returns_none_and_logs_stderr(tmp_path, monkeypatch, caplog):
    _fake_exec(monkeypatch, FakeProc(1, stderr=b"Traceback: boom"))

    with caplog.at_level("ERROR", logger="research_agent.parsing.pipeline"):
        out = asyncio.run(pp._run_docling_worker("x.pdf", tmp_path, {}, timeout=5))

    assert out is None
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_worker_output_read_from_meta_json(tmp_path, monkeypatch):
    ParsedPaper(source_id="m", method="docling", char_count=3).write_meta(tmp_path)
    _fake_exec(monkeypatch, FakeProc(0, stdout=b"ignored"))

    out = asyncio.run(pp._run_docling_worker("x.pdf", tmp_path, {}, timeout=5))

    assert out.source_id == "m"


def test_worker_output_falls_back_to_stdout_without_meta(tmp_path, monkeypatch):
    stdout = ParsedPaper(source_id="s", method="docling").model_dump_json().encode()
    _fake_exec(monkeypatch, FakeProc(0, stdout=stdout))

    out = asyncio.run(pp._run_docling_worker("x.pdf", tmp_path / "none", {}, timeout=5))

    assert out.source_id == "s"


def test_worker_unreadable_output_returns_none(tmp_path, monkeypatch):
    _fake_exec(monkeypatch, FakeProc(0, stdout=b"not json"))

    out = asyncio.run(pp._run_docling_worker("x.pdf", tmp_path / "none", {}, timeout=5))

    assert out is None


def test_worker_tolerates_options_file_already_gone(tmp_path, monkeypatch):
    async def fake(*cmd, **kwargs):
        Path(cmd[-1]).unlink()  # the finally-unlink then hits OSError
        return FakeProc(0, stdout=b"not json")

    monkeypatch.setattr(pp.asyncio, "create_subprocess_exec", fake)

    assert asyncio.run(pp._run_docling_worker("x.pdf", tmp_path, {}, timeout=5)) is None


# --- parse_paper_pipeline -------------------------------------------------------------


class Cache:
    def __init__(self, blob=None, fail_get=False, fail_put=False):
        self.blobs = {} if blob is None else {"7": blob}
        self.fail_get = fail_get
        self.fail_put = fail_put
        self.figjson = {}

    def get_artifacts(self, key):
        if self.fail_get:
            raise ConnectionError("down")
        return self.blobs.get(key)

    def put_artifacts(self, key, data, ttl_s):
        if self.fail_put:
            raise ConnectionError("down")
        self.blobs[key] = data

    def get_figjson(self, source_id, idx):
        return self.figjson.get((source_id, idx))

    def put_figjson(self, source_id, idx, data, ttl_s):
        self.figjson[(source_id, idx)] = data


def _config(tmp_path, **kw):
    return AgentConfig(litellm_base_url="http://unused", workdir=tmp_path, **kw)


def _fallback_only(monkeypatch, precheck=(2, 500)):
    async def no_worker(*a, **k):
        return None

    monkeypatch.setattr(pp, "_precheck", lambda p: precheck)
    monkeypatch.setattr(pp, "_run_docling_worker", no_worker)
    monkeypatch.setattr(pp, "_pymupdf_text", lambda p: "TEXT")


def _recorder():
    messages = []

    async def emit(message, **detail):
        messages.append(message)

    return messages, emit


def test_cache_read_failure_reparses_and_still_writes_cache(tmp_path, monkeypatch):
    _fallback_only(monkeypatch)
    cache = Cache(fail_get=True)

    parsed = asyncio.run(pp.parse_paper_pipeline("d.pdf", "7", _config(tmp_path), cache))

    assert parsed.method == "pymupdf"
    assert "7" in cache.blobs


def test_corrupt_cached_blob_is_ignored_and_reparsed(tmp_path, monkeypatch):
    _fallback_only(monkeypatch)
    cache = Cache(blob=b"not a tarball")

    parsed = asyncio.run(pp.parse_paper_pipeline("d.pdf", "7", _config(tmp_path), cache))

    assert parsed.method == "pymupdf"
    assert cache.blobs["7"] != b"not a tarball"  # replaced by the fresh parse


def test_scanned_pdf_emits_ocr_notice_and_requests_ocr(tmp_path, monkeypatch):
    seen = {}

    async def worker(pdf, outdir, options, timeout):
        seen.update(options)
        return None

    monkeypatch.setattr(pp, "_precheck", lambda p: (4, 0))
    monkeypatch.setattr(pp, "_run_docling_worker", worker)
    monkeypatch.setattr(pp, "_pymupdf_text", lambda p: "")
    messages, emit = _recorder()

    asyncio.run(pp.parse_paper_pipeline("d.pdf", "7", _config(tmp_path), emit=emit))

    assert seen["do_ocr"] is True
    assert "looks scanned" in messages[0]


def test_oversized_artifact_dir_is_not_cached(tmp_path, monkeypatch):
    _fallback_only(monkeypatch)
    monkeypatch.setattr(pp, "_MAX_CACHE_BYTES", 1)
    cache = Cache()

    asyncio.run(pp.parse_paper_pipeline("d.pdf", "7", _config(tmp_path), cache))

    assert cache.blobs == {}


def test_cache_write_failure_does_not_fail_the_parse(tmp_path, monkeypatch):
    _fallback_only(monkeypatch)

    parsed = asyncio.run(
        pp.parse_paper_pipeline("d.pdf", "7", _config(tmp_path), Cache(fail_put=True))
    )

    assert parsed.method == "pymupdf"


def _docling_with_figure(monkeypatch):
    async def worker(pdf, outdir, options, timeout):
        outdir = Path(outdir)
        (outdir / "figures").mkdir(parents=True, exist_ok=True)
        (outdir / "figures" / "fig_01.png").write_bytes(b"png")
        parsed = ParsedPaper(
            source_id=options["source_id"], method="docling",
            figures=[FigureArtifact(index=1, png_path="figures/fig_01.png")],
        )
        parsed.write_meta(outdir)
        return parsed

    monkeypatch.setattr(pp, "_precheck", lambda p: (2, 500))
    monkeypatch.setattr(pp, "_run_docling_worker", worker)


def test_figure_analysis_uses_injected_vlm(tmp_path, monkeypatch):
    _docling_with_figure(monkeypatch)
    seen = {}

    async def fake_analyze(parsed, out, vlm, *, max_figures, deadline, cache):
        seen.update(vlm=vlm, max_figures=max_figures, deadline=deadline)
        parsed.figures[0].analyzed = True
        return parsed

    async def vlm(prompt, images, *, max_tokens, temperature=0):
        return "{}"

    monkeypatch.setattr(pp, "analyze_figures", fake_analyze)
    messages, emit = _recorder()
    config = _config(tmp_path, analyze_figures=True, max_figures=3)

    parsed = asyncio.run(pp.parse_paper_pipeline(
        "d.pdf", "7", config, emit=emit, vlm_complete=vlm, deadline=123.0))

    assert parsed.method == "docling"
    assert seen == {"vlm": vlm, "max_figures": 3, "deadline": 123.0}
    assert "Analyzing 1 figure(s)..." in messages
    # The analyzed flag is persisted to meta.json.
    assert ParsedPaper.load(paper_dir(tmp_path, "7")).figures[0].analyzed is True


def test_figure_analysis_defaults_to_litellm_vlm_client(tmp_path, monkeypatch):
    _docling_with_figure(monkeypatch)
    built = {}

    class FakeClient:
        def __init__(self, base_url, api_key, model):
            built.update(base_url=base_url, api_key=api_key, model=model)

        async def complete(self, prompt, images, *, max_tokens, temperature=0):
            return "{}"

    async def fake_analyze(parsed, out, vlm, **kw):
        built["vlm_owner"] = type(vlm.__self__)
        return parsed

    monkeypatch.setattr(pp, "LiteLLMVlmClient", FakeClient)
    monkeypatch.setattr(pp, "analyze_figures", fake_analyze)
    config = _config(tmp_path, analyze_figures=True)
    route = config.model_route("vlm")

    asyncio.run(pp.parse_paper_pipeline("d.pdf", "7", config))

    assert built["vlm_owner"] is FakeClient
    assert (built["base_url"], built["api_key"], built["model"]) == (
        route.base_url, route.api_key, route.model)


def test_figures_not_analyzed_unless_enabled(tmp_path, monkeypatch):
    _docling_with_figure(monkeypatch)

    async def must_not_run(*a, **k):
        raise AssertionError("figure analysis should be off")

    monkeypatch.setattr(pp, "analyze_figures", must_not_run)
    config = _config(tmp_path, analyze_figures=False)

    parsed = asyncio.run(pp.parse_paper_pipeline("d.pdf", "7", config))

    assert parsed.method == "docling"
    assert parsed.figures[0].analyzed is False
