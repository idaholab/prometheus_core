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
"""Edge-case tests for figure analysis: empty papers, broken images and caches."""

import asyncio
import json

from PIL import Image

from research_agent.parsing import figures as figmod
from research_agent.parsing.artifacts import FigureArtifact, ParsedPaper


class FlakyCache:
    """An ArtifactCache whose figure-JSON reads and writes always fail."""

    def __init__(self):
        self.get_calls = 0
        self.put_calls = 0

    def get_figjson(self, source_id, idx):
        self.get_calls += 1
        raise ConnectionError("cache down")

    def put_figjson(self, source_id, idx, data, ttl_s):
        self.put_calls += 1
        raise ConnectionError("cache down")


def _paper(tmp_path, n=1):
    (tmp_path / "figures").mkdir(exist_ok=True)
    figs = []
    for i in range(1, n + 1):
        png = f"figures/fig_{i:02d}.png"
        Image.new("RGB", (40, 40), "white").save(tmp_path / png)
        figs.append(FigureArtifact(index=i, png_path=png))
    return ParsedPaper(source_id="p", method="docling", figures=figs)


def test_paper_without_figures_is_returned_untouched(tmp_path):
    parsed = ParsedPaper(source_id="p", method="docling")

    async def vlm(*a, **k):
        raise AssertionError("must not be called")

    assert asyncio.run(figmod.analyze_figures(parsed, tmp_path, vlm)) is parsed


def test_image_area_is_zero_for_unreadable_file(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")

    assert figmod._image_area(bad) == 0
    assert figmod._image_area(tmp_path / "missing.png") == 0


def test_non_object_vlm_reply_is_recorded_unreadable_and_cache_errors_ignored(tmp_path):
    parsed = _paper(tmp_path)
    cache = FlakyCache()
    prompts = []

    async def vlm(prompt, images, *, max_tokens, temperature=0):
        prompts.append(prompt)
        return "[1, 2, 3]"

    out = asyncio.run(figmod.analyze_figures(parsed, tmp_path, vlm, cache=cache))

    fig = out.figures[0]
    assert fig.analyzed is True
    data = json.loads((tmp_path / fig.json_path).read_text())
    assert data == {"readable": False, "error": "unparseable VLM response"}
    assert cache.get_calls == 1 and cache.put_calls == 1
    assert "caption reads" not in prompts[0]  # no caption -> no caption block
