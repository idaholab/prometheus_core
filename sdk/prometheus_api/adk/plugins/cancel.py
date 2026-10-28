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
"""Cancel plugin: stop an aborted ADK run and keep its honest partial result (REQ-016-06).

The run is aborted when the ``abort_signal`` given to ``Runner.run_async`` is set (ADK exposes
it to callbacks as ``is_aborted``) or when the event injected as ``abort_signal`` is set. From
then on:

- ``before_tool_callback`` answers every new call with ``CANCELLED_RESULT`` and the tool does
  not run.
- The first time, the plugin calls ``cancel()`` on each ``PrometheusWorker`` given to
  ``register_worker`` and ``on_cancel()`` (a function or a coroutine function, no arguments)
  of each long-running tool of the run that has one.
- ``provenance.mark_cancelled`` gets the finished artifacts, so the provenance plugin closes
  the execution record as ``cancelled`` with them. Call it in the request context of the run.

The plugin counts the tool calls the model requested and the calls that finished, and the
artifacts saved (the ``artifact_delta`` of the run's events, as ``filename@version``), and
``summary()`` gives the final status text.
"""

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.adk.utils._function_call_names import CLIENT_FUNCTION_CALL_NAMES

from ...agent.worker import PrometheusWorker
from .provenance import ProvenancePlugin

if TYPE_CHECKING:
    from ...agent.base import PrometheusAgent

logger = logging.getLogger(__name__)

CANCELLED_RESULT: dict[str, Any] = {"status": "cancelled"}


class CancelPlugin(BasePlugin):
    """Block new tool calls after the run's abort signal and stop its workers and jobs.

    Built as ``CancelPlugin(agent, provenance=..., abort_signal=...)``: ``provenance`` is the
    run's ``ProvenancePlugin`` (``None`` writes no record), and ``abort_signal`` is the event
    passed to ``Runner.run_async`` (``None`` relies on ADK's ``is_aborted`` only).
    """

    def __init__(
        self,
        agent: "PrometheusAgent",
        *,
        provenance: ProvenancePlugin | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> None:
        super().__init__(name="prometheus_cancel")
        self._agent = agent
        self._provenance = provenance
        self._abort_signal = abort_signal
        self._workers: list[PrometheusWorker] = []
        self._reset()

    def register_worker(self, worker: PrometheusWorker) -> None:
        """Register a worker of the run; it gets ``cancel()`` when the run is aborted."""
        self._workers.append(worker)

    def summary(self) -> str | None:
        """Return the final status text of a cancelled run, or ``None`` when it was not."""
        if not self._cancelled and not self._signal_set():
            return None
        return (
            f"Cancelled after {self._finished} of {self._requested} tool calls; "
            f"{len(self._artifacts)} artifacts kept"
        )

    async def before_run_callback(self, *, invocation_context: InvocationContext) -> None:
        self._reset()
        return None

    async def on_event_callback(
        self, *, invocation_context: InvocationContext, event: Event
    ) -> Event | None:
        for filename, version in event.actions.artifact_delta.items():
            self._artifacts.setdefault(f"{filename}@{version}", None)
        self._requested += sum(
            1 for call in event.get_function_calls() if call.name not in CLIENT_FUNCTION_CALL_NAMES
        )
        if invocation_context.is_aborted or self._signal_set():
            await self._abort()
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        if tool_context.is_aborted or self._signal_set():
            await self._abort()
            return dict(CANCELLED_RESULT)
        if tool.is_long_running and callable(getattr(tool, "on_cancel", None)):
            self._jobs.setdefault(id(tool), tool)
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not (isinstance(result, dict) and result.get("status") == "cancelled"):
            self._finished += 1
        return None

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        if self._cancelled:
            self._mark_cancelled()
        return None

    def _reset(self) -> None:
        self._cancelled = False
        self._requested = 0
        self._finished = 0
        self._artifacts: dict[str, None] = {}
        self._jobs: dict[int, BaseTool] = {}

    def _signal_set(self) -> bool:
        return self._abort_signal is not None and self._abort_signal.is_set()

    def _mark_cancelled(self) -> None:
        if self._provenance is not None:
            self._provenance.mark_cancelled(list(self._artifacts))

    async def _abort(self) -> None:
        """Stop the workers and jobs once, and hand the finished artifacts to provenance."""
        if not self._cancelled:
            self._cancelled = True
            logger.info("Run of %s aborted; blocking new tool calls", self._agent.agent_name)
            for worker in self._workers:
                worker.cancel()
            for tool in self._jobs.values():
                outcome = getattr(tool, "on_cancel")()
                if inspect.isawaitable(outcome):
                    await outcome
        self._mark_cancelled()
