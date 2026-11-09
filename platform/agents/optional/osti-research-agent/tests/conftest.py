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

"""Shared test setup for the osti-research-agent suite.

Makes the research_agent package (and agent.py) importable regardless of the
pytest invocation directory.
"""

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture(autouse=True)
def _no_network_synthesis(request, monkeypatch):
    """Keep the graded synthesis from calling a real model in every test that
    builds a final result; tests marked ``real_synthesis`` drive it with fake
    chat models instead."""
    if request.node.get_closest_marker("real_synthesis"):
        return
    from research_agent.core import synthesis

    async def no_synthesis(*args, **kwargs):
        return None

    monkeypatch.setattr(synthesis, "synthesize", no_synthesis)


@pytest.fixture(autouse=True)
def _no_arxiv_spacing(monkeypatch, tmp_path):
    """arXiv requests are spaced 3 s (API) and 15 s (PDFs) apart in
    production; tests run without the gap, and with gate files of their own
    so they never share one with a real agent on the same machine."""
    from research_agent import osti_client, scholarly

    monkeypatch.setenv("RATE_GATE_DIR", str(tmp_path / "gates"))
    monkeypatch.setattr(scholarly.ARXIV_API_GATE, "interval_s", 0.0)
    monkeypatch.setattr(osti_client.ARXIV_PDF_GATE, "interval_s", 0.0)
    monkeypatch.setattr(scholarly, "_RETRY_AFTER_S", 0.0)
