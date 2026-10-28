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
def _no_arxiv_spacing(monkeypatch):
    """The arXiv request gap is 3 s in production; tests run without it."""
    from research_agent import scholarly

    monkeypatch.setattr(scholarly, "ARXIV_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(scholarly, "_ARXIV_RETRY_AFTER_S", 0.0)
    monkeypatch.setattr(scholarly, "_arxiv_lock", None)
    monkeypatch.setattr(scholarly, "_arxiv_last_request", 0.0)
