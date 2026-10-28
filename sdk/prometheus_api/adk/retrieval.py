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
"""Retrieval as an ADK tool: the ``retrieve`` tool over a ``RetrievalBroker``.

Each result names its source, DeepLynx item ID, ``deeplynx://`` URI, rank and version, and is
marked untrusted: retrieved text is data for the model, never instructions.
"""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from ..storage_client.async_client import AsyncStorageClient
from .plugins.credentials import deeplynx_config

if TYPE_CHECKING:
    from ..agent.base import PrometheusAgent


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieval result, with the citation fields the model must keep."""

    item_id: int
    uri: str
    name: str
    snippet: str
    score: int
    version: Optional[Any] = None
    source: Literal["deeplynx"] = "deeplynx"
    untrusted: bool = True


class RetrievalBroker(Protocol):
    """Finds the chunks that answer a query for one user."""

    async def search(self, query: str, *, user_id: str, limit: int) -> list[RetrievedChunk]: ...


class DeepLynxRetrievalBroker:
    """Text search over the DeepLynx records of one project, with the user's credential."""

    def __init__(self, agent: "PrometheusAgent", project_id: Optional[int] = None) -> None:
        self._agent = agent
        self._project_id = project_id

    async def search(self, query: str, *, user_id: str, limit: int) -> list[RetrievedChunk]:
        config = await deeplynx_config(self._agent, user_id)
        project_id = self._project_id or config.project_id
        async with AsyncStorageClient(config) as client:
            page = await client.search.advanced_query(
                filters=[], project_ids=[project_id], text_search=query, page_size=limit
            )
        return [
            RetrievedChunk(
                item_id=item.id,
                uri=(
                    f"deeplynx://organizations/{config.organization_id}"
                    f"/projects/{project_id}"
                    f"/items/{item.id}"
                ),
                name=item.name,
                snippet=item.description or "",
                score=rank,
                version=item.properties.get("version"),
            )
            for rank, item in enumerate(page.items, start=1)
        ]


def retrieve_tool(broker: RetrievalBroker) -> FunctionTool:
    """Return the ``retrieve`` tool, which searches *broker* as the calling user."""

    async def retrieve(
        query: str, tool_context: ToolContext, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search the project's records and return cited, untrusted chunks.

        Args:
            query: The text to search for.
            limit: The maximum number of chunks to return.
        """
        chunks = await broker.search(query, user_id=tool_context.user_id, limit=limit)
        return [asdict(chunk) for chunk in chunks]

    return FunctionTool(retrieve)
