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

"""Figure analysis: one multimodal LLM call per figure PNG -> strict JSON.

Runs in the parent process (it's just API calls) after the docling worker
returns. Gated by ``config.analyze_figures``; the old pipeline doesn't consume
the JSON, while the deep-agent paper analyzer can inspect it through the paper
artifact directory. Failures are written as ``{"readable": false, ...}``
rather than aborting the parse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

from research_agent.core.llm import VlmCompleteFn
from research_agent.llm_steps import extract_json_from_text
from research_agent.memory import ArtifactCache
from research_agent.parsing.artifacts import ParsedPaper

logger = logging.getLogger(__name__)

# Stop launching new VLM calls when fewer than this many seconds of budget
# remain, so figure analysis can never eat the synthesis step's time.
_DEADLINE_GUARD_S = 60
_CACHE_TTL_S = 30 * 24 * 3600

FIGURE_PROMPT = """You are analyzing a single figure extracted from a scientific paper.

{caption_block}Return ONLY a JSON object (no prose, no code fences) with this exact shape:
{{
  "figure_type": "line_plot | scatter | bar | schematic | photo | micrograph | other",
  "caption_or_inferred_title": "...",
  "axes": {{"x": {{"label": "...", "unit": "...", "range": [null, null]}}, "y": {{"label": "...", "unit": "...", "range": [null, null]}}}},
  "series": [{{"name": "...", "notable_points": [{{"x": null, "y": null, "note": "..."}}]}}],
  "key_findings": ["one-sentence quantitative takeaways"],
  "readable": true
}}
If the image is not a readable data figure, return {{"readable": false, "error": "reason"}}."""


def _image_area(path: Path) -> int:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.width) * int(im.height)
    except Exception:
        return 0


async def analyze_figures(
    parsed: ParsedPaper,
    base_dir: Path,
    vlm_complete: VlmCompleteFn,
    *,
    max_figures: int = 12,
    deadline: Optional[float] = None,
    cache: Optional[ArtifactCache] = None,
    concurrency: int = 4,
) -> ParsedPaper:
    """Analyze up to ``max_figures`` figures (largest by pixel area first),
    writing ``figures/fig_NN.json`` and flipping ``analyzed``/``json_path`` on
    each :class:`FigureArtifact`. ``deadline`` is a ``time.monotonic()``
    timestamp; calls stop once it's within :data:`_DEADLINE_GUARD_S`.
    """
    base_dir = Path(base_dir)
    if not parsed.figures:
        return parsed

    ranked = sorted(
        parsed.figures,
        key=lambda f: _image_area(base_dir / f.png_path),
        reverse=True,
    )[:max_figures]

    sem = asyncio.Semaphore(concurrency)

    async def _one(fig) -> None:
        json_rel = f"figures/fig_{fig.index:02d}.json"
        json_abs = base_dir / json_rel

        # Warm cache hit: reuse a prior run's analysis for this paper+figure.
        if cache is not None:
            try:
                hit = cache.get_figjson(parsed.source_id, fig.index)
            except Exception:
                hit = None
            if hit:
                json_abs.write_text(hit)
                fig.json_path, fig.analyzed = json_rel, True
                return

        async with sem:
            if deadline is not None and time.monotonic() > (
                deadline - _DEADLINE_GUARD_S
            ):
                logger.info(
                    "[figures] deadline approaching; skipping figure %d", fig.index
                )
                return
            caption_block = (
                f'The figure caption reads: "{fig.caption}"\n\n' if fig.caption else ""
            )
            prompt = FIGURE_PROMPT.format(caption_block=caption_block)
            try:
                png = (base_dir / fig.png_path).read_bytes()
                raw = await vlm_complete(prompt, [png], max_tokens=800)
                data = extract_json_from_text(raw)
                if not isinstance(data, dict):
                    data = {"readable": False, "error": "unparseable VLM response"}
            except Exception as e:  # a bad figure must not abort the batch
                logger.warning("[figures] figure %d analysis failed: %s", fig.index, e)
                data = {"readable": False, "error": str(e)}

        payload = json.dumps(data, indent=2)
        json_abs.write_text(payload)
        fig.json_path, fig.analyzed = json_rel, True
        if cache is not None:
            try:
                cache.put_figjson(
                    parsed.source_id, fig.index, payload, ttl_s=_CACHE_TTL_S
                )
            except Exception:
                pass

    await asyncio.gather(*(_one(f) for f in ranked))
    return parsed
