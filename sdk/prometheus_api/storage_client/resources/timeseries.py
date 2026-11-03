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

"""Timeseries resource for synchronous operations."""

from typing import Any, Dict, Optional, Sequence
from ..models.timeseries import TimeseriesResult
from .base import BaseResource


def build_query_payload(
    sql_query: Optional[str],
    limit: Optional[int],
    row_stride: Optional[int],
    start_row: Optional[int],
    stop_row: Optional[int],
    columns: Optional[Sequence[str]],
) -> Dict[str, Any]:
    """The JSON body for ``olap/query``: only the options the caller provided, camelCase."""
    candidates = {
        "query": sql_query,
        "limit": limit,
        "rowStride": row_stride,
        "startRow": start_row,
        "stopRow": stop_row,
        "columns": list(columns) if columns is not None else None,
    }
    return {key: value for key, value in candidates.items() if value is not None}


class TimeseriesResource(BaseResource):
    """Handles queries over tabular (timeseries) file records."""

    def query(
        self,
        record_id: int,
        view_name: str = "data",
        sql_query: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        row_stride: Optional[int] = None,
        start_row: Optional[int] = None,
        stop_row: Optional[int] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> TimeseriesResult:
        """Query the rows of a tabular file (csv or parquet) record.

        Calls ``POST .../records/{record_id}/olap/query``. The server exposes the file as a
        temporary SQL view called ``view_name`` and runs ``sql_query`` against it, so the
        query must mention ``view_name``. Without a query it returns ``SELECT * FROM`` the
        view, limited to ``limit`` rows (the server's default is 20).

        Args:
            record_id: ID of the record that points at the tabular file or folder of parts
            view_name: Name of the view the query refers to (letters, digits, underscore)
            sql_query: A single SQL ``SELECT`` over ``view_name``. The server rejects
                statements containing ``COPY``, ``EXPORT``, ``IMPORT``, ``INSERT``, ``UPDATE``,
                ``DELETE``, ``DROP``, ``ALTER``, ``ATTACH``, ``CREATE`` of tables, views or
                secrets, file-reading functions, or a ``;``, as a case-insensitive substring
                match, so a column name such as ``updated`` can be rejected too.
                Quote column names that contain dots, for example ``"a.b"``.
            limit: Maximum rows, 1 to 100000
            row_stride: Keep every Nth row (1 keeps all)
            start_row: First row to include; rows are numbered from 1 in file order
            stop_row: Last row to include
            columns: Column names to keep. Names with dots or other symbols are rejected by
                the server here; select them with ``sql_query`` instead.

        Returns:
            The column names and rows. A window past the end of the data is an empty result,
            not an error.

        Raises:
            ValidationError: If the server rejects the query or options
            ItemNotFoundError: If the record or its file does not exist

        Note:
            Each call opens a fresh query engine on the server and can take many seconds on
            large files. Raise ``ConnectionConfig.timeout`` if requests time out.

        Example:
            ```python
            result = client.timeseries.query(
                record_id=123,
                sql_query='SELECT "Timestamp", power FROM data WHERE power > 5',
            )
            print(result.columns, result.data[:3])
            ```
        """
        response = self._client._request(
            "POST",
            f"{self._base_path}/records/{record_id}/olap/query",
            params={"viewName": view_name},
            json=build_query_payload(sql_query, limit, row_stride, start_row, stop_row, columns),
        )

        data = response.json()
        return TimeseriesResult(
            columns=data.get("columns") or [],
            data=data.get("data") or [],
        )
