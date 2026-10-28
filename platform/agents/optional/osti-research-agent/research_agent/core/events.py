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

"""Event and result models streamed by ResearchRunner.

`provenance` and `suggested_queries` stay as list[dict] (not list[Source] /
list[str]) so FinalResult's emitted JSON is field-for-field identical to what
the A2A adapter emits.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ProgressEvent(BaseModel):
    kind: Literal["status", "todo_update", "tool_call", "tool_result"] = "status"
    message: str
    detail: Optional[Dict[str, Any]] = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Source(BaseModel):
    id: str
    title: str
    url: str
    origin: Literal["osti", "web", "openalex", "arxiv"] = "osti"


class Finding(BaseModel):
    """Structured result produced by the verified paper-analysis tool.

    The legacy pipeline leaves ``findings`` empty and reports its sources
    through ``FinalResult.provenance``.
    """

    source_id: str
    answer: str
    evidence: str = ""
    excerpt: Optional[str] = None
    artifacts: List[str] = Field(default_factory=list)
    # "exact": the paper reports what was asked, at the asked conditions.
    # "nearest": the closest the paper reports (other temperature, stress,
    # material grade, ...); the answer and evidence state the difference.
    match: Literal["exact", "nearest"] = "exact"


class FinalResult(BaseModel):
    status: Literal["completed", "no_results", "error", "timeout_partial"]
    question: str
    answer: str = ""
    provenance: List[Dict[str, Any]] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    search_query: Optional[str] = None
    papers_assessed: int = 0
    relevant_papers: int = 0
    papers_analyzed: int = 0
    facts_stored: int = 0
    suggested_queries: List[Dict[str, str]] = Field(default_factory=list)
    progress_log: List[str] = Field(default_factory=list)
    cached: bool = False
    source: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Every search hit of the run (source_id -> hit), for the A2A layer to show
    # as artifacts. Excluded from the emitted JSON so the wire shape is unchanged.
    searched_papers: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, exclude=True
    )


AgentEvent = Union[ProgressEvent, FinalResult]
