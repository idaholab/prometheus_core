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

"""Unit tests for the Docling worker's pure helpers.

``build_markdown`` and ``write_artifacts`` are the parts that shape the
artifact directory; both are written to run against a DoclingDocument-*shaped*
fake, so these exercise placeholder insertion, the figure area-threshold
filter, and malformed-table resilience with no docling/torch import.
"""

import pandas as pd
from PIL import Image

from research_agent.parsing import docling_worker as dw
from research_agent.parsing.artifacts import ParsedPaper


def test_pipeline_options_disable_torch_compile():
    options = dw._pipeline_options({"do_ocr": False, "images_scale": 2.0})

    assert options.layout_options.engine_options.compile_model is False


def test_pipeline_options_apply_the_memory_settings():
    from docling.datamodel.pipeline_options import TableFormerMode

    low = dw._pipeline_options({"images_scale": 1.0, "table_mode": "fast"})
    default = dw._pipeline_options({})

    assert low.images_scale == 1.0
    assert low.table_structure_options.mode == TableFormerMode.FAST
    assert default.images_scale == 2.0
    assert default.table_structure_options.mode == TableFormerMode.ACCURATE


class FakeProv:
    def __init__(self, page_no):
        self.page_no = page_no


class FakeItem:
    """A DoclingDocument item stand-in: only the attributes/methods that
    build_markdown and write_artifacts actually touch."""

    def __init__(
        self,
        *,
        self_ref=None,
        label=None,
        text="",
        caption="",
        level=1,
        page=1,
        df=None,
        image=None,
        df_error=False,
    ):
        self.self_ref = self_ref
        self.label = label
        self.text = text
        self._caption = caption
        self.level = level
        self.prov = [FakeProv(page)] if page else []
        self._df = df
        self._image = image
        self._df_error = df_error

    def caption_text(self, doc):
        return self._caption

    def export_to_dataframe(self, doc):
        if self._df_error:
            raise ValueError("malformed table")
        return self._df

    def get_image(self, doc):
        return self._image


class FakeDoc:
    def __init__(self, items, tables, pictures, name="Test Paper", pages=None):
        self._items = items
        self.tables = tables
        self.pictures = pictures
        self.name = name
        self.pages = pages if pages is not None else {1: object()}

    def iterate_items(self):
        for it in self._items:
            yield it, 0


def test_build_markdown_inserts_table_and_figure_placeholders():
    title = FakeItem(self_ref="#/texts/0", label="title", text="A Study")
    section = FakeItem(
        self_ref="#/texts/1", label="section_header", text="Methods", level=1
    )
    para = FakeItem(self_ref="#/texts/2", label="text", text="Intro paragraph.")
    tbl = FakeItem(self_ref="#/tables/0", label="table", caption="Table 1. Data")
    fig = FakeItem(self_ref="#/pictures/0", label="picture", caption="Fig 1. Plot")
    doc = FakeDoc([title, section, para, tbl, fig], [tbl], [fig])

    md = dw.build_markdown(doc, {"#/tables/0": "table_01"}, {"#/pictures/0": "fig_01"})

    assert "# A Study" in md
    assert "## Methods" in md
    assert "Intro paragraph." in md
    assert "[TABLE table_01] Table 1. Data" in md
    assert "[FIGURE fig_01] Fig 1. Plot" in md


def test_write_artifacts_filters_small_figures_and_survives_bad_table(tmp_path):
    good_tbl = FakeItem(
        self_ref="#/tables/0",
        label="table",
        caption="Results",
        df=pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
    )
    bad_tbl = FakeItem(self_ref="#/tables/1", label="table", df_error=True)
    big_pic = FakeItem(
        self_ref="#/pictures/0",
        label="picture",
        caption="Big fig",
        image=Image.new("RGB", (200, 200), "white"),  # area 40000 > threshold
    )
    small_pic = FakeItem(
        self_ref="#/pictures/1",
        label="picture",
        image=Image.new("RGB", (50, 50), "white"),  # area 2500 < threshold
    )
    body = FakeItem(self_ref="#/texts/0", label="text", text="Body text.")
    doc = FakeDoc(
        [body, good_tbl, big_pic],
        tables=[good_tbl, bad_tbl],
        pictures=[big_pic, small_pic],
    )

    parsed = dw.write_artifacts(doc, tmp_path, "999", min_area=10_000)

    assert isinstance(parsed, ParsedPaper)
    assert parsed.method == "docling"
    assert parsed.title == "Test Paper"

    # The malformed table is skipped without aborting; the good one is written.
    assert len(parsed.tables) == 1
    tbl_art = parsed.tables[0]
    assert (tbl_art.n_rows, tbl_art.n_cols) == (2, 2)
    assert (tmp_path / tbl_art.csv_path).exists()
    assert (tmp_path / tbl_art.md_path).exists()

    # Only the above-threshold figure is kept and saved.
    assert len(parsed.figures) == 1
    assert (tmp_path / parsed.figures[0].png_path).exists()

    # paper.md carries the locator placeholders and the running text.
    md = (tmp_path / "paper.md").read_text()
    assert "[TABLE table_01]" in md
    assert "[FIGURE fig_01]" in md
    assert "Body text." in md

    # And the whole thing round-trips through meta.json.
    reloaded = ParsedPaper.load(tmp_path)
    assert reloaded.source_id == "999"
    assert reloaded == parsed


def test_write_artifacts_handles_no_tables_or_figures(tmp_path):
    only_text = FakeItem(self_ref="#/texts/0", label="text", text="Just prose.")
    doc = FakeDoc([only_text], tables=[], pictures=[])

    parsed = dw.write_artifacts(doc, tmp_path, "abc", min_area=10_000)

    assert parsed.tables == []
    assert parsed.figures == []
    assert "Just prose." in (tmp_path / "paper.md").read_text()
