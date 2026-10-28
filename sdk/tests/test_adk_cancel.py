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

"""Tests for the ADK cancel plugin and the cancel path of ``AdkPrometheusAgent``.

The runs go through the agent's A2A executor with in-memory ADK services
(``adk_test_mode``) and a stub model, so no real LLM is involved. DeepLynx is a recording
fake of the ``AsyncStorageClient`` surface that the execution record and the provenance
plugin use.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import TaskState, TaskStatusUpdateEvent
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.tools.tool_context import ToolContext
from google.adk.workflow import BaseNode
from google.genai import types

from prometheus_api.adk.agent import AdkPrometheusAgent
from prometheus_api.adk.plugins import provenance
from prometheus_api.adk.plugins.cancel import CancelPlugin
from prometheus_api.agent import PrometheusWorker
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.item import Item, ItemUpdate

SKILL = "cancel_skill"
RECORD_ID = 41
TOOLS = ("save_report", "tool_two", "tool_three")


class _StubLlm(BaseLlm):
    """Calls the given tools in one model event, then answers with text after the responses."""

    model: str = "stub"
    tools: tuple[str, ...] = TOOLS

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            parts = [types.Part(text="done")]
        else:
            parts = [
                types.Part(function_call=types.FunctionCall(name=name, args={}))
                for name in self.tools
            ]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


class _RecordingQueue:
    """An event queue fake that records what the executor enqueues."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


class _Records:
    """Records each execution-record update that the provenance plugin makes."""

    def __init__(self) -> None:
        self.updates: list[tuple[int, ItemUpdate]] = []


def _fake_record_client(records: _Records) -> type:
    class _FakeItems:
        async def create(self, item: Any) -> SimpleNamespace:
            return SimpleNamespace(id=RECORD_ID)

        async def get(self, item_id: int) -> Item:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            return Item(
                id=item_id,
                name=f"Execution record {item_id}",
                properties={"agent_name": "cancel_agent"},
                created_at=now,
                updated_at=now,
            )

        async def update(self, item_id: int, update: ItemUpdate) -> None:
            records.updates.append((item_id, update))

    class _FakeClient:
        """The ``AsyncStorageClient`` surface of the execution record and provenance."""

        def __init__(self, config: ConnectionConfig) -> None:
            self.items = _FakeItems()

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    return _FakeClient


@pytest.fixture
def records(monkeypatch: pytest.MonkeyPatch) -> _Records:
    """Fake DeepLynx for the execution record (agent base) and the provenance plugin."""
    recorder = _Records()
    client = _fake_record_client(recorder)

    async def get_credential(self: Any, resource: str, scope: Any = None) -> SimpleNamespace:
        return SimpleNamespace(value={"org_id": 1, "project_id": 2, "key": "k", "secret": "s"})

    async def fake_deeplynx_config(agent: Any, user_id: str) -> ConnectionConfig:
        return ConnectionConfig(organization_id=1, project_id=2, jwt_token="t")

    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", client)
    monkeypatch.setattr(AdkPrometheusAgent, "get_credential", get_credential)
    monkeypatch.setattr(provenance, "AsyncStorageClient", client)
    monkeypatch.setattr(provenance, "deeplynx_config", fake_deeplynx_config)
    return recorder


class _CancelAgent(AdkPrometheusAgent):
    """An ADK agent with one card skill, no compaction, and in-memory ADK services.

    ``create_runner`` registers ``worker`` with the run's cancel plugin and keeps the run's
    abort signal in ``abort_signals``.
    """

    compaction = None
    adk_test_mode = True

    def __init__(self, root: BaseNode, worker: PrometheusWorker | None = None) -> None:
        super().__init__(agent_name="Cancel Agent")
        self.adk_agents = {SKILL: root}
        self.worker = worker
        self.abort_signals: list[asyncio.Event] = []

    def get_raw_agent_card(self) -> dict[str, Any]:
        return {"name": self.agent_name, "skills": [{"id": SKILL, "name": "Cancel"}]}

    def create_runner(
        self,
        context: RequestContext,
        root: BaseNode,
        *,
        event_queue: EventQueue,
        abort_signal: asyncio.Event,
    ) -> Runner:
        runner = super().create_runner(
            context, root, event_queue=event_queue, abort_signal=abort_signal
        )
        self.abort_signals.append(abort_signal)
        cancel = runner.plugin_manager.get_plugin("prometheus_cancel")
        assert isinstance(cancel, CancelPlugin)
        if self.worker is not None:
            cancel.register_worker(self.worker)
        return runner


def _context(task_id: str) -> MagicMock:
    context = MagicMock(spec=RequestContext)
    context.task_id = task_id
    context.context_id = f"context-{task_id}"
    context.current_task = None
    context.message = None
    context.get_user_input.return_value = json.dumps({"skill_id": SKILL})
    return context


def _statuses(queue: _RecordingQueue) -> list[TaskStatusUpdateEvent]:
    return [event for event in queue.events if isinstance(event, TaskStatusUpdateEvent)]


async def test_cancel_blocks_new_tools(records: _Records) -> None:
    """Covers REQ-016-06."""
    ran: list[str] = []
    context = _context("task-cancel")
    worker = PrometheusWorker()
    agent: _CancelAgent

    async def save_report(tool_context: ToolContext) -> dict[str, Any]:
        """Cancel the run, then save the report artifact."""
        ran.append("save_report")
        # ADK starts the three calls of one model event as parallel tasks. The abort is set
        # before this tool's first suspension point, so the before-tool callbacks of tools 2
        # and 3 always see it, however the tasks interleave.
        await agent.on_cancel(context)
        await tool_context.save_artifact("report.txt", types.Part(text="partial report"))
        return {"saved": "report.txt"}

    def tool_two() -> dict[str, Any]:
        """The second tool."""
        ran.append("tool_two")
        return {"ok": 2}

    def tool_three() -> dict[str, Any]:
        """The third tool."""
        ran.append("tool_three")
        return {"ok": 3}

    root = LlmAgent(
        name="cancel_agent", model=_StubLlm(), tools=[save_report, tool_two, tool_three]
    )
    agent = _CancelAgent(root, worker)
    queue = _RecordingQueue()

    await agent.create_executor().execute(context, queue)  # type: ignore[arg-type]

    assert ran == ["save_report"], "a tool ran after the run's abort signal was set"
    assert worker.cancelled is True
    assert len(records.updates) == 1, "the execution record was not closed exactly once"
    record_id, update = records.updates[0]
    assert record_id == RECORD_ID
    assert update.properties is not None
    assert update.properties["status"] == "cancelled"
    assert update.properties["artifact_ids"] == ["report.txt@0"]
    final = _statuses(queue)[-1]
    final_text = final.status.message.parts[0].text
    assert json.loads(final_text)["status"] == "cancelled"
    assert "1 of 3" in final_text


async def test_executor_cancel_sets_abort_before_canceled_status(records: _Records) -> None:
    """Covers BEH-016-02."""
    started = asyncio.Event()
    release = asyncio.Event()
    context = _context("task-running")

    async def slow_tool() -> dict[str, Any]:
        """Wait until the test releases the run."""
        started.set()
        await release.wait()
        return {"ok": True}

    root = LlmAgent(name="cancel_agent", model=_StubLlm(tools=("slow_tool",)), tools=[slow_tool])
    agent = _CancelAgent(root)
    executor = agent.create_executor()
    run = asyncio.create_task(executor.execute(context, _RecordingQueue()))  # type: ignore[arg-type]
    await asyncio.wait_for(started.wait(), timeout=5)

    abort_when_canceled: list[bool] = []

    class _CancelQueue(_RecordingQueue):
        async def enqueue_event(self, event: Any) -> None:
            if (
                isinstance(event, TaskStatusUpdateEvent)
                and event.status.state == TaskState.TASK_STATE_CANCELED
            ):
                abort_when_canceled.append(agent.abort_signals[0].is_set())
            await super().enqueue_event(event)

    try:
        await executor.cancel(context, _CancelQueue())  # type: ignore[arg-type]
    finally:
        release.set()
        await asyncio.wait_for(run, timeout=5)

    assert abort_when_canceled == [True], "the canceled status was emitted before the abort"
