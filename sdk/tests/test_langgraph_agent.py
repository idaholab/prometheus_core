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

"""Tests for ``LangGraphPrometheusAgent``: approval interrupts and checkpoint resume."""

from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
from a2a.types import TaskState
from google.protobuf.json_format import MessageToDict
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver

from prometheus_api.langgraph import LangGraphPrometheusAgent
from prometheus_api.langgraph.model import PrometheusChatModel
from prometheus_api.llm_client import AsyncLLMClient, ChatResponse
from prometheus_api.llm_client.tools import ToolCall


class _ReactiveAsyncClient(AsyncLLMClient):
    """``AsyncLLMClient`` stand-in that calls each planned tool once, then answers with text.

    The reply depends only on the tool results already in the messages, so a run that starts
    over calls the first tool again instead of following a fixed script.
    """

    def __init__(self, plan: list[tuple[str, str]], answer: str = "Finished."):
        # No config: the fake never reaches a provider.
        self._plan = plan
        self._answer = answer

    async def chat(self, text_or_messages, model=None, trace_tags=None, **kwargs):  # type: ignore[override]
        answered = {m.get("tool_call_id") for m in text_or_messages if m.get("role") == "tool"}
        for name, call_id in self._plan:
            if call_id not in answered:
                call = ToolCall(id=call_id, name=name, arguments={})
                return ChatResponse("", "default", "resolved", None, {}, (call,), "tool_calls")
        return ChatResponse(self._answer, "default", "resolved", None, {}, (), "stop")

    async def aclose(self) -> None:
        return None


class _RecordingQueue:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def enqueue_event(self, event: Any) -> None:
        self.events.append(event)


def _context(task_id: str) -> Any:
    return SimpleNamespace(task_id=task_id, context_id=f"conv-{task_id}")


class _ScriptedAgent(LangGraphPrometheusAgent):
    """A LangGraph agent with fixed skill tools, a reactive model and no DeepLynx."""

    def __init__(
        self,
        tools: dict[str, list[BaseTool]],
        plan: list[tuple[str, str]],
        saver: InMemorySaver,
        agent_card_path: str | None = None,
    ):
        super().__init__(agent_name="Scripted Agent", agent_card_path=agent_card_path)
        self._tools = tools
        self._plan = plan
        self.checkpoint_saver = saver

    def skill_tools(self) -> dict[str, list[BaseTool]]:
        return self._tools

    def llm_client(self, context, **kwargs):
        return _ReactiveAsyncClient(self._plan)

    async def storage_config(self):
        return None


class _ApprovalAgent(_ScriptedAgent):
    approval_tools = frozenset({"approve"})


def _approval_agent(runs: Counter[str], saver: InMemorySaver) -> _ApprovalAgent:
    @tool
    def approve() -> str:
        """Release the pending change."""
        runs["approve"] += 1
        return json.dumps({"status": "success", "released": True})

    agent = _ApprovalAgent({"release": [approve]}, [("approve", "call_approve")], saver)
    agent.agent_card_dict = {"skills": [{"id": "release", "name": "Release"}]}
    agent.validate_skill_tools()
    return agent


async def test_approval_tool_pauses_then_runs_once_on_approve_and_never_on_reject():
    """Covers REQ-017-04."""
    runs: Counter[str] = Counter()
    saver = InMemorySaver()
    agent = _approval_agent(runs, saver)
    params = {"skill_id": "release", "change": "v2"}

    queue = _RecordingQueue()
    first = await agent._execute(dict(params), _context("task-approve"), queue)

    assert first == {"status": "input_required"}
    assert runs["approve"] == 0, "REQ-017-04: the tool pauses before it runs"
    (event,) = queue.events
    assert event.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    payload = MessageToDict(event.status.message.parts[0].data)
    (missing,) = payload["missing_inputs"]
    assert missing["name"] == "approved"
    assert missing["type"] == "boolean"

    resumed = await agent._execute(
        {**params, "approved": True}, _context("task-approve"), _RecordingQueue()
    )

    assert resumed == {"status": "success", "released": True}
    assert runs["approve"] == 1, "REQ-017-04: an approved tool runs once on the same task"

    paused = await agent._execute(dict(params), _context("task-reject"), _RecordingQueue())
    assert paused == {"status": "input_required"}
    rejected = await agent._execute(
        {**params, "approved": False}, _context("task-reject"), _RecordingQueue()
    )

    assert rejected["status"] == "error", "REQ-017-04: a rejected call returns an error result"
    assert "Rejected by the user." in rejected["message"]
    assert runs["approve"] == 1, "REQ-017-04: a rejected tool never runs"
    model = PrometheusChatModel(client=_ReactiveAsyncClient([]))
    graph = agent.build_graph("release", model, saver)
    state = await graph.aget_state({"configurable": {"thread_id": "task-reject"}})
    tool_messages = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages[-1].name == "approve"
    assert "Rejected by the user." in tool_messages[-1].content


def _pipeline_tools(runs: Counter[str]) -> dict[str, list[BaseTool]]:
    @tool
    def one() -> str:
        """Run the first step."""
        runs["one"] += 1
        return "one done"

    @tool
    def two() -> str:
        """Run the second step; it fails on its first run."""
        runs["two"] += 1
        if runs["two"] == 1:
            raise RuntimeError("worker lost")
        return json.dumps({"status": "success", "steps": 2})

    return {"pipeline": [one, two]}


PIPELINE_PLAN = [("one", "call_one"), ("two", "call_two")]


async def test_fresh_agent_on_shared_saver_resumes_task_without_rerunning_finished_tool():
    """Covers REQ-017-06."""
    runs: Counter[str] = Counter()
    saver = InMemorySaver()
    card = {"skills": [{"id": "pipeline", "name": "Pipeline"}]}
    params = {"skill_id": "pipeline"}

    first = _ScriptedAgent(_pipeline_tools(runs), PIPELINE_PLAN, saver)
    first.agent_card_dict = card
    with pytest.raises(RuntimeError, match="worker lost"):
        await first._execute(dict(params), _context("task-resume"), _RecordingQueue())
    assert runs == Counter({"one": 1, "two": 1})

    fresh = _ScriptedAgent(_pipeline_tools(runs), PIPELINE_PLAN, saver)
    fresh.agent_card_dict = card
    result = await fresh._execute(dict(params), _context("task-resume"), _RecordingQueue())

    assert result == {"status": "success", "steps": 2}
    assert runs["one"] == 1, "REQ-017-06: a finished tool does not run again on resume"
    assert runs["two"] == 2, "REQ-017-06: the unfinished tool runs again on resume"


@pytest.mark.parametrize(
    "card_skills",
    [
        pytest.param(["pipeline", "orphan"], id="card-skill-without-tools"),
        pytest.param([], id="tool-list-without-card-skill"),
    ],
)
def test_load_agent_card_rejects_unmapped_skill(tmp_path, monkeypatch, card_skills):
    """Covers REQ-017-06."""
    monkeypatch.setenv("EXTERNAL_AGENT_URL", "http://scripted-agent:8000")
    card_path = tmp_path / "agent_card.json"
    card = {
        "name": "Scripted Agent",
        "description": "LangGraph test agent",
        "version": "1.0.0",
        "capabilities": {"streaming": False},
        "skills": [
            {"id": skill_id, "name": skill_id, "description": f"Run {skill_id}."}
            for skill_id in card_skills
        ],
    }
    card_path.write_text(json.dumps(card), encoding="utf-8")
    agent = _ScriptedAgent(
        _pipeline_tools(Counter()), PIPELINE_PLAN, InMemorySaver(), str(card_path)
    )

    with pytest.raises(ValueError, match="without"):
        agent.load_agent_card()
