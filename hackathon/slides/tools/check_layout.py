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

"""Layout checker for the hackathon decks.

For every slide in every deck it reports
  * content that runs past the slide's safe area (into the footer or off the edge),
  * boxes whose content is clipped (scrollWidth/scrollHeight > client size),
  * text runs from different elements whose rendered glyph boxes overlap,
and optionally writes a PNG screenshot per slide.

Run:  uv run --with playwright python tools/check_layout.py [--shots DIR] [deck.html ...]
Uses the locally installed Google Chrome (channel="chrome").
"""

import argparse
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent

JS = r"""
(i) => {
  const stage = document.getElementById('stage');
  stage.style.transform = 'none';
  window.__deck.go(i);
  const slide = document.querySelectorAll('#stage .slide')[i];
  const S = stage.getBoundingClientRect();
  const issues = [];
  const cz = slide.querySelector(':scope > .content');
  if (cz && parseFloat(cz.style.zoom || '1') < 0.9) issues.push(`AUTOFIT-SHRUNK zoom=${cz.style.zoom}`);
  const label = (el) => {
    const t = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    return `<${el.tagName.toLowerCase()}${el.className ? '.' + String(el.className).split(' ').join('.') : ''}> "${t}"`;
  };
  const skip = (el) => el.closest('.foot, aside.notes');
  const bottomLimit = slide.dataset.nofoot !== undefined || slide.classList.contains('title') ? 890 : 842;
  for (const el of slide.querySelectorAll('*')) {
    if (skip(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(el);
    if (cs.position === 'absolute' && el.closest('.logos')) continue;
    if (r.bottom - S.top > bottomLimit + 0.5 || r.right - S.left > 1592 || r.left - S.left < 0) {
      issues.push(`OUT-OF-SAFE-AREA ${label(el)} bottom=${Math.round(r.bottom - S.top)} right=${Math.round(r.right - S.left)}`);
    }
    if (el.matches('.col, .card, .box, .grid > *') && el.scrollWidth > el.clientWidth + 1) {
      issues.push(`CONTENT-WIDER-THAN-BOX ${label(el)} scroll=${el.scrollWidth} client=${el.clientWidth}`);
    }
    const clip = ['hidden', 'clip', 'auto', 'scroll'];
    if (clip.includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 1) {
      issues.push(`CLIPPED-X ${label(el)} scroll=${el.scrollWidth} client=${el.clientWidth}`);
    }
    if (clip.includes(cs.overflowY) && el.scrollHeight > el.clientHeight + 1 && !el.classList.contains('slide')) {
      issues.push(`CLIPPED-Y ${label(el)} scroll=${el.scrollHeight} client=${el.clientHeight}`);
    }
  }
  // text-run overlap between different parent elements
  const runs = [];
  const walker = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    if (!n.textContent.trim()) continue;
    const p = n.parentElement;
    if (skip(p)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.width < 1 || r.height < 1) continue;
      runs.push({ p, r, t: n.textContent.trim().slice(0, 30) });
    }
  }
  const seen = new Set();
  for (let a = 0; a < runs.length; a++) {
    for (let b = a + 1; b < runs.length; b++) {
      const A = runs[a], B = runs[b];
      if (A.p === B.p) continue;
      const w = Math.min(A.r.right, B.r.right) - Math.max(A.r.left, B.r.left);
      const h = Math.min(A.r.bottom, B.r.bottom) - Math.max(A.r.top, B.r.top);
      // inline siblings on one line touch by < 1px; require a real overlap
      if (w > 2 && h > 3) {
        const key = A.t + '|' + B.t;
        if (seen.has(key)) continue;
        seen.add(key);
        issues.push(`TEXT-OVERLAP "${A.t}" x "${B.t}" (${Math.round(w)}x${Math.round(h)})`);
      }
    }
  }
  // text that runs into a box/card it does not belong to (e.g. arrow labels)
  const boxes = Array.from(slide.querySelectorAll('.box, .card, pre, img')).filter((b) => !skip(b));
  const seenBox = new Set();
  for (const A of runs) {
    for (const b of boxes) {
      if (b.contains(A.p)) continue;
      const r = b.getBoundingClientRect();
      const w = Math.min(A.r.right, r.right) - Math.max(A.r.left, r.left);
      const h = Math.min(A.r.bottom, r.bottom) - Math.max(A.r.top, r.top);
      if (w > 2 && h > 3) {
        const key = A.t + '|' + (b.textContent || b.tagName).slice(0, 20);
        if (seenBox.has(key)) continue;
        seenBox.add(key);
        issues.push(`TEXT-INTO-BOX "${A.t}" over ${label(b)}`);
      }
    }
  }
  return issues;
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("decks", nargs="*")
    ap.add_argument("--shots", help="directory for per-slide PNG screenshots")
    args = ap.parse_args()
    decks = [pathlib.Path(d) for d in args.decks] or [
        deck
        for folder in (ROOT, ROOT / "one-day")
        for deck in sorted(folder.glob("[0-9]*.html")) + [folder / "index.html"]
    ]
    shots = pathlib.Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        for deck in decks:
            if not deck.exists():
                continue
            page.goto(deck.resolve().as_uri())
            page.wait_for_load_state("load")
            page.add_style_tag(content=".slide{transition:none !important}")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(400)
            count = page.evaluate("window.__deck ? window.__deck.count : 0")
            for i in range(count):
                issues = page.evaluate(JS, i)
                if shots:
                    page.screenshot(path=str(shots / f"{deck.stem}-{i + 1:02d}.png"))
                for msg in issues:
                    print(f"{deck.name} #{i + 1}: {msg}")
                total += len(issues)
            print(f"{deck.name}: {count} slides checked")
        browser.close()
    print(f"TOTAL ISSUES: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
