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

"""Structured PDF parsing.

Turns a downloaded PDF into a per-paper artifact directory -
``papers/{source_id}/`` containing ``paper.md``, ``tables/table_NN.{csv,md}``,
``figures/fig_NN.png`` (+ optional ``fig_NN.json``), and a ``meta.json``
describing them (:class:`~research_agent.parsing.artifacts.ParsedPaper`).

Nothing here imports prometheus_api or a2a; the heavy docling/torch work runs
in a subprocess (:mod:`research_agent.parsing.docling_worker`).
"""

from research_agent.parsing.artifacts import (
    FigureArtifact,
    ParsedPaper,
    TableArtifact,
    paper_dir,
)

__all__ = ["FigureArtifact", "ParsedPaper", "TableArtifact", "paper_dir"]
