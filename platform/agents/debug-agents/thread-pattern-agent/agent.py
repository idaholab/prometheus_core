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

"""
Thread Pattern Debug Agent
==========================

A reference agent for running **long, blocking work** without freezing the
single event loop, using ``PrometheusWorker`` + ``PrometheusAgent.run_worker``.

Why this matters
----------------
A Prometheus agent runs as one process with one asyncio event loop. A blocking
call (a synchronous SDK, a legacy library, a CPU loop, ``time.sleep``) does not
``await``, so while it runs nothing else on the loop can run: not the keepalive
heartbeat, not the A2A SSE consumer that flushes bytes to the caller, not other
clients. If the gap exceeds the upstream socket-read timeout (the registry gateway),
the streaming connection is torn down even though the agent is still working.

The pattern
-----------
Put the blocking work in a ``PrometheusWorker.run()`` (plain synchronous code on
a worker thread). From inside ``run`` it emits progress with the safe-subset
helpers — ``emit_status_update`` and ``emit_json_artifact`` — into a thread-safe
mailbox. ``await self.run_worker(worker, context, event_queue)`` runs it off-loop
and drains that mailbox from the event loop, so the loop stays free for the
heartbeat and SSE to keep flowing. The worker checks ``self.cancelled`` to stop
cooperatively (threads cannot be force-killed).

Skills
------
- ``run_blocking_task``    — foreground demo. The client-agent waits for it;
  status (and a JSON summary artifact) stream the whole time. Optional
  ``duration_seconds`` (default 60) controls how long the worker blocks.
- ``run_background_task``  — same blocking work, but calls
  ``declare_long_running`` first so the orchestrator proactively detaches the
  turn (the user regains control immediately and is notified out-of-band on
  completion). The reference exercise for the agent-driven background-task path.
"""
import time
from datetime import datetime, timezone
from typing import Any, Dict

from prometheus_api.agent import PrometheusAgent, PrometheusWorker
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

# Skill identifiers (must match agent_card.json).
SKILL_BLOCKING = "run_blocking_task"
SKILL_BACKGROUND = "run_background_task"

DEFAULT_DURATION_SECONDS = 60
MAX_DURATION_SECONDS = 600
# How often run_worker drains progress and lets the loop breathe. Keep this well
# under the heartbeat interval (default 15s) so real progress updates supersede
# heartbeats while the worker is reporting.
POLL_INTERVAL_SECONDS = 1.0


class BlockingDemoWorker(PrometheusWorker):
    """Stand-in for a real blocking workload (a sync SDK, a legacy analysis tool,
    a CPU loop). It blocks in one-second steps so it can report progress and
    honour cooperative cancellation. A truly opaque blocking call (a single
    ``library.run()`` with no hooks) could not report mid-flight — there the
    loop-side heartbeat alone keeps the connection alive.
    """

    def __init__(self, duration_seconds: int) -> None:
        super().__init__()
        self.duration_seconds = duration_seconds

    def run(self) -> Dict[str, Any]:
        start = time.monotonic()
        elapsed = 0
        while elapsed < self.duration_seconds:
            if self.cancelled:
                return {
                    "status": "cancelled",
                    "requested_seconds": self.duration_seconds,
                    "elapsed_seconds": elapsed,
                }
            time.sleep(1)  # the blocking wait that never yields to the event loop
            elapsed = int(time.monotonic() - start)
            self.emit_status_update(
                f"Blocking compute in progress… {elapsed}/{self.duration_seconds}s elapsed."
            )

        # A JSON artifact is handy for verbose, structured progress output —
        # e.g. intermediate results streamed from a long numerical simulation.
        self.emit_json_artifact(
            {"requested_seconds": self.duration_seconds, "elapsed_seconds": elapsed},
            name="blocking_task_summary",
            json_type="prometheus.debug.blocking_summary.v1",
        )
        return {
            "status": "success",
            "requested_seconds": self.duration_seconds,
            "elapsed_seconds": elapsed,
        }


class ThreadPatternAgent(PrometheusAgent):
    """Reference agent for the offload-and-observe pattern."""

    async def _execute(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        # The base executor injects the invoked skill as params["skill_id"]
        # from the A2A message metadata. Default to the foreground demo.
        skill_id = str(params.get("skill_id") or SKILL_BLOCKING)
        duration_seconds = self._resolve_duration_seconds(params)

        if skill_id == SKILL_BACKGROUND:
            return await self._run_background_task(params, context, event_queue, duration_seconds)
        return await self._run_foreground_blocking(params, context, event_queue, duration_seconds)

    @staticmethod
    def _resolve_duration_seconds(params: Dict[str, Any]) -> int:
        """Read the optional duration parameter, clamped to a sane range."""
        raw = params.get("duration_seconds", DEFAULT_DURATION_SECONDS)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = DEFAULT_DURATION_SECONDS
        return max(1, min(value, MAX_DURATION_SECONDS))

    # ------------------------------------------------------------------ #
    # Skill 1: foreground blocking task (PrometheusWorker + run_worker)
    # ------------------------------------------------------------------ #
    async def _run_foreground_blocking(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
        duration_seconds: int,
    ) -> Dict[str, Any]:
        """Run a blocking compute on a worker thread, streaming progress.

        The client-agent waits for this skill; because the blocking work runs
        off-loop and run_worker forwards the worker's events from the loop, the
        caller sees a steady stream of status updates (plus heartbeats) for the
        whole duration instead of a silent connection that times out.
        """
        await self.send_status_update(
            context=context,
            event_queue=event_queue,
            message=f"Starting blocking task ({duration_seconds}s) on a worker thread…",
        )

        worker = BlockingDemoWorker(duration_seconds)
        # run_worker runs worker.run() off-loop, forwards its emitted events from
        # the loop, flushes on completion, re-raises worker errors, and on caller
        # cancellation signals the worker to stop cooperatively.
        result = await self.run_worker(
            worker, context, event_queue, poll_interval=POLL_INTERVAL_SECONDS
        )
        result.setdefault("message", f"Blocking task finished after {result.get('elapsed_seconds')}s.")
        return result

    # ------------------------------------------------------------------ #
    # Skill 2: background task (declare_long_running → orchestrator detaches)
    # ------------------------------------------------------------------ #
    async def _run_background_task(
        self,
        params: Dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
        duration_seconds: int,
    ) -> Dict[str, Any]:
        """Declare the work long-running up front, then run it like the
        foreground path.

        ``declare_long_running`` emits an early status tagged
        ``metadata.background = True``. The orchestrator (client-agent) sees that
        flag on the stream and *proactively detaches the turn*: the user regains
        control immediately and is notified out-of-band when this finishes —
        rather than waiting out the orchestrator's soft deadline.

        From this agent's side the execution is identical to the foreground demo:
        the blocking work still runs on a ``PrometheusWorker`` via ``run_worker``,
        streaming progress the whole time. The only difference is the early
        declaration. The detach/notify machinery lives entirely in the
        orchestrator + frontend; this agent just opts in.

        See ``docs/dev-docs/background-tasks-implementation.md``.
        """
        await self.declare_long_running(
            context=context,
            event_queue=event_queue,
            estimate_seconds=duration_seconds,
            message=(
                f"Accepted; this will take ~{duration_seconds}s and will run in "
                "the background while you keep working."
            ),
        )

        worker = BlockingDemoWorker(duration_seconds)
        result = await self.run_worker(
            worker, context, event_queue, poll_interval=POLL_INTERVAL_SECONDS
        )
        result["background"] = True
        result.setdefault(
            "message",
            f"Background task finished after {result.get('elapsed_seconds')}s.",
        )
        result.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        return result


if __name__ == "__main__":
    agent = ThreadPatternAgent(agent_name="Thread Pattern Debug Agent")
    agent.run()
