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

"""Deep-agent tools. Import from here to get the full tool set bound
to a single run's :class:`RunContext`::

    from research_agent.tools import RunContext, build_tools
    tools = build_tools(ctx)

langchain/langgraph are only imported when this package is used, so the
pipeline engine and CLI never pull them in.
"""

from __future__ import annotations

from typing import List

from research_agent.tools.context import RunContext

__all__ = ["RunContext", "build_tools"]


def build_tools(ctx: RunContext) -> List:
    """All orchestrator-facing tools: OSTI search/download/parse, web + scholarly
    search, and the knowledge base."""
    from research_agent.tools.evidence import build_evidence_tools
    from research_agent.tools.memory import build_memory_tools
    from research_agent.tools.osti import build_osti_tools
    from research_agent.tools.search import build_search_tools

    return (
        build_osti_tools(ctx)
        + build_search_tools(ctx)
        + build_memory_tools(ctx)
        + build_evidence_tools(ctx)
    )
