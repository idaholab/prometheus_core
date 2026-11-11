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

"""Resuming an INPUT_REQUIRED task through the real A2A request handler."""

from __future__ import annotations

import json
import uuid

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
    TaskState,
    TaskStatusUpdateEvent,
)

from prometheus_api.agent import EventQueue, PrometheusAgentExecutor, RequestContext
from prometheus_api.agent.events import emit_status_update


class AskThenFinishExecutor(PrometheusAgentExecutor):
    """Pauses for input on the first request and finishes on the resume."""

    def __init__(self) -> None:
        super().__init__(agent_name="Resume Agent")
        self.calls = 0

    async def _execute(self, params, context: RequestContext, event_queue: EventQueue):
        self.calls += 1
        if self.calls == 1:
            await emit_status_update(
                context=context,
                event_queue=event_queue,
                state=TaskState.TASK_STATE_INPUT_REQUIRED,
                final=True,
                message="Need approval",
            )
            return {}
        return {"status": "resumed", "answer": params.get("answer")}


def _agent_card(*, streaming: bool = False) -> AgentCard:
    return AgentCard(
        name="Resume Agent",
        description="Pauses for input, then finishes",
        supported_interfaces=[AgentInterface(url="http://testserver/", protocol_binding="JSONRPC")],
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=streaming),
        skills=[AgentSkill(id="resume", name="Resume", description="Resume", tags=["test"])],
        default_input_modes=["text"],
        default_output_modes=["text"],
    )


def _request(payload: dict, *, task_id: str = "", context_id: str = "") -> SendMessageRequest:
    message = Message(
        message_id=str(uuid.uuid4()),
        role=Role.ROLE_USER,
        parts=[Part(text=json.dumps(payload))],
    )
    if task_id:
        message.task_id = task_id
    if context_id:
        message.context_id = context_id
    return SendMessageRequest(message=message)


def _status_text(event: Task | TaskStatusUpdateEvent) -> str:
    return "".join(part.text for part in event.status.message.parts)


async def _pause_for_input(handler: DefaultRequestHandler) -> Task:
    first = await handler.on_message_send(_request({"skill_id": "resume"}), ServerCallContext())
    assert isinstance(first, Task)
    assert first.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    return first


async def test_resumed_input_required_task_returns_the_resumed_result():
    """Covers REQ-009-24 and BEH-009-11."""
    executor = AskThenFinishExecutor()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=_agent_card(),
    )

    first = await _pause_for_input(handler)

    resume = _request(
        {"skill_id": "resume", "answer": "approve"},
        task_id=first.id,
        context_id=first.context_id,
    )
    resumed = await handler.on_message_send(resume, ServerCallContext())

    assert isinstance(resumed, Task)
    assert resumed.id == first.id
    assert resumed.status.state == TaskState.TASK_STATE_COMPLETED
    assert json.loads(_status_text(resumed)) == {"status": "resumed", "answer": "approve"}
    assert resume.message.message_id in [message.message_id for message in resumed.history]
    assert executor.calls == 2


async def test_resumed_input_required_stream_starts_with_working_status():
    """Covers REQ-009-24 and BEH-009-11."""
    executor = AskThenFinishExecutor()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=_agent_card(streaming=True),
    )
    first = await _pause_for_input(handler)

    resume = _request(
        {"skill_id": "resume", "answer": "approve"},
        task_id=first.id,
        context_id=first.context_id,
    )
    events = [event async for event in handler.on_message_send_stream(resume, ServerCallContext())]

    assert all(isinstance(event, TaskStatusUpdateEvent) for event in events)
    assert events[0].status.state == TaskState.TASK_STATE_WORKING
    assert events[-1].status.state == TaskState.TASK_STATE_COMPLETED
    assert json.loads(_status_text(events[-1])) == {"status": "resumed", "answer": "approve"}
    assert executor.calls == 2
