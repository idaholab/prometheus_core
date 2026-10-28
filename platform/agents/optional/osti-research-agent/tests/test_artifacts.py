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

"""Unit tests for the parse-artifact contract: metadata round-tripping,
source ID sanitization, table ordering, and relative-path helpers."""

from pathlib import Path

from research_agent.parsing.artifacts import (
    FigureArtifact,
    ParsedPaper,
    TableArtifact,
    _safe_source_id,
    paper_dir,
)


def test_meta_roundtrip(tmp_path):
    parsed = ParsedPaper(
        source_id="abc",
        title="A Title",
        method="docling",
        tables=[
            TableArtifact(
                index=1,
                page=2,
                caption="Results",
                md_path="tables/table_01.md",
                csv_path="tables/table_01.csv",
                n_rows=3,
                n_cols=4,
            )
        ],
        figures=[FigureArtifact(index=1, page=5, png_path="figures/fig_01.png")],
        page_count=9,
        char_count=1234,
        warnings=["something"],
    )
    parsed.write_meta(tmp_path)
    assert (tmp_path / "meta.json").exists()

    loaded = ParsedPaper.load(tmp_path)
    assert loaded == parsed


def test_paper_dir_is_under_workdir_papers(tmp_path):
    d = paper_dir(tmp_path, "10.1000/xyz abc/../etc")
    # source_id with slashes/spaces collapses to one safe directory name;
    # it can never escape workdir/papers.
    assert d.parent == Path(tmp_path) / "papers"
    assert "/" not in d.name


def test_safe_source_id_removes_separators():
    assert "/" not in _safe_source_id("../../etc/passwd")
    assert _safe_source_id("") == "unknown"
    # allowed characters (alnum, -, _, .) are preserved verbatim
    assert _safe_source_id("A1-b_.2") == "A1-b_.2"


def test_largest_tables_orders_by_cell_count():
    t1 = TableArtifact(
        index=1, md_path="a.md", csv_path="a.csv", n_rows=2, n_cols=2
    )  # 4
    t2 = TableArtifact(
        index=2, md_path="b.md", csv_path="b.csv", n_rows=10, n_cols=5
    )  # 50
    t3 = TableArtifact(
        index=3, md_path="c.md", csv_path="c.csv", n_rows=3, n_cols=3
    )  # 9
    parsed = ParsedPaper(source_id="x", method="docling", tables=[t1, t2, t3])

    top = parsed.largest_tables(2)
    assert [t.index for t in top] == [2, 3]
    # asking for more than exist just returns all, still ordered
    assert [t.index for t in parsed.largest_tables(10)] == [2, 3, 1]


def test_markdown_text_reads_paper_md(tmp_path):
    (tmp_path / "paper.md").write_text("hello body", encoding="utf-8")
    parsed = ParsedPaper(source_id="x", method="docling")
    assert parsed.markdown_text(tmp_path) == "hello body"


def test_markdown_text_missing_file_returns_empty(tmp_path):
    parsed = ParsedPaper(source_id="y", method="docling", markdown_path="absent.md")
    assert parsed.markdown_text(tmp_path) == ""
