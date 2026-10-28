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
"""Bridge ADK run events onto the A2A events a ``PrometheusAgent`` emits today."""

from typing import Any

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.plugins import BasePlugin
from google.adk.utils._function_call_names import (
    CLIENT_FUNCTION_CALL_NAMES,
    REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
    REQUEST_INPUT_FUNCTION_CALL_NAME,
)
from google.genai import types

from ...agent.artifacts import ArtifactReference
from ...agent.base import MissingInput, PrometheusAgent

PENDING_FUNCTION_CALL_IDS_METADATA_KEY = "pendingFunctionCallIds"


class A2ABridgePlugin(BasePlugin):
    """Turn ADK events into the status, input-required and artifact events of the agent.

    Only A2A types leave this plugin: every event goes through the agent's existing
    ``send_status_update``, ``send_input_required`` and ``send_artifact_reference``.
    With ``emit_events=False`` it emits artifact references only, for an agent that
    builds its own final status from the run (the client-agent).
    """

    def __init__(
        self,
        agent: PrometheusAgent,
        context: RequestContext,
        event_queue: EventQueue,
        *,
        emit_events: bool = True,
    ) -> None:
        super().__init__(name="a2a_bridge")
        self._agent = agent
        self._context = context
        self._event_queue = event_queue
        self._emit_events = emit_events

    async def on_event_callback(
        self, *, invocation_context: InvocationContext, event: Event
    ) -> Event | None:
        """Emit a status update for each tool call and model text, and pause on a pending call."""
        if not self._emit_events or event.author == "user" or event.partial:
            return None
        pending_ids = event.long_running_tool_ids or set()
        calls = event.get_function_calls()
        for call in calls:
            if call.id not in pending_ids and call.name not in CLIENT_FUNCTION_CALL_NAMES:
                await self._agent.send_status_update(
                    self._context, self._event_queue, message=f"Running {call.name}"
                )
        if not calls:
            text = event_text(event)
            if text:
                await self._agent.send_status_update(self._context, self._event_queue, message=text)
        pending = [call for call in calls if call.id in pending_ids]
        if pending:
            await self._agent.send_input_required(
                self._context,
                self._event_queue,
                missing_inputs=[_missing_input(call) for call in pending],
                hint=_pending_hint(pending[0]),
                metadata={PENDING_FUNCTION_CALL_IDS_METADATA_KEY: [call.id for call in pending]},
            )
        return None

    async def emit_artifact_reference(
        self, item: int, filename: str, mime_type: str | None, uri: str
    ) -> ArtifactReference:
        """Register and emit DeepLynx item ``item`` the way ``send_deeplynx_artifact`` does."""
        return await self._agent.send_artifact_reference(
            context=self._context,
            event_queue=self._event_queue,
            name=filename,
            description=filename,
            uri=uri,
            mime_type=mime_type or "application/octet-stream",
            metadata={"deeplynx_item_id": item, "deeplynx_file_id": item},
        )


def event_text(event: Event) -> str:
    """Return the visible (non-thought) text of an ADK event."""
    if event.content is None or not event.content.parts:
        return ""
    return "".join(part.text for part in event.content.parts if part.text and not part.thought)


def _call_args(call: types.FunctionCall) -> dict[str, Any]:
    return dict(call.args or {})


def _pending_hint(call: types.FunctionCall) -> str:
    """Return the question a pending call puts to the user."""
    args = _call_args(call)
    if call.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
        confirmation = args.get("toolConfirmation") or {}
        original = args.get("originalFunctionCall") or {}
        return str(confirmation.get("hint") or f"Confirm {original.get('name', 'the tool call')}")
    if call.name == REQUEST_INPUT_FUNCTION_CALL_NAME:
        return str(args.get("message") or "I need some additional information to proceed:")
    return f"{call.name} is waiting for your input."


def _missing_input(call: types.FunctionCall) -> MissingInput:
    """Describe the answer a pending call waits for."""
    hint = _pending_hint(call)
    if call.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
        return MissingInput(
            name="confirmed",
            description="Whether the tool call may run.",
            user_prompt=hint,
            type="boolean",
        )
    schema = _call_args(call).get("response_schema") or {}
    return MissingInput(
        name=call.name or "response",
        description=hint,
        user_prompt=hint,
        type=str(schema.get("type") or "string"),
    )
