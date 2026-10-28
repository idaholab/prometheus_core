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

"""Verify that only the A2A executor imports prometheus_api or a2a.

Plain text search rather than actually importing every module, so this test
runs without prometheus_api/a2a-sdk installed and catches the violation even
if the import is behind a try/except or inside a function body.
"""

import re
from pathlib import Path

RESEARCH_AGENT_DIR = Path(__file__).resolve().parents[1] / "research_agent"
FORBIDDEN = re.compile(r"^\s*(?:from|import)\s+(prometheus_api|a2a)\b")


def test_research_agent_core_does_not_import_prometheus_api_or_a2a():
    violations = []
    for path in sorted(RESEARCH_AGENT_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.match(line):
                violations.append(
                    f"{path.relative_to(RESEARCH_AGENT_DIR.parent)}:{lineno}: {line.strip()}"
                )

    assert (
        not violations
    ), "research_agent/ must not import prometheus_api or a2a:\n" + "\n".join(
        violations
    )
