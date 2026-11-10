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

"""Timeseries resource for asynchronous operations."""

from typing import Optional, Sequence
from ..models.timeseries import TimeseriesResult
from ..resources.timeseries import build_query_payload, parse_query_response
from .base import AsyncBaseResource


class AsyncTimeseriesResource(AsyncBaseResource):
    """Handles async queries over tabular (timeseries) file records."""

    async def query(
        self,
        record_id: int,
        *,
        view_name: str = "data",
        sql_query: Optional[str] = None,
        limit: Optional[int] = None,
        row_stride: Optional[int] = None,
        start_row: Optional[int] = None,
        stop_row: Optional[int] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> TimeseriesResult:
        """Query the rows of a tabular file record asynchronously.

        Takes the same arguments and returns the same result as
        ``TimeseriesResource.query``; see its documentation for the server's rules.
        """
        response = await self._client._request(
            "POST",
            f"{self._base_path}/records/{record_id}/olap/query",
            params={"viewName": view_name},
            json=build_query_payload(sql_query, limit, row_stride, start_row, stop_row, columns),
        )

        return parse_query_response(response.json())
