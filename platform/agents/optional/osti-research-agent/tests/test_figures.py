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

"""Tests for multimodal figure analysis.

The multimodal model is injected as a fake ``vlm_complete``, so no live model
is touched (the VLM *client* itself is covered by test_vlm_client.py against a
respx mock). Covers: JSON written + flags flipped; deadline short-circuit;
warm-cache reuse; and per-figure failure isolation.
"""

import asyncio
import json
import time
from pathlib import Path

from PIL import Image

from research_agent.parsing import figures as figmod
from research_agent.parsing.artifacts import FigureArtifact, ParsedPaper


def _make_paper_with_figs(base: Path, n: int = 2) -> ParsedPaper:
    (base / "figures").mkdir(parents=True, exist_ok=True)
    figs = []
    for i in range(1, n + 1):
        png = f"figures/fig_{i:02d}.png"
        # Distinct sizes so the area-ranking has something to sort on.
        Image.new("RGB", (100 + i, 100 + i), "white").save(base / png)
        figs.append(FigureArtifact(index=i, png_path=png, caption=f"Fig {i}"))
    return ParsedPaper(source_id="p1", method="docling", figures=figs)


def test_analyze_figures_writes_json_and_flips_flags(tmp_path):
    parsed = _make_paper_with_figs(tmp_path, 2)
    calls = []

    async def fake_vlm(prompt, images, *, max_tokens, temperature=0):
        calls.append(len(images))
        return '{"readable": true, "figure_type": "line_plot", "key_findings": ["k"]}'

    out = asyncio.run(
        figmod.analyze_figures(parsed, tmp_path, fake_vlm, max_figures=12)
    )

    assert len(calls) == 2
    assert all(n == 1 for n in calls)  # one image per call
    for fig in out.figures:
        assert fig.analyzed is True
        assert fig.json_path
        assert (tmp_path / fig.json_path).exists()


def test_analyze_figures_respects_max_figures(tmp_path):
    parsed = _make_paper_with_figs(tmp_path, 3)
    calls = []

    async def fake_vlm(prompt, images, *, max_tokens, temperature=0):
        calls.append(1)
        return "{}"

    asyncio.run(figmod.analyze_figures(parsed, tmp_path, fake_vlm, max_figures=1))

    assert len(calls) == 1  # only the largest figure is analyzed


def test_analyze_figures_deadline_short_circuits(tmp_path):
    parsed = _make_paper_with_figs(tmp_path, 2)
    calls = []

    async def fake_vlm(prompt, images, *, max_tokens, temperature=0):
        calls.append(1)
        return "{}"

    # A deadline inside the guard window means no new VLM call should start.
    deadline = time.monotonic() + 1
    out = asyncio.run(
        figmod.analyze_figures(parsed, tmp_path, fake_vlm, deadline=deadline)
    )

    assert calls == []
    assert all(not f.analyzed for f in out.figures)


def test_analyze_figures_uses_cache(tmp_path):
    parsed = _make_paper_with_figs(tmp_path, 1)
    calls = []

    async def fake_vlm(prompt, images, *, max_tokens, temperature=0):
        calls.append(1)
        return "{}"

    class Cache:
        def get_figjson(self, source_id, idx):
            return '{"readable": true, "cached": true}'

        def put_figjson(self, *a, **k):
            pass

    out = asyncio.run(figmod.analyze_figures(parsed, tmp_path, fake_vlm, cache=Cache()))

    assert calls == []  # served from the warm cache, no model call
    fig = out.figures[0]
    assert fig.analyzed
    assert "cached" in (tmp_path / fig.json_path).read_text()


def test_analyze_figures_failure_writes_readable_false(tmp_path):
    parsed = _make_paper_with_figs(tmp_path, 1)

    async def boom_vlm(prompt, images, *, max_tokens, temperature=0):
        raise RuntimeError("vlm down")

    out = asyncio.run(figmod.analyze_figures(parsed, tmp_path, boom_vlm))

    fig = out.figures[0]
    assert fig.analyzed  # we still recorded a (negative) result
    data = json.loads((tmp_path / fig.json_path).read_text())
    assert data["readable"] is False
    assert "vlm down" in data["error"]
