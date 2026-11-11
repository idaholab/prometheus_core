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
"""LangGraph middleware: provenance edges, the tool-call log, approval and compaction.

``ProvenanceMiddleware`` writes to the execution record that ``PrometheusAgent`` creates
before ``_execute`` (``PrometheusContext.execution_record_id``); it never creates a second
record (REQ-017-03):

- after each tool call, one ``{tool, tool_call_id, arguments_sha256, result_sha256,
  duration_ms}`` entry in ``ProvenanceLedger.tool_calls``, and one
  ``relationships.bulk_create`` of the ledger's pending ``generated`` and ``input_to`` edges.
  The first flush of a record reads its existing relations, so a resumed run writes each
  ``(from, to, type)`` once.
- when the graph ends without an interrupt, one ``items.update`` of the record with
  ``status``, ``ended_at`` and ``tool_calls``. A paused run keeps its record open. A tool
  exception closes the record ``failed`` and re-raises.

Arguments and results are stored as SHA-256 digests only. Without an execution record or a
DeepLynx configuration, nothing is written to DeepLynx. Storage clients come from
``artifacts.open_storage``, the seam that tests replace.

``summarization`` and ``approval`` build the stock ``SummarizationMiddleware`` (REQ-017-05)
and ``HumanInTheLoopMiddleware``.
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any, cast

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    HumanInTheLoopMiddleware,
    SummarizationMiddleware,
    ToolCallRequest,
)
from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from langgraph.types import Command

from ..llm_client import AsyncLLMClient
from ..storage_client.models.relationship import RelationshipCreate
from . import artifacts
from .artifacts import PrometheusContext, ProvenanceLedger
from .model import PrometheusChatModel

logger = logging.getLogger(__name__)

Edge = tuple[int, int, str]

_SUMMARY_INSTRUCTION = (
    "Copy every deeplynx:// URI, artifact_id and tool_call_id of the conversation history "
    "into the extracted context verbatim. Never shorten, paraphrase or drop one.\n\n"
)
SUMMARY_PROMPT = DEFAULT_SUMMARY_PROMPT.replace(
    "<messages>", _SUMMARY_INSTRUCTION + "<messages>", 1
)


def _sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _result_value(result: ToolMessage | Command[Any]) -> Any:
    return result.content if isinstance(result, ToolMessage) else result


def log_call(
    ledger: ProvenanceLedger,
    tool_call: dict[str, Any],
    result: ToolMessage | Command[Any],
    duration_s: float,
) -> None:
    """Append the digest entry of one finished tool call to *ledger*."""
    ledger.tool_calls.append(
        {
            "tool": tool_call.get("name"),
            "tool_call_id": tool_call.get("id"),
            "arguments_sha256": _sha256(tool_call.get("args")),
            "result_sha256": _sha256(_result_value(result)),
            "duration_ms": round(duration_s * 1000),
        }
    )


class ProvenanceMiddleware(AgentMiddleware[AgentState[Any], PrometheusContext]):
    """Write the run's ``generated`` and ``input_to`` edges and close its execution record."""

    def __init__(self) -> None:
        super().__init__()
        # The edges each open record already has in DeepLynx, read once per record.
        self._known: dict[int, set[Edge]] = {}

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        ctx = cast(PrometheusContext, request.runtime.context)
        started = time.perf_counter()
        try:
            result = await handler(request)
        except GraphBubbleUp:
            # An interrupt pauses the run; its record stays open.
            raise
        except Exception:
            await self.flush_edges(ctx)
            await self.close_record(ctx, status="failed")
            raise
        log_call(ctx.provenance, dict(request.tool_call), result, time.perf_counter() - started)
        await self.flush_edges(ctx)
        return result

    async def aafter_agent(
        self, state: AgentState[Any], runtime: Runtime[PrometheusContext]
    ) -> dict[str, Any] | None:
        await self.close_record(runtime.context, status="succeeded")
        return None

    async def flush_edges(self, ctx: PrometheusContext) -> None:
        """Write the ledger's pending edges once with ``relationships.bulk_create``."""
        ledger = ctx.provenance
        record_id = ctx.execution_record_id
        if record_id is None or ctx.storage is None:
            ledger.edges.clear()
            return
        if not ledger.edges and record_id in self._known:
            return
        async with artifacts.open_storage(ctx.storage) as dl:
            known = self._known.get(record_id)
            if known is None:
                known = {
                    (rel.from_item_id, rel.to_item_id, rel.relationship_type)
                    for rel in await dl.relationships.get_item_relationships(record_id)
                }
                self._known[record_id] = known
            pending = [edge for edge in ledger.edges if edge not in known]
            if pending:
                await dl.relationships.bulk_create(
                    [
                        RelationshipCreate(from_item_id=src, to_item_id=dst, relationship_type=kind)
                        for src, dst, kind in pending
                    ]
                )
                known.update(pending)
        ledger.edges.clear()

    async def close_record(self, ctx: PrometheusContext, status: str) -> None:
        """Update the execution record once with ``status``, ``ended_at`` and ``tool_calls``.

        The ledger's tool-call log is emptied afterwards, so a later run on the same context
        writes only its own calls.
        """
        ledger = ctx.provenance
        record_id = ctx.execution_record_id
        tool_calls = list(ledger.tool_calls)
        ledger.tool_calls.clear()
        if record_id is None or ctx.storage is None:
            logger.debug("No execution record for this run; provenance is not written")
            return
        self._known.pop(record_id, None)
        close = {
            "status": status,
            "ended_at": datetime.now(UTC).isoformat(),
            "tool_calls": tool_calls,
        }
        async with artifacts.open_storage(ctx.storage) as dl:
            await artifacts.merge_item_properties(dl, record_id, close)
        logger.info("Closed execution record %s as %s", record_id, status)


def summarization(
    client: AsyncLLMClient,
    trigger_tokens: int | None = None,
    keep_messages: int | None = None,
) -> SummarizationMiddleware:
    """Return the compaction middleware on the ``small`` alias (REQ-017-05).

    The thresholds default to ``LANGGRAPH_SUMMARY_TRIGGER_TOKENS`` (24000) and
    ``LANGGRAPH_SUMMARY_KEEP_MESSAGES`` (20).
    """
    if trigger_tokens is None:
        trigger_tokens = int((os.getenv("LANGGRAPH_SUMMARY_TRIGGER_TOKENS") or "24000").strip())
    if keep_messages is None:
        keep_messages = int((os.getenv("LANGGRAPH_SUMMARY_KEEP_MESSAGES") or "20").strip())
    return SummarizationMiddleware(
        model=PrometheusChatModel(alias="small", client=client),
        trigger=("tokens", trigger_tokens),
        keep=("messages", keep_messages),
        summary_prompt=SUMMARY_PROMPT,
    )


def approval(
    card_skills: Iterable[dict[str, Any]],
    extra_tools: Iterable[str] = (),
) -> HumanInTheLoopMiddleware | None:
    """Return the approval middleware for the tools that need approval, or ``None``.

    A tool needs approval when the card skill whose ``id`` is its name has
    ``requires_approval: true``, or when it is in *extra_tools*.
    """
    tools = [
        str(skill["id"])
        for skill in card_skills
        if isinstance(skill, dict) and skill.get("requires_approval") is True and skill.get("id")
    ]
    tools.extend(extra_tools)
    if not tools:
        return None
    return HumanInTheLoopMiddleware(
        interrupt_on={tool: {"allowed_decisions": ["approve", "reject"]} for tool in tools}
    )
