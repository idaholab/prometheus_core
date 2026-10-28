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

"""Golden-corpus parsing tests.

These run the *real* docling ladder against a small set of representative OSTI
PDFs and assert structural invariants (a non-empty paper.md; the ladder lands
on a known method). They are slow and need docling's model weights, so:

  * they are marked ``@pytest.mark.slow`` (excluded from the default suite -
    run them in a nightly job: ``pytest -m slow``), and
  * they skip cleanly unless the corpus has been fetched:

        uv run python scripts/download_goldens.py

Corpus curation (which PDFs, expected table/figure counts) is a documented
follow-up; see scripts/download_goldens.py and plans/deep-agent-implementation.md 2.6.
"""

import asyncio
from pathlib import Path

import pytest

from research_agent.core.config import AgentConfig
from research_agent.parsing import pipeline as pp
from research_agent.parsing.artifacts import paper_dir

GOLDENS_DIR = Path(__file__).parent / "goldens"
PDFS = sorted(GOLDENS_DIR.glob("*.pdf")) if GOLDENS_DIR.exists() else []

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not PDFS, reason="no golden PDFs; run scripts/download_goldens.py")
@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_golden_pdf_parses(pdf, tmp_path):
    config = AgentConfig(litellm_base_url="http://unused", workdir=tmp_path)

    parsed = asyncio.run(
        pp.parse_paper_pipeline(str(pdf), pdf.stem, config, caches=None)
    )

    assert parsed.method in ("docling", "pymupdf")
    base = paper_dir(tmp_path, pdf.stem)
    assert parsed.markdown_text(base).strip(), "paper.md should not be empty"
