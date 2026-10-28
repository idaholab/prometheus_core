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

"""The parse-artifact contract every downstream consumer reads.

Paths in these models are **relative to the paper directory** (e.g.
``tables/table_01.csv``, ``paper.md``) so an artifact directory can be tarred
into Redis and untarred into a different workdir without rewriting anything.
Use :func:`ParsedPaper.abspath` to resolve one against a base directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

META_FILENAME = "meta.json"


class TableArtifact(BaseModel):
    index: int
    page: Optional[int] = None
    caption: Optional[str] = None
    md_path: str
    csv_path: str
    n_rows: int
    n_cols: int


class FigureArtifact(BaseModel):
    index: int
    page: Optional[int] = None
    caption: Optional[str] = None
    png_path: str
    json_path: Optional[str] = None  # Set only after successful VLM analysis.
    analyzed: bool = False


class ParsedPaper(BaseModel):
    source_id: str
    title: Optional[str] = None
    method: Literal["docling", "pymupdf"]
    markdown_path: str = "paper.md"
    tables: List[TableArtifact] = Field(default_factory=list)
    figures: List[FigureArtifact] = Field(default_factory=list)
    page_count: Optional[int] = None
    char_count: int = 0
    warnings: List[str] = Field(default_factory=list)

    # --- serialization to/from the paper directory's meta.json ---

    def write_meta(self, base: Path) -> Path:
        """Write ``base/meta.json`` and return its path."""
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
        path = base / META_FILENAME
        path.write_text(self.model_dump_json(indent=2))
        return path

    @classmethod
    def load(cls, base: Path) -> "ParsedPaper":
        """Load a :class:`ParsedPaper` from ``base/meta.json``."""
        path = Path(base) / META_FILENAME
        return cls.model_validate_json(path.read_text())

    # --- path helpers ---

    def abspath(self, base: Path, relpath: str) -> Path:
        return Path(base) / relpath

    def markdown_text(self, base: Path) -> str:
        """Read ``paper.md`` (empty string if it's missing)."""
        p = self.abspath(base, self.markdown_path)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def largest_tables(self, n: int) -> List[TableArtifact]:
        """Return the largest tables by cell count for answer extraction."""
        return sorted(self.tables, key=lambda t: t.n_rows * t.n_cols, reverse=True)[:n]


def paper_dir(workdir: Path, source_id: str) -> Path:
    """``workdir/papers/{source_id}/`` - the per-paper artifact directory.

    ``source_id`` is sanitized so a DOI slug or URL hash can't escape the tree.
    """
    safe = _safe_source_id(source_id)
    return Path(workdir) / "papers" / safe


def _safe_source_id(source_id: str) -> str:
    return (
        "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(source_id))
        or "unknown"
    )
