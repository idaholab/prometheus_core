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

"""Docling parse worker, run as an isolated subprocess.

    python -m research_agent.parsing.docling_worker <pdf> <outdir> <options.json>

Docling (torch under the hood) can hang or OOM, so the parent
(:mod:`research_agent.parsing.pipeline`) runs this with a hard
``subprocess.run(timeout=...)`` and CPU-only env. This module writes the
artifact directory directly (``paper.md``, ``tables/``, ``figures/``,
``meta.json``) and prints the resulting :class:`ParsedPaper` JSON on stdout.

Heavy imports (docling/torch/pandas) live inside :func:`parse` so importing
this module - e.g. to unit-test the pure helpers - stays cheap.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_agent.parsing.artifacts import FigureArtifact, ParsedPaper, TableArtifact

# CPU-only, single-threaded: keep torch from grabbing GPUs or spawning a
# thread storm inside the already-isolated subprocess. The parent sets these
# too, but set them here before any torch import as a belt-and-suspenders.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("TORCH_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

logger = logging.getLogger(__name__)

# Labels that carry running prose we want verbatim in paper.md.
_TEXT_LABELS = {
    "text",
    "paragraph",
    "reference",
    "footnote",
    "code",
    "formula",
    "caption",
}


def _page_no(item: Any) -> Optional[int]:
    prov = getattr(item, "prov", None)
    if prov:
        try:
            return int(prov[0].page_no)
        except Exception:
            return None
    return None


def _heading_prefix(item: Any) -> str:
    level = getattr(item, "level", 1) or 1
    return "#" * min(1 + int(level), 6)


def build_markdown(
    doc: Any, table_markers: Dict[str, str], figure_markers: Dict[str, str]
) -> str:
    """Render the document in reading order, replacing tables and (kept)
    figures with ``[TABLE table_NN]`` / ``[FIGURE fig_NN]`` locator lines so a
    reader can find the corresponding artifact file. Table/figure *content*
    lives in ``tables/`` and ``figures/`` - paper.md stays compact.
    """
    lines: List[str] = []
    for item, _level in doc.iterate_items():
        ref = getattr(item, "self_ref", None)
        label = getattr(
            getattr(item, "label", None), "value", getattr(item, "label", None)
        )

        if ref in table_markers:
            cap = (getattr(item, "caption_text", lambda _d: "")(doc) or "").strip()
            lines.append(f"[TABLE {table_markers[ref]}]" + (f" {cap}" if cap else ""))
            continue
        if ref in figure_markers:
            cap = (getattr(item, "caption_text", lambda _d: "")(doc) or "").strip()
            lines.append(f"[FIGURE {figure_markers[ref]}]" + (f" {cap}" if cap else ""))
            continue

        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if label == "title":
            lines.append(f"# {text}")
        elif label == "section_header":
            lines.append(f"{_heading_prefix(item)} {text}")
        elif label == "list_item":
            lines.append(f"- {text}")
        elif label in _TEXT_LABELS:
            lines.append(text)
        # picture/table children and unknown structural nodes: skipped

    return "\n\n".join(lines).strip() + "\n"


def _pipeline_options(options: Dict[str, Any]):
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

    opts = PdfPipelineOptions(
        do_table_structure=True,
        generate_picture_images=True,
        images_scale=float(options.get("images_scale", 2.0)),
        do_ocr=bool(options.get("do_ocr", False)),
    )
    opts.layout_options.engine_options.compile_model = False
    opts.table_structure_options.mode = (
        TableFormerMode.FAST
        if options.get("table_mode") == "fast"
        else TableFormerMode.ACCURATE
    )
    return opts


def parse(pdf_path: str, outdir: str, options: Dict[str, Any]) -> ParsedPaper:
    """Convert one PDF into the artifact directory and return its ParsedPaper."""
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=_pipeline_options(options)
            )
        }
    )
    result = converter.convert(pdf_path)
    doc = result.document

    source_id = str(options.get("source_id") or Path(outdir).name)
    min_area = int(options.get("min_figure_area", 10_000))
    return write_artifacts(doc, Path(outdir), source_id, min_area)


def write_artifacts(doc: Any, out: Path, source_id: str, min_area: int) -> ParsedPaper:
    """Write ``paper.md``, ``tables/``, ``figures/`` and ``meta.json`` from a
    DoclingDocument-shaped ``doc``. Pure enough to unit-test with a fake doc:
    it only touches ``doc.tables``, ``doc.pictures``, ``doc.iterate_items()``,
    and each item's ``self_ref``/``caption_text``/``export_to_dataframe``/
    ``get_image``.
    """
    out = Path(out)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)

    table_markers: Dict[str, str] = {}
    tables: List[TableArtifact] = []
    for i, table in enumerate(doc.tables, 1):
        marker = f"table_{i:02d}"
        try:
            df = table.export_to_dataframe(doc)
        except Exception as e:  # a malformed table shouldn't kill the whole parse
            logger.warning("[docling-worker] table %d export failed: %s", i, e)
            continue
        caption = (table.caption_text(doc) or "").strip() or None
        csv_rel = f"tables/{marker}.csv"
        md_rel = f"tables/{marker}.md"
        df.to_csv(out / csv_rel, index=False)
        header = f"**{caption}**\n\n" if caption else ""
        (out / md_rel).write_text(header + df.to_markdown(index=False))
        tables.append(
            TableArtifact(
                index=i,
                page=_page_no(table),
                caption=caption,
                md_path=md_rel,
                csv_path=csv_rel,
                n_rows=int(df.shape[0]),
                n_cols=int(df.shape[1]),
            )
        )
        ref = getattr(table, "self_ref", None)
        if ref is not None:
            table_markers[ref] = marker

    figure_markers: Dict[str, str] = {}
    figures: List[FigureArtifact] = []
    saved = 0
    for pic in doc.pictures:
        try:
            img = pic.get_image(doc)
        except Exception as e:
            logger.warning("[docling-worker] figure image extraction failed: %s", e)
            img = None
        if img is None or (img.width * img.height) < min_area:
            continue
        saved += 1
        marker = f"fig_{saved:02d}"
        png_rel = f"figures/{marker}.png"
        img.save(out / png_rel)
        caption = (pic.caption_text(doc) or "").strip() or None
        figures.append(
            FigureArtifact(
                index=saved,
                page=_page_no(pic),
                caption=caption,
                png_path=png_rel,
            )
        )
        ref = getattr(pic, "self_ref", None)
        if ref is not None:
            figure_markers[ref] = marker

    markdown = build_markdown(doc, table_markers, figure_markers)
    (out / "paper.md").write_text(markdown, encoding="utf-8")

    parsed = ParsedPaper(
        source_id=source_id,
        title=(getattr(doc, "name", None) or None),
        method="docling",
        tables=tables,
        figures=figures,
        page_count=(len(doc.pages) if getattr(doc, "pages", None) else None),
        char_count=len(markdown),
    )
    parsed.write_meta(out)
    return parsed


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("usage: docling_worker <pdf> <outdir> [options.json]", file=sys.stderr)
        return 2
    pdf_path, outdir = argv[0], argv[1]
    options: Dict[str, Any] = {}
    if len(argv) >= 3 and argv[2]:
        options = json.loads(Path(argv[2]).read_text())
    try:
        parsed = parse(pdf_path, outdir, options)
    except (
        Exception
    ) as e:  # surface the failure to the parent via stderr + nonzero exit
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(parsed.model_dump_json())
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
