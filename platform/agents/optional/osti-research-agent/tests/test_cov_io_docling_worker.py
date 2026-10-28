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
"""Tests for the docling worker's parse/main entry points with fake docling."""

import json
import sys
import types

import pandas as pd
from PIL import Image

from research_agent.parsing import docling_worker as dw
from research_agent.parsing.artifacts import ParsedPaper


class _Prov:
    def __init__(self, page_no):
        self.page_no = page_no


class _Item:
    def __init__(self, *, self_ref=None, label=None, text="", caption="", prov=None,
                 df=None, image=None, image_error=False, level=1):
        self.self_ref = self_ref
        self.label = label
        self.text = text
        self._caption = caption
        self.prov = prov if prov is not None else [_Prov(1)]
        self._df = df
        self._image = image
        self._image_error = image_error
        self.level = level

    def caption_text(self, doc):
        return self._caption

    def export_to_dataframe(self, doc):
        return self._df

    def get_image(self, doc):
        if self._image_error:
            raise RuntimeError("no image bytes")
        return self._image


class _Doc:
    def __init__(self, items=(), tables=(), pictures=(), name="Doc", pages=None):
        self._items = list(items)
        self.tables = list(tables)
        self.pictures = list(pictures)
        self.name = name
        self.pages = pages

    def iterate_items(self):
        for it in self._items:
            yield it, 0


# --- _page_no / build_markdown --------------------------------------------------


def test_page_no_is_none_when_provenance_is_unreadable():
    assert dw._page_no(_Item(prov=[_Prov("not-a-number")])) is None
    assert dw._page_no(_Item(prov=[])) is None
    assert dw._page_no(_Item(prov=[_Prov("7")])) == 7


def test_build_markdown_skips_empty_text_and_renders_list_items():
    doc = _Doc(items=[
        _Item(label="text", text="   "),
        _Item(label="list_item", text="first point"),
        _Item(label="picture", text="ignored structural node"),
    ])

    md = dw.build_markdown(doc, {}, {})

    assert md == "- first point\n"


# --- write_artifacts ------------------------------------------------------------


def test_figure_whose_image_extraction_fails_is_skipped(tmp_path):
    bad = _Item(self_ref="#/pictures/0", image_error=True)
    good = _Item(self_ref="#/pictures/1", caption="Plot",
                 image=Image.new("RGB", (120, 120), "white"))
    doc = _Doc(items=[good], pictures=[bad, good], pages={1: object(), 2: object()})

    parsed = dw.write_artifacts(doc, tmp_path, "s1", min_area=100)

    assert [f.caption for f in parsed.figures] == ["Plot"]
    assert parsed.figures[0].png_path == "figures/fig_01.png"
    assert parsed.page_count == 2
    assert "[FIGURE fig_01] Plot" in (tmp_path / "paper.md").read_text()


# --- parse (fake docling modules) -----------------------------------------------


def _install_fake_docling(monkeypatch, doc, seen):
    class InputFormat:
        PDF = "pdf"

    class PdfFormatOption:
        def __init__(self, pipeline_options):
            self.pipeline_options = pipeline_options

    class DocumentConverter:
        def __init__(self, format_options):
            seen["format_options"] = format_options

        def convert(self, path):
            seen["converted"] = path
            return types.SimpleNamespace(document=doc)

    base_models = types.ModuleType("docling.datamodel.base_models")
    base_models.InputFormat = InputFormat
    converter = types.ModuleType("docling.document_converter")
    converter.DocumentConverter = DocumentConverter
    converter.PdfFormatOption = PdfFormatOption
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter)
    monkeypatch.setattr(dw, "_pipeline_options", lambda opts: ("opts", dict(opts)))


def test_parse_converts_pdf_and_writes_artifacts(tmp_path, monkeypatch):
    table = _Item(self_ref="#/tables/0", df=pd.DataFrame({"a": [1]}), caption="T1")
    doc = _Doc(items=[_Item(label="title", text="Paper"), table], tables=[table])
    seen = {}
    _install_fake_docling(monkeypatch, doc, seen)
    outdir = tmp_path / "paper-dir"

    parsed = dw.parse("in.pdf", str(outdir), {"source_id": "88", "min_figure_area": 5})

    assert seen["converted"] == "in.pdf"
    fmt = seen["format_options"]["pdf"]
    assert fmt.pipeline_options == ("opts", {"source_id": "88", "min_figure_area": 5})
    assert parsed.source_id == "88"
    assert len(parsed.tables) == 1
    assert ParsedPaper.load(outdir) == parsed


def test_parse_defaults_source_id_to_outdir_name(tmp_path, monkeypatch):
    _install_fake_docling(monkeypatch, _Doc(items=[_Item(label="text", text="x")]), {})

    parsed = dw.parse("in.pdf", str(tmp_path / "osti-5"), {})

    assert parsed.source_id == "osti-5"


# --- main -------------------------------------------------------------------------


def test_main_without_enough_args_prints_usage(capsys):
    assert dw.main(["only-pdf"]) == 2
    assert "usage" in capsys.readouterr().err


def test_main_reads_options_and_prints_parsed_json(tmp_path, monkeypatch, capsys):
    opts = tmp_path / "opts.json"
    opts.write_text(json.dumps({"source_id": "7"}))
    seen = {}

    def fake_parse(pdf, outdir, options):
        seen.update(pdf=pdf, outdir=outdir, options=options)
        return ParsedPaper(source_id=options["source_id"], method="docling")

    monkeypatch.setattr(dw, "parse", fake_parse)

    assert dw.main(["a.pdf", str(tmp_path / "o"), str(opts)]) == 0
    assert seen == {"pdf": "a.pdf", "outdir": str(tmp_path / "o"),
                    "options": {"source_id": "7"}}
    printed = ParsedPaper.model_validate_json(capsys.readouterr().out)
    assert printed.source_id == "7"


def test_main_reports_parse_failure_on_stderr(monkeypatch, capsys):
    def failing_parse(pdf, outdir, options):
        assert options == {}
        raise RuntimeError("docling exploded")

    monkeypatch.setattr(dw, "parse", failing_parse)

    assert dw.main(["a.pdf", "out", ""]) == 1
    assert "ERROR: docling exploded" in capsys.readouterr().err
