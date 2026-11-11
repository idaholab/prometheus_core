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

"""Write the backend's OpenAPI document to ``openapi/openapi.json``.

The document is the one the backend serves at ``/openapi.json``, built from the app
without starting it, so no Valkey, database or ``.env`` is needed. It's committed so
CI can lint it and reviewers see how a change moves the API. CI's
``platform: backend openapi`` job regenerates it and fails if that changes the
committed file; regenerate it with::

    uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DOCUMENT_PATH = BACKEND / "openapi" / "openapi.json"


def main() -> None:
    # The app package is the backend directory
    sys.path.insert(0, str(BACKEND))
    from app.main import app

    # Indented, with keys in the order FastAPI writes them
    DOCUMENT_PATH.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {DOCUMENT_PATH.relative_to(BACKEND)}")


if __name__ == "__main__":
    main()
