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
"""``AdkPrometheusAgent``: a ``PrometheusAgent`` whose skills run as ADK nodes.

Each card skill maps to one ADK agent or ``Workflow`` in ``adk_agents``. A request runs the
node of its ``skill_id`` through ``build_runner``, with the A2A context ID as the ADK session
ID and the params JSON as the first user message. The session state maps each A2A task ID to
its ADK invocation ID, so a request whose task is already there resumes that invocation: its
provided inputs answer the pending confirmation or input call, and without them the run
continues where it stopped.
"""

import asyncio
import json
from typing import Any

import jsonschema  # type: ignore[import-untyped]
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import AgentCard
from google.adk.agents.invocation_context import new_invocation_context_id
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions.session import Session
from google.adk.utils._function_call_names import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.workflow import BaseNode
from google.genai import types
from google.protobuf.json_format import MessageToDict

from ..agent.base import PrometheusAgent
from ..agent.events import context_id as event_context_id
from ..agent.events import context_task_id
from ..agent.identity import USER_TOKEN_METADATA_KEY
from ..llm_client.security import redact_secrets
from .memory import SKILL_ID_STATE_KEY
from .plugins.bridge import event_text
from .plugins.cancel import CancelPlugin
from .plugins.compaction import CompactionPolicy
from .runner import build_runner, commit_run_to_memory, ensure_session

INVOCATION_STATE_KEY_PREFIX = "prometheus_invocation:"

# Keys the executor adds to the params; they are not skill inputs.
_REQUEST_PARAM_KEYS = ("skill_id", "user_id")


class AdkPrometheusAgent(PrometheusAgent):
    """A Prometheus agent whose card skills run as ADK agents or workflows.

    Set on a subclass (or the instance, before the card loads):

    - ``adk_agents``: card skill ID -> ADK agent or ``Workflow``.
    - ``long_running``: skill ID -> estimated seconds; those skills call
      ``declare_long_running`` before they run.
    - ``compaction``: the compaction policy of every runner; ``None`` turns compaction off.
    - ``adk_test_mode``: build runners with in-memory services (``build_runner(test=True)``).

    Override ``create_runner`` to inject a different runner, for example one with a stub
    summarizer. A subclass that overrides ``_execute`` handles the card skills that have no
    node itself and calls ``super()._execute`` for the others.
    """

    adk_agents: dict[str, BaseNode] = {}
    long_running: dict[str, int] = {}
    compaction: CompactionPolicy | None = CompactionPolicy()
    adk_test_mode: bool = False

    def __init__(self, agent_name: str = "Agent", agent_card_path: str | None = None):
        super().__init__(agent_name=agent_name, agent_card_path=agent_card_path)
        self._abort: dict[str, asyncio.Event] = {}

    def load_agent_card(self) -> AgentCard:
        """Load the agent card and check that its skills and ``adk_agents`` match."""
        agent_card = super().load_agent_card()
        self.validate_adk_skills()
        return agent_card

    def validate_adk_skills(self) -> None:
        """Raise ``ValueError`` when a card skill has no node or a node has no card skill.

        A card skill without a node is allowed when the subclass overrides ``_execute``.
        """
        skills = self.get_raw_agent_card().get("skills") or []
        skill_ids = {str(skill.get("id")) for skill in skills if isinstance(skill, dict)}
        handles_unmapped = type(self)._execute is not AdkPrometheusAgent._execute
        no_node = [] if handles_unmapped else sorted(skill_ids - set(self.adk_agents))
        no_skill = sorted(set(self.adk_agents) - skill_ids)
        if no_node or no_skill:
            raise ValueError(
                f"{self.agent_name}: card skills without an ADK node: {no_node}; "
                f"ADK nodes without a card skill: {no_skill}"
            )

    def create_runner(
        self,
        context: RequestContext,
        root: BaseNode,
        *,
        event_queue: EventQueue,
        abort_signal: asyncio.Event,
    ) -> Runner:
        """Build the runner of one request; the test seam of this class."""
        return build_runner(
            self,
            context,
            root,
            event_queue=event_queue,
            compaction=self.compaction,
            test=self.adk_test_mode,
            abort_signal=abort_signal,
        )

    async def on_cancel(self, context: RequestContext) -> None:
        """Set the abort signal of the cancelled task's run, if it is running."""
        abort = self._abort.get(context_task_id(context))
        if abort is not None:
            abort.set()

    async def _execute(
        self,
        params: dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> dict[str, Any]:
        """Run (or resume) the ADK node of ``params["skill_id"]`` and return its result."""
        skill_id = str(params.get("skill_id") or "")
        root = self.adk_agents.get(skill_id)
        if root is None:
            raise ValueError(f"{self.agent_name} has no ADK node for skill {skill_id!r}")
        task_id = context_task_id(context)
        session_id = event_context_id(context) or task_id
        user_id = str(params.get("user_id") or "local")
        abort = self._abort.setdefault(task_id, asyncio.Event())
        try:
            runner = self.create_runner(context, root, event_queue=event_queue, abort_signal=abort)
        except BaseException:
            self._abort.pop(task_id, None)
            raise
        try:
            session = await ensure_session(runner, user_id, session_id)
            invocation_key = f"{INVOCATION_STATE_KEY_PREFIX}{task_id}"
            invocation_id = session.state.get(invocation_key)
            state_delta: dict[str, Any] | None = None
            new_message: types.Content | None
            if invocation_id:
                new_message = _resume_message(
                    session, invocation_id, self.get_provided_inputs(context)
                )
            else:
                inputs = {k: v for k, v in params.items() if k not in _REQUEST_PARAM_KEYS}
                self._validate_inputs(skill_id, inputs)
                if skill_id in self.long_running:
                    await self.declare_long_running(
                        context, event_queue, estimate_seconds=self.long_running[skill_id]
                    )
                invocation_id = new_invocation_context_id()
                state_delta = {SKILL_ID_STATE_KEY: skill_id, invocation_key: invocation_id}
                new_message = types.Content(
                    role="user", parts=[types.Part(text=json.dumps(inputs, default=str))]
                )

            last: Event | None = None
            paused = False
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                new_message=new_message,
                state_delta=state_delta,
                run_config=RunConfig(custom_metadata={"a2a_metadata": _a2a_metadata(context)}),
                abort_signal=abort,
            ):
                if event.author == "user" or event.partial:
                    continue
                paused = paused or bool(event.long_running_tool_ids)
                if event.output is not None or event_text(event):
                    last = event
            cancel = runner.plugin_manager.get_plugin("prometheus_cancel")
            summary = cancel.summary() if isinstance(cancel, CancelPlugin) else None
            if not paused:
                await commit_run_to_memory(runner, user_id, session_id)
        finally:
            self._abort.pop(task_id, None)
            await runner.close()

        if summary is not None:
            return {"status": "cancelled", "message": summary}
        if paused:
            return {"status": "input_required"}
        return _final_result(last)

    def _validate_inputs(self, skill_id: str, inputs: dict[str, Any]) -> None:
        """Raise ``ValueError`` when ``inputs`` do not match the skill's card ``inputSchema``."""
        skills = self.get_raw_agent_card().get("skills") or []
        schema = next(
            (
                skill.get("inputSchema")
                for skill in skills
                if isinstance(skill, dict) and skill.get("id") == skill_id
            ),
            None,
        )
        if not isinstance(schema, dict):
            return
        try:
            jsonschema.validate(inputs, schema)
        except jsonschema.ValidationError as exc:
            raise ValueError(f"Invalid params for skill {skill_id!r}: {exc.message}") from exc


def _a2a_metadata(context: RequestContext) -> dict[str, Any]:
    """Return the request's A2A message metadata without the user token or other secrets."""
    message = getattr(context, "message", None)
    if message is None:
        return {}
    metadata = MessageToDict(message.metadata)
    metadata.pop(USER_TOKEN_METADATA_KEY, None)
    redacted: dict[str, Any] = redact_secrets(metadata)
    return redacted


def _final_result(event: Event | None) -> dict[str, Any]:
    """Turn the run's last output or text event into the final result dict."""
    if event is None:
        return {"status": "success"}
    value: Any = event.output
    if value is None:
        text = event_text(event)
        try:
            value = json.loads(text)
        except ValueError:
            value = text
    if isinstance(value, dict):
        return value
    return {"status": "success", "result": value}


def _resume_message(
    session: Session, invocation_id: str, provided: dict[str, Any]
) -> types.Content | None:
    """Answer the invocation's pending long-running calls with ``provided``, if any.

    Returns ``None`` when nothing is pending or nothing was provided; the run then resumes
    where it stopped.
    """
    if not provided:
        return None
    calls: dict[str, types.FunctionCall] = {}
    answered: set[str] = set()
    for event in session.events:
        if event.invocation_id != invocation_id:
            continue
        pending_ids = event.long_running_tool_ids or set()
        for call in event.get_function_calls():
            if call.id and call.id in pending_ids:
                calls[call.id] = call
        answered.update(r.id for r in event.get_function_responses() if r.id)
    parts = []
    for call_id, call in calls.items():
        if call_id in answered:
            continue
        if call.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
            response: dict[str, Any] = {"confirmed": bool(provided.get("confirmed"))}
        else:
            response = {"result": provided.get(call.name or "", provided)}
        parts.append(
            types.Part(
                function_response=types.FunctionResponse(
                    id=call_id, name=call.name, response=response
                )
            )
        )
    return types.Content(role="user", parts=parts) if parts else None
