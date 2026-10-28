#!/usr/bin/env python3
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

"""Fetch the golden-corpus PDFs used by tests/test_goldens.py.

The golden corpus is a small, curated set of open-access OSTI papers chosen to
exercise the parse ladder: a text-heavy paper, a table-heavy paper, a
figure-heavy paper, and a scanned (OCR) paper. We download by OSTI id through
the same client the agent uses, so this stays in sync with real behavior.

Usage:
    uv run python scripts/download_goldens.py

``GOLDEN_OSTI_IDS`` is empty by default. Populate it with IDs whose PDFs are
reliably downloadable and licensed for redistribution. Recording expected
table and figure counts also allows ``test_goldens.py`` to validate document
structure instead of only checking for non-empty output.
"""

from __future__ import annotations

import sys
from pathlib import Path

# (osti_id, human-readable label describing what the PDF stresses).
# Populate only with documents suitable for the committed golden corpus.
GOLDEN_OSTI_IDS: list[tuple[str, str]] = [
    # ("1234567", "text-heavy review article"),
    # ("2345678", "table-heavy experimental results"),
    # ("3456789", "figure-heavy plots"),
    # ("4567890", "scanned / image-only (OCR path)"),
]

GOLDENS_DIR = Path(__file__).resolve().parents[1] / "tests" / "goldens"


def main() -> int:
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)

    if not GOLDEN_OSTI_IDS:
        print(
            "No golden OSTI ids configured yet.\n"
            f"Add (osti_id, label) tuples to GOLDEN_OSTI_IDS in {__file__},\n"
            "then re-run. tests/test_goldens.py will pick up any *.pdf in\n"
            f"{GOLDENS_DIR} and skip while it's empty.",
            file=sys.stderr,
        )
        return 0

    # Import lazily so the no-op path above doesn't require the package env.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_agent import osti_client

    fetched = 0
    for osti_id, label in GOLDEN_OSTI_IDS:
        dest = GOLDENS_DIR / f"{osti_id}.pdf"
        if dest.exists():
            print(f"  have {osti_id}.pdf ({label})")
            fetched += 1
            continue
        print(f"  downloading {osti_id} ({label})...")
        path = osti_client.download_paper(osti_id, None)
        if not path:
            print(f"    !! could not download OSTI #{osti_id}", file=sys.stderr)
            continue
        dest.write_bytes(Path(path).read_bytes())
        fetched += 1

    print(f"{fetched}/{len(GOLDEN_OSTI_IDS)} golden PDFs available in {GOLDENS_DIR}")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
