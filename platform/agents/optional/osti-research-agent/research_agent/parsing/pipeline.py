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

"""Parse ladder: cheap PyMuPDF pre-check -> docling worker (subprocess) ->
PyMuPDF full-text fallback. Produces one artifact directory per paper and
caches the whole directory as a tar blob in Redis.

    parsed = await parse_paper_pipeline(pdf_path, source_id, config, caches, emit)

This is the only PDF-processing path.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import signal
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Optional, Tuple

import research_agent
from research_agent.core.config import AgentConfig
from research_agent.core.llm import LiteLLMVlmClient, VlmCompleteFn
from research_agent.memory import ArtifactCache
from research_agent.parsing.artifacts import ParsedPaper, paper_dir
from research_agent.parsing.figures import analyze_figures

logger = logging.getLogger(__name__)

EmitFn = Callable[..., Awaitable[None]]

# Don't cache absurdly large artifact dirs (huge scanned reports with many
# figure PNGs) - the tar would dominate Redis memory. Uncached still works.
_MAX_CACHE_BYTES = 25 * 1024 * 1024
_CACHE_TTL_S = 30 * 24 * 3600
# A scan is a PDF with essentially no embedded text on its opening pages.
_SCAN_TEXT_THRESHOLD = 100

_SUBPROCESS_ENV = {
    "CUDA_VISIBLE_DEVICES": "",
    "TORCH_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


async def _noop_emit(message: str, **detail) -> None:  # default when no emitter given
    return None


def _pymupdf():
    """The PyMuPDF module (``pymupdf``, or ``fitz`` on older releases), or None."""
    try:
        import pymupdf as fitz  # noqa: N813
    except Exception:
        try:
            import fitz
        except Exception:
            return None
    return fitz


def _precheck(pdf_path: str) -> Tuple[Optional[int], int]:
    """(page_count, chars on the first 3 pages). Cheap; used to detect scans."""
    fitz = _pymupdf()
    if fitz is None:
        return None, 0
    try:
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count
            chars = 0
            for i in range(min(3, page_count)):
                chars += len(doc.load_page(i).get_text() or "")
            return page_count, chars
    except Exception as e:
        logger.warning("[parse] pre-check failed for %s: %s", pdf_path, e)
        return None, 0


def _decide_ocr(mode: str, page_count: Optional[int], head_chars: int) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    # auto: OCR only when there are pages but no extractable text (a scan).
    return bool(page_count) and head_chars < _SCAN_TEXT_THRESHOLD


def _package_root() -> str:
    # Directory that *contains* the research_agent package, so the worker
    # subprocess can `import research_agent` regardless of cwd.
    return str(Path(research_agent.__file__).resolve().parents[1])


async def _run_docling_worker(
    pdf_path: str, outdir: Path, options: dict, timeout: int
) -> Optional[ParsedPaper]:
    """Run the docling worker as a child process with a hard timeout.

    Async (not ``subprocess.run`` in a thread) so that cancelling the parse -
    the runner does this when the outer time budget fires - kills the child
    instead of leaving it burning CPU until its own timeout."""
    root = _package_root()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        import json as _json

        f.write(_json.dumps(options))
        options_path = f.name

    cmd = [
        sys.executable,
        "-m",
        "research_agent.parsing.docling_worker",
        pdf_path,
        str(outdir),
        options_path,
    ]
    env = {
        **os.environ,
        **_SUBPROCESS_ENV,
        "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=root,
                env=env,
            )
        except Exception as e:
            logger.error("[parse] docling worker failed to launch: %s", e)
            return None
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            await _kill(proc)
            logger.error("[parse] docling worker timed out after %ss", timeout)
            return None
        except asyncio.CancelledError:
            await _kill(proc)
            raise
    finally:
        try:
            os.unlink(options_path)
        except OSError:
            pass

    if proc.returncode == -signal.SIGKILL:
        # Not our timeout (that path returns above): the kernel's OOM killer.
        logger.error(
            "[parse] docling worker was killed (SIGKILL), most likely out of "
            "memory; falling back to PyMuPDF text. Give Docker more memory, or "
            "lower DOCLING_IMAGES_SCALE / set DOCLING_TABLE_MODE=fast."
        )
        return None
    if proc.returncode != 0:
        logger.error(
            "[parse] docling worker exited %s: %s",
            proc.returncode,
            stderr.decode(errors="replace")[-500:],
        )
        return None
    try:
        # meta.json on disk is the source of truth; stdout is a fallback.
        return ParsedPaper.load(outdir)
    except Exception:
        try:
            return ParsedPaper.model_validate_json(stdout.decode(errors="replace"))
        except Exception as e:
            logger.error("[parse] could not read worker output: %s", e)
            return None


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        proc.kill()
        await proc.wait()


def _pymupdf_text(pdf_path: str) -> str:
    """Plain text of every page, or "" when PyMuPDF can't read the PDF."""
    fitz = _pymupdf()
    if fitz is None:
        return ""
    try:
        with fitz.open(pdf_path) as doc:
            pages = []
            for page_number in range(doc.page_count):
                try:
                    pages.append(doc.load_page(page_number).get_text() or "")
                except Exception as e:
                    logger.warning("[parse] PyMuPDF failed on page %d: %s", page_number + 1, e)
                    pages.append("")
            return "\n\n".join(pages)
    except Exception as e:
        logger.error("[parse] PyMuPDF could not open %s: %s", pdf_path, e)
        return ""


def _pymupdf_fallback(
    pdf_path: str, outdir: Path, source_id: str, page_count: Optional[int]
) -> ParsedPaper:
    text = _pymupdf_text(pdf_path)
    (outdir / "paper.md").write_text(text, encoding="utf-8")
    parsed = ParsedPaper(
        source_id=source_id,
        method="pymupdf",
        page_count=page_count,
        char_count=len(text),
        warnings=[
            "tables and figures unavailable (PyMuPDF fallback: docling failed or timed out)"
        ],
    )
    parsed.write_meta(outdir)
    return parsed


def _tar_dir(base: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(base, arcname=".")
    return buf.getvalue()


def _untar_into(blob: bytes, base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Defensive: never let a cached tar write outside the paper dir.
            dest = (base / member.name).resolve()
            if not str(dest).startswith(str(base.resolve())):
                continue
            # filter="data" (py3.12+) also rejects absolute paths, traversal,
            # and unsafe metadata - defense in depth behind the check above.
            tar.extract(member, base, filter="data")


async def parse_paper_pipeline(
    pdf_path: str,
    source_id: str,
    config: AgentConfig,
    caches: Optional[ArtifactCache] = None,
    emit: Optional[EmitFn] = None,
    vlm_complete: Optional[VlmCompleteFn] = None,
    deadline: Optional[float] = None,
) -> ParsedPaper:
    """Parse one downloaded PDF into ``papers/{source_id}/`` and return its
    :class:`ParsedPaper`. Uses ``caches`` (if given) to skip re-parsing."""
    emit = emit or _noop_emit
    out = paper_dir(config.workdir, source_id)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Artifact-directory cache hit -> untar and return.
    if caches is not None:
        try:
            blob = caches.get_artifacts(source_id)
        except Exception as e:
            logger.warning("[parse] artifact cache read failed: %s", e)
            blob = None
        if blob:
            try:
                _untar_into(blob, out)
                parsed = ParsedPaper.load(out)
                logger.info("[parse] %s served from artifact cache", source_id)
                return parsed
            except Exception as e:
                logger.warning("[parse] artifact cache untar failed, re-parsing: %s", e)

    # 2. Cheap pre-check: page count + is this a scan (needs OCR)?
    page_count, head_chars = _precheck(pdf_path)
    do_ocr = _decide_ocr(config.parse_ocr, page_count, head_chars)
    if do_ocr:
        await emit(f"PDF looks scanned; parsing OSTI #{source_id} with OCR (slower)...")

    # 3. Docling worker (subprocess, hard timeout).
    await emit(f"Parsing OSTI #{source_id} (docling: tables + figures)...")
    options = {
        "do_ocr": do_ocr,
        "images_scale": config.docling_images_scale,
        "table_mode": config.docling_table_mode,
        "source_id": source_id,
        "min_figure_area": config.min_figure_area,
    }
    parsed = await _run_docling_worker(
        pdf_path, out, options, config.docling_timeout_s
    )

    if parsed is None:
        # 4. Fallback to PyMuPDF full text; still emit one code path (paper.md).
        await emit(
            f"Docling failed for OSTI #{source_id}; falling back to PyMuPDF text."
        )
        parsed = _pymupdf_fallback(pdf_path, out, source_id, page_count)
    else:
        await emit(
            f"Parsed OSTI #{source_id}: {len(parsed.tables)} table(s), {len(parsed.figures)} figure(s)."
        )
        # Optional figure analysis, disabled unless explicitly configured.
        if config.analyze_figures and parsed.figures:
            vlm_route = config.model_route("vlm")
            vlm = (
                vlm_complete
                or LiteLLMVlmClient(
                    vlm_route.base_url,
                    vlm_route.api_key,
                    vlm_route.model,
                ).complete
            )
            await emit(
                f"Analyzing {min(len(parsed.figures), config.max_figures)} figure(s)..."
            )
            parsed = await analyze_figures(
                parsed,
                out,
                vlm,
                max_figures=config.max_figures,
                deadline=deadline,
                cache=caches,
            )
            parsed.write_meta(out)

    # 5. Cache the whole artifact directory (size-capped).
    if caches is not None:
        try:
            blob = _tar_dir(out)
            if len(blob) <= _MAX_CACHE_BYTES:
                caches.put_artifacts(source_id, blob, ttl_s=_CACHE_TTL_S)
            else:
                logger.info(
                    "[parse] %s artifact dir too large to cache (%d bytes)",
                    source_id,
                    len(blob),
                )
        except Exception as e:
            logger.warning("[parse] artifact cache write failed: %s", e)

    return parsed
