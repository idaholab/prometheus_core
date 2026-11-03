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

"""Timeseries models for the storage client."""

from typing import Any, List
from pydantic import BaseModel, Field


class TimeseriesResult(BaseModel):
    """The rows a timeseries (tabular file) query returns.

    ``data`` holds one list per row, in the order of ``columns``. Cells are returned as the
    server sent them: a missing value can arrive as an empty object (``{}``) and one column can
    mix numbers and empty objects, so cells are not coerced to a type.
    """

    columns: List[str] = Field(default_factory=list, description="Column names, in row order")
    data: List[List[Any]] = Field(default_factory=list, description="Rows, as lists of cells")

    model_config = {"from_attributes": True}
