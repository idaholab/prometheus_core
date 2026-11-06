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

"""Export decks to pdf/<deck>.pdf (one 1600x900 page per slide).

Run:  uv run --with playwright python tools/export_pdf.py [deck.html ...]
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent

decks = sys.argv[1:] or sorted(
    str(p.relative_to(ROOT)) for folder in (ROOT, ROOT / "one-day") for p in folder.glob("[0-9]*.html")
)
(ROOT / "pdf").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    for name in decks:
        page.goto((ROOT / name).as_uri())
        page.wait_for_load_state("load")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(500)
        # Keep the folder, so one-day/01-welcome.html does not overwrite 01-welcome.pdf.
        out = ROOT / "pdf" / pathlib.Path(name).with_suffix(".pdf")
        out.parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=str(out), width="1600px", height="900px", print_background=True,
                 prefer_css_page_size=True)
        print(out)
    browser.close()
