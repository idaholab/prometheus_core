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

"""A turn's ``new_artifacts`` are the artifacts that turn produced, not a catalog diff.

Artifacts registered by a turn running meanwhile (a backgrounded one, or the one
the user sent after it) share the conversation catalog. They must not appear in
this turn's ``new_artifacts``, or the UI renders them under two replies
(Prometheus Artifact Contract, "Frontend viewer ownership").
"""

import asyncio
from types import SimpleNamespace

import pytest

import orchestrator.service as service_mod
import task_graph
from orchestrator import task_tracking
from prometheus_api.agent import ArtifactReference
from tests.test_task_graph import _FakeRedis

CONV = "conv-turn"


class _Registry:
    """In-memory stand-in for the conversation artifact registry."""

    def __init__(self, *ids):
        self.refs = {}
        for i, artifact_id in enumerate(ids):
            self.add(artifact_id, created_at=f"2026-09-30T10:0{i}:00+00:00")

    def add(self, artifact_id, created_at="2026-09-30T11:00:00+00:00"):
        self.refs[artifact_id] = ArtifactReference(
            artifact_id=artifact_id,
            conversation_id=CONV,
            name=f"{artifact_id}.json",
            description="",
            json_body={"id": artifact_id},
            created_at=created_at,
        )

    def register(self, reference):
        self.refs[reference.artifact_id] = reference
        return reference

    def list(self, conversation_id, limit=None):
        return sorted(self.refs.values(), key=lambda r: r.created_at, reverse=True)

    def resolve_by_id(self, conversation_id, artifact_id):
        return self.refs.get(artifact_id)


class _Queue:
    async def enqueue_event(self, event):
        pass


@pytest.fixture()
def orchestrator(monkeypatch):
    monkeypatch.setattr(task_graph, "_client", lambda: _FakeRedis())
    task_tracking._turn.set(None)
    task_tracking._nested_parent.set(None)
    monkeypatch.delenv("PROMETHEUS_BACKGROUND_DEADLINE_SECONDS", raising=False)
    monkeypatch.setattr(service_mod.runtime, "_tools_cache", [object()])
    monkeypatch.setattr(service_mod.runtime, "store_status_update", lambda *a, **k: None)
    monkeypatch.setattr(service_mod, "get_conversation", lambda conversation_id: None)

    recorded = []
    monkeypatch.setattr(service_mod, "record_turn_artifacts", lambda *args: recorded.append(args))

    async def no_upload(self, *args, **kwargs):
        return []

    monkeypatch.setattr(service_mod.OrchestratorAgent, "_handle_uploaded_files", no_upload)

    agent = service_mod.OrchestratorAgent()
    agent.artifact_registry = _Registry("a1")  # an older turn's artifact
    agent.recorded = recorded
    return agent


def _run(agent, query="make a plot"):
    return asyncio.run(
        agent._execute({"query": query, "conversation_id": CONV}, SimpleNamespace(context_id=CONV), _Queue())
    )


def _ids(refs):
    return [r["artifact_id"] for r in refs]


# A turn can publish outputs and then pause at a form or an approval gate; what it
# produced is reported the same way as for a turn that finishes.
_FINAL_OR_PAUSED = {
    "completed": {"report": "plotted"},
    "needs_info": {"message": "Gate 2: approve?", "followup_questions": [{"field": "f", "question": "Q?"}]},
    "plan_ready": {"message": "Plan ready", "plan": {"steps": []}},
}


@pytest.mark.parametrize("status", list(_FINAL_OR_PAUSED))
def test_new_artifacts_are_the_ids_the_turn_produced(orchestrator, monkeypatch, status):
    turn_ids = []

    async def fake_chat(request):
        orchestrator.artifact_registry.add("a2")
        task_tracking.record_produced_artifacts(["a2"])  # what the dispatch reported
        orchestrator.artifact_registry.add("a3")  # registered by a turn running meanwhile
        turn_ids.append(task_tracking.current_turn_id())
        return service_mod.ConversationResponse(conversation_id=CONV, status=status, **_FINAL_OR_PAUSED[status])

    monkeypatch.setattr(service_mod, "chat", fake_chat)

    payload = _run(orchestrator)

    assert _ids(payload["new_artifacts"]) == ["a2"]
    assert sorted(_ids(payload["artifacts"])) == ["a1", "a2", "a3"]
    assert orchestrator.recorded == [(CONV, turn_ids[0], ["a2"])]


def test_the_turns_uploads_count_as_produced(orchestrator, monkeypatch):
    async def upload(self, request_payload, conversation_id, context, event_queue):
        orchestrator.artifact_registry.add("up1")
        return ["up1"]

    async def fake_chat(request):
        return service_mod.ConversationResponse(conversation_id=CONV, status="completed", report="ok")

    monkeypatch.setattr(service_mod.OrchestratorAgent, "_handle_uploaded_files", upload)
    monkeypatch.setattr(service_mod, "chat", fake_chat)

    payload = _run(orchestrator)

    assert _ids(payload["new_artifacts"]) == ["up1"]


def test_an_echoed_older_artifact_is_not_new(orchestrator, monkeypatch):
    # The response echoes a1 in tool_results; re-ingest registers it again, but
    # this turn did not produce it.
    async def fake_chat(request):
        return service_mod.ConversationResponse(
            conversation_id=CONV,
            status="completed",
            report="reused",
            tool_results={"skill": {"result": {"artifacts": [orchestrator.artifact_registry.refs["a1"].to_dict()]}}},
        )

    monkeypatch.setattr(service_mod, "chat", fake_chat)

    payload = _run(orchestrator)

    assert payload["new_artifacts"] == []
    assert orchestrator.recorded == []


def test_an_artifact_only_in_the_response_json_is_new(orchestrator, monkeypatch):
    # Not a native A2A artifact, so no dispatch reported it, but this response is
    # the one that brought it into the catalog.
    async def fake_chat(request):
        return service_mod.ConversationResponse(
            conversation_id=CONV,
            status="completed",
            report="made",
            tool_results={
                "skill": {
                    "result": {"artifacts": [{"artifact_id": "inline", "name": "inline.json", "json_body": {"k": 1}}]}
                }
            },
        )

    monkeypatch.setattr(service_mod, "chat", fake_chat)

    payload = _run(orchestrator)

    assert _ids(payload["new_artifacts"]) == ["inline"]
    assert orchestrator.recorded[0][2] == ["inline"]


def test_a_slash_command_has_no_turn_and_records_nothing(orchestrator, monkeypatch):
    seen = {}

    async def fake_chat(request):
        orchestrator.artifact_registry.add("x")
        task_tracking.record_produced_artifacts(["x"])  # lands only if a turn began
        seen["turn"] = task_tracking.current_turn()
        return service_mod.ConversationResponse(conversation_id=CONV, status="answer", response_text="listed")

    monkeypatch.setattr(service_mod, "chat", fake_chat)

    payload = _run(orchestrator, query="/artifacts")

    assert seen["turn"] is None
    assert payload["new_artifacts"] == []
    assert orchestrator.recorded == []


def test_the_placeholder_shows_nothing_and_the_finisher_owns_the_turns_artifacts(orchestrator, monkeypatch):
    spawned = {}

    async def fake_chat(request):
        orchestrator.artifact_registry.add("early")
        task_tracking.record_produced_artifacts(["early"])  # produced before the detach
        task_tracking.request_background()
        await asyncio.Event().wait()  # never completes; fake_spawn cancels the task

    def fake_spawn(self, chat_task, conversation_id, root_id, turn):
        spawned["turn"] = turn
        chat_task.cancel()

    monkeypatch.setattr(service_mod, "chat", fake_chat)
    monkeypatch.setattr(service_mod.OrchestratorAgent, "_spawn_background_finisher", fake_spawn)

    placeholder = _run(orchestrator, query="run a long simulation")

    assert placeholder["status"] == "backgrounded"
    assert placeholder["new_artifacts"] == []
    assert orchestrator.recorded == []

    # What the finisher's build_payload returns when the detached turn completes.
    turn = spawned["turn"]
    orchestrator.artifact_registry.add("meanwhile")  # the next turn's artifact
    done = orchestrator._response_payload_with_artifacts(
        CONV, service_mod.ConversationResponse(conversation_id=CONV, status="completed", report="late"), turn
    )
    assert _ids(done["new_artifacts"]) == ["early"]
    assert orchestrator.recorded == [(CONV, turn.turn_id, ["early"])]
