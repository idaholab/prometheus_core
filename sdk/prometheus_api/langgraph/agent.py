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
"""``LangGraphPrometheusAgent``: a ``PrometheusAgent`` whose skills run as LangGraph graphs.

Each card skill maps to the tools of one ``langchain.agents.create_agent`` graph in
``skill_tools()``. A request runs the graph of its ``skill_id`` with the A2A task ID as the
checkpoint ``thread_id`` (REQ-017-06), so a later request of the same task continues the
same thread:

- a new task sends the params JSON as the first user message;
- a task paused on an approval interrupt resumes with ``Command(resume=...)``, approved when
  ``params["approved"]`` is ``True`` and rejected otherwise (REQ-017-04);
- a task with an unfinished checkpoint and no pending interrupt continues where it stopped.

The checkpointer is an ``AsyncPostgresSaver`` on ``LANGGRAPH_CHECKPOINT_DB_URL``, opened once
per process and closed when the app shuts down; without that setting it is an in-memory
saver that cannot resume after a restart.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import AgentCard
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ..agent.base import MissingInput, PrometheusAgent
from ..agent.events import context_task_id
from ..credentials import CredentialError
from ..storage_client.connection import ConnectionConfig
from .artifacts import PrometheusContext
from .middleware import ProvenanceMiddleware, approval, summarization
from .model import PrometheusChatModel

logger = logging.getLogger(__name__)

REJECTED_MESSAGE = "Rejected by the user."

# Keys the executor adds to the params; they are not skill inputs.
_REQUEST_PARAM_KEYS = ("skill_id", "user_id")


class LangGraphPrometheusAgent(PrometheusAgent):
    """A Prometheus agent whose card skills run as ``create_agent`` graphs.

    Set on a subclass:

    - ``skill_tools()``: card skill ID -> the tools of its graph.
    - ``system_prompt(skill_id)``: the system prompt of that graph.
    - ``model_alias``: the semantic LLM alias of the graph model.
    - ``approval_tools``: tool names that need approval besides the tools of the card skills
      with ``requires_approval: true``.

    Set ``checkpoint_saver`` (on the instance, before the first request) to use a given
    saver instead of the one from ``LANGGRAPH_CHECKPOINT_DB_URL``; the agent never closes an
    injected saver.
    """

    model_alias: str = "default"
    approval_tools: frozenset[str] = frozenset()
    checkpoint_saver: BaseCheckpointSaver | None = None

    def __init__(self, agent_name: str = "Agent", agent_card_path: str | None = None):
        super().__init__(agent_name=agent_name, agent_card_path=agent_card_path)
        self._checkpoint_lock = asyncio.Lock()
        self._checkpoint_stack: AsyncExitStack | None = None

    def skill_tools(self) -> dict[str, list[BaseTool]]:
        """Return the tools of each card skill. Override in a subclass."""
        raise NotImplementedError("Override skill_tools() in your LangGraph agent subclass")

    def system_prompt(self, skill_id: str) -> str:
        """Return the system prompt of the graph of *skill_id*."""
        return (
            "Call the tool of this skill with the parameters of the user message, "
            "then answer with one sentence."
        )

    def load_agent_card(self) -> AgentCard:
        """Load the agent card and check that its skills and ``skill_tools()`` match."""
        agent_card = super().load_agent_card()
        self.validate_skill_tools()
        return agent_card

    def validate_skill_tools(self) -> None:
        """Raise ``ValueError`` when a card skill has no tools or a tool list has no skill."""
        skills = self.get_raw_agent_card().get("skills") or []
        skill_ids = {str(skill.get("id")) for skill in skills if isinstance(skill, dict)}
        tools = self.skill_tools()
        no_tools = sorted(skill_id for skill_id in skill_ids if not tools.get(skill_id))
        no_skill = sorted(set(tools) - skill_ids)
        if no_tools or no_skill:
            raise ValueError(
                f"{self.agent_name}: card skills without tools: {no_tools}; "
                f"tool lists without a card skill: {no_skill}"
            )

    async def checkpointer(self) -> BaseCheckpointSaver:
        """Return the process checkpointer, opening it on first use."""
        async with self._checkpoint_lock:
            if self.checkpoint_saver is not None:
                return self.checkpoint_saver
            url = (os.getenv("LANGGRAPH_CHECKPOINT_DB_URL") or "").strip()
            if not url:
                logger.warning(
                    "LANGGRAPH_CHECKPOINT_DB_URL is not set; %s keeps checkpoints in memory "
                    "and cannot resume a task after a restart",
                    self.agent_name,
                )
                self.checkpoint_saver = InMemorySaver()
                return self.checkpoint_saver
            stack = AsyncExitStack()
            try:
                saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(url))
                await saver.setup()
            except BaseException:
                await stack.aclose()
                raise
            self._checkpoint_stack = stack
            self.checkpoint_saver = saver
            return saver

    async def close_checkpointer(self) -> None:
        """Close the checkpointer that ``checkpointer()`` opened, if any."""
        async with self._checkpoint_lock:
            stack, self._checkpoint_stack = self._checkpoint_stack, None
            if stack is not None:
                self.checkpoint_saver = None
                await stack.aclose()

    @asynccontextmanager
    async def lifespan(self, app) -> AsyncIterator[None]:
        """Open the checkpointer at startup and close it on shutdown."""
        async with super().lifespan(app):
            await self.checkpointer()
            try:
                yield
            finally:
                await self.close_checkpointer()

    def build_graph(
        self,
        skill_id: str,
        model: PrometheusChatModel,
        checkpointer: BaseCheckpointSaver,
    ) -> CompiledStateGraph[Any, PrometheusContext, Any, Any]:
        """Build the ``create_agent`` graph of *skill_id*."""
        tools = self.skill_tools()[skill_id]
        card_skills = self.get_raw_agent_card().get("skills") or []
        needs_approval = any(
            isinstance(skill, dict)
            and str(skill.get("id")) == skill_id
            and skill.get("requires_approval") is True
            for skill in card_skills
        )
        extra_tools = set(self.approval_tools)
        if needs_approval:
            extra_tools.update(tool.name for tool in tools)
        middleware: list[AgentMiddleware[Any, Any]] = [
            m
            for m in (
                summarization(model.client),
                approval(card_skills, extra_tools),
                ProvenanceMiddleware(),
            )
            if m
        ]
        return create_agent(
            model,
            tools=tools,
            system_prompt=self.system_prompt(skill_id),
            middleware=middleware,
            context_schema=PrometheusContext,
            checkpointer=checkpointer,
        )

    async def storage_config(self) -> ConnectionConfig | None:
        """Return the DeepLynx connection of the current user, or ``None`` if unconfigured."""
        try:
            return ConnectionConfig.from_credential(await self.get_credential("deeplynx"))
        except (CredentialError, RuntimeError, ValueError) as exc:
            logger.info("DeepLynx is not configured for %s: %s", self.agent_name, exc)
            return None

    async def _execute(
        self,
        params: dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> dict[str, Any]:
        """Run, resume or continue the graph of ``params["skill_id"]``."""
        skill_id = str(params.get("skill_id") or "")
        if skill_id not in self.skill_tools():
            raise ValueError(f"{self.agent_name} has no tools for skill {skill_id!r}")
        thread_id = context_task_id(context)
        config: Any = {"configurable": {"thread_id": thread_id}}
        run_context = PrometheusContext(
            agent=self,
            request=context,
            event_queue=event_queue,
            thread_id=thread_id,
            execution_record_id=self.execution_record_id,
            storage=await self.storage_config(),
        )
        async with self.llm_client(context) as client:
            model = PrometheusChatModel(alias=self.model_alias, client=client)
            graph = self.build_graph(skill_id, model, await self.checkpointer())
            state = await graph.aget_state(config)
            run_input: Any
            if state.interrupts and "approved" in params:
                run_input = _resume_command(state.interrupts[0].value, params["approved"])
            elif state.next:
                run_input = None
            else:
                inputs = {k: v for k, v in params.items() if k not in _REQUEST_PARAM_KEYS}
                run_input = {"messages": [HumanMessage(json.dumps(inputs, default=str))]}
            result = await graph.ainvoke(run_input, config, context=run_context, durability="sync")

        interrupts = result.get("__interrupt__")
        if interrupts:
            await self._request_approval(context, event_queue, interrupts[0].value)
            return {"status": "input_required"}
        return _final_result(result.get("messages") or [])

    async def _request_approval(
        self, context: RequestContext, event_queue: EventQueue, request: dict[str, Any]
    ) -> None:
        """Send the final ``INPUT_REQUIRED`` that asks for the boolean ``approved``."""
        actions = "; ".join(
            f"{action['name']} with {json.dumps(action.get('args') or {}, default=str)}"
            for action in request.get("action_requests") or []
        )
        await self.send_input_required(
            context,
            event_queue,
            missing_inputs=[
                MissingInput(
                    name="approved",
                    description="Whether the pending tool call may run.",
                    user_prompt=f"Approve the call of {actions}?",
                    type="boolean",
                )
            ],
            hint="This step needs your approval before it runs.",
        )


def _resume_command(request: dict[str, Any], approved: Any) -> Command[Any]:
    """Answer every pending action of an approval interrupt with one decision."""
    decision: dict[str, Any] = (
        {"type": "approve"} if approved is True else {"type": "reject", "message": REJECTED_MESSAGE}
    )
    count = len(request.get("action_requests") or []) or 1
    return Command(resume={"decisions": [dict(decision) for _ in range(count)]})


def _final_result(messages: list[Any]) -> dict[str, Any]:
    """Return the last tool error or result dict, else the last AI text as a success result.

    A rejected approval and a failed tool call both leave an error ``ToolMessage``.
    """
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            if message.status == "error":
                return {"status": "error", "message": message.text}
            if isinstance(message.content, str):
                try:
                    value = json.loads(message.content)
                except ValueError:
                    break
                if isinstance(value, dict):
                    return value
            break
    text = next((m.text for m in reversed(messages) if isinstance(m, AIMessage) and m.text), "")
    return {"status": "success", "result": text}
