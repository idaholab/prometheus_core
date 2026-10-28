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

"""Emit human-readable progress from inside a tool onto LangGraph's ``custom``
stream, which ``core/deep_runner`` translates into ``ProgressEvent``s.

``get_stream_writer()`` only works inside a running graph; outside one (unit
tests, or if the API changes) this degrades to a no-op instead of raising, so
the tools stay drivable in isolation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def emit(message: str, detail: Optional[Dict[str, Any]] = None) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        writer = None
    if writer is None:
        logger.debug("[tool-progress] %s", message)
        return
    payload: Dict[str, Any] = {"message": message}
    if detail:
        payload["detail"] = detail
    try:
        writer(payload)
    except Exception:  # never let progress reporting break a tool
        logger.debug("[tool-progress] writer failed for: %s", message)
