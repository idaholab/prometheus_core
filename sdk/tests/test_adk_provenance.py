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

"""Tests for the ADK provenance plugin.

The run uses in-memory ADK services and a stub model that calls one tool, so no real LLM is
involved. DeepLynx is a recording fake of the ``AsyncStorageClient`` surface the plugin uses.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.long_running_tool import LongRunningFunctionTool
from google.genai import types

from prometheus_api.adk.memory import EXECUTION_STATUS_STATE_KEY
from prometheus_api.adk.plugins import provenance
from prometheus_api.adk.plugins.provenance import (
    CHILD_OF,
    INPUT_TO,
    PARENT_EXECUTION_RECORD_METADATA_KEY,
    ProvenancePlugin,
)
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.item import Item, ItemUpdate
from prometheus_api.storage_client.models.relationship import RelationshipCreate

APP = "provenance-test"
USER = "user-1"
TOOL = "inspect_tool"
RECORD_ID = 11
PARENT_ID = 3
ARTIFACT_ID = 7
PARAMS = {"cad_artifact_id": f"deeplynx://org/1/project/2/items/{ARTIFACT_ID}"}


class _StubLlm(BaseLlm):
    """Calls the tool once, then answers with text after the tool response."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            parts = [types.Part(text="done")]
        else:
            parts = [types.Part(function_call=types.FunctionCall(name=TOOL, args={"n": 1}))]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


class _RecordAgent:
    """The minimal agent surface the plugin reads: the PR #198 execution record ID."""

    execution_record_id = RECORD_ID


class _Recorder:
    """Records each DeepLynx write and read the plugin makes."""

    def __init__(self) -> None:
        self.edges: list[tuple[int, int, str]] = []
        self.gets: list[int] = []
        self.updates: list[tuple[int, ItemUpdate]] = []
        self.creates: list[Any] = []
        self.record_properties: dict[str, Any] = {"agent_name": "provenance_agent"}


class _FakeRelationships:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def bulk_create(self, relationships: list[RelationshipCreate]) -> list[Any]:
        for rel in relationships:
            self._recorder.edges.append((rel.from_item_id, rel.to_item_id, rel.relationship_type))
        return []

    async def get_item_relationships(self, item_id: int) -> list[Any]:
        return []


class _FakeItems:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def get(self, item_id: int) -> Item:
        self._recorder.gets.append(item_id)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return Item(
            id=item_id,
            name=f"Execution record {item_id}",
            properties=dict(self._recorder.record_properties),
            created_at=now,
            updated_at=now,
        )

    async def update(self, item_id: int, update: ItemUpdate) -> None:
        self._recorder.updates.append((item_id, update))

    async def create(self, item: Any) -> None:
        self._recorder.creates.append(item)


def _fake_client_class(recorder: _Recorder) -> type:
    class _FakeClient:
        """The ``AsyncStorageClient`` surface the plugin uses."""

        def __init__(self, config: ConnectionConfig) -> None:
            self.config = config
            self.items = _FakeItems(recorder)
            self.relationships = _FakeRelationships(recorder)

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    return _FakeClient


@pytest.mark.parametrize(
    ("tool_fails", "expected_status"),
    [
        pytest.param(False, "succeeded", id="tool-succeeds-closes-succeeded"),
        pytest.param(True, "failed", id="tool-raises-closes-failed"),
    ],
)
async def test_provenance_edges_and_close(
    monkeypatch: pytest.MonkeyPatch, tool_fails: bool, expected_status: str
) -> None:
    """Covers REQ-016-03."""
    recorder = _Recorder()
    config_users: list[str] = []

    async def fake_deeplynx_config(agent: Any, user_id: str) -> ConnectionConfig:
        config_users.append(user_id)
        return ConnectionConfig(organization_id=1, project_id=2, jwt_token="t")

    monkeypatch.setattr(provenance, "deeplynx_config", fake_deeplynx_config)
    monkeypatch.setattr(provenance, "AsyncStorageClient", _fake_client_class(recorder))

    def inspect_tool(n: int) -> dict[str, Any]:
        """Inspect the CAD artifact."""
        if tool_fails:
            raise RuntimeError("inspection failed")
        return {"ok": n}

    sessions = InMemorySessionService()
    app = App(
        name=APP,
        root_agent=LlmAgent(name="provenance_agent", model=_StubLlm(), tools=[inspect_tool]),
        plugins=[ProvenancePlugin(_RecordAgent())],  # type: ignore[arg-type]
    )
    runner = Runner(app=app, session_service=sessions)
    session = await sessions.create_session(app_name=APP, user_id=USER)
    message = types.Content(role="user", parts=[types.Part(text=json.dumps(PARAMS))])
    run_config = RunConfig(custom_metadata={PARENT_EXECUTION_RECORD_METADATA_KEY: PARENT_ID})

    async def run() -> None:
        async for _ in runner.run_async(
            user_id=USER, session_id=session.id, new_message=message, run_config=run_config
        ):
            pass

    if tool_fails:
        # ADK 2.13.0 re-raises a tool error that no on_tool_error callback answers; the
        # runner calls on_run_error_callback before the error leaves run_async.
        with pytest.raises(RuntimeError, match="inspection failed"):
            await run()
    else:
        await run()

    assert recorder.edges == [
        (ARTIFACT_ID, RECORD_ID, INPUT_TO),
        (RECORD_ID, PARENT_ID, CHILD_OF),
    ]
    assert recorder.creates == [], "the plugin created its own execution record"
    assert len(recorder.updates) == 1, "the execution record was not closed exactly once"
    updated_id, update = recorder.updates[0]
    assert updated_id == RECORD_ID
    properties = update.properties or {}
    assert properties["status"] == expected_status
    assert properties["agent_name"] == "provenance_agent"
    assert datetime.fromisoformat(properties["ended_at"]).tzinfo is not None
    assert set(properties["token_usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    if tool_fails:
        assert properties["tool_calls"] == []
    else:
        assert [call["tool"] for call in properties["tool_calls"]] == [TOOL]
    assert set(config_users) == {USER}

    stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=session.id)
    assert stored is not None
    assert stored.state[EXECUTION_STATUS_STATE_KEY] == expected_status


WAIT_TOOL = "wait_tool"
CALL_ID = "c1"


class _PausingLlm(BaseLlm):
    """Calls the long-running tool for the params message, else answers with text."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any((part.text or "") == json.dumps(PARAMS) for part in last.parts or []):
            call = types.FunctionCall(id=CALL_ID, name=WAIT_TOOL, args={})
            parts = [types.Part(function_call=call)]
        else:
            parts = [types.Part(text="done")]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def _status_deltas(events: list[Any]) -> list[Any]:
    return [
        event.actions.state_delta[EXECUTION_STATUS_STATE_KEY]
        for event in events
        if EXECUTION_STATUS_STATE_KEY in (event.actions.state_delta or {})
    ]


class _PauseHarness:
    """Runs turns of one session, each on a new ProvenancePlugin as a new request would."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.recorder = _Recorder()
        self.sessions = InMemorySessionService()
        self.on_wait: Any = None

        async def fake_deeplynx_config(agent: Any, user_id: str) -> ConnectionConfig:
            return ConnectionConfig(organization_id=1, project_id=2, jwt_token="t")

        monkeypatch.setattr(provenance, "deeplynx_config", fake_deeplynx_config)
        monkeypatch.setattr(provenance, "AsyncStorageClient", _fake_client_class(self.recorder))

    async def start(self) -> str:
        session = await self.sessions.create_session(app_name=APP, user_id=USER)
        return session.id

    async def turn(self, session_id: str, message: types.Content) -> ProvenancePlugin:
        plugin = ProvenancePlugin(_RecordAgent())  # type: ignore[arg-type]

        def wait_tool() -> None:
            """Wait for the user's answer."""
            if self.on_wait is not None:
                self.on_wait(plugin)

        app = App(
            name=APP,
            root_agent=LlmAgent(
                name="provenance_agent",
                model=_PausingLlm(),
                tools=[LongRunningFunctionTool(wait_tool)],
            ),
            plugins=[plugin],
        )
        runner = Runner(app=app, session_service=self.sessions)
        async for _ in runner.run_async(user_id=USER, session_id=session_id, new_message=message):
            pass
        return plugin

    async def events(self, session_id: str) -> list[Any]:
        stored = await self.sessions.get_session(app_name=APP, user_id=USER, session_id=session_id)
        assert stored is not None
        return list(stored.events)


def _params_message() -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=json.dumps(PARAMS))])


def _answer_message() -> types.Content:
    response = types.FunctionResponse(id=CALL_ID, name=WAIT_TOOL, response={"answer": "yes"})
    return types.Content(role="user", parts=[types.Part(function_response=response)])


async def test_provenance_paused_run_closes_once_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers REQ-016-03: a paused run leaves the record open; the resumed run closes it once."""
    harness = _PauseHarness(monkeypatch)
    session_id = await harness.start()

    await harness.turn(session_id, _params_message())

    paused = await harness.events(session_id)
    assert any(CALL_ID in (event.long_running_tool_ids or set()) for event in paused)
    assert harness.recorder.updates == [], "the paused run closed its execution record"
    assert _status_deltas(paused) == []

    await harness.turn(session_id, _answer_message())

    assert len(harness.recorder.updates) == 1, "the resumed run did not close the record once"
    updated_id, update = harness.recorder.updates[0]
    assert updated_id == RECORD_ID
    assert (update.properties or {})["status"] == "succeeded"
    assert _status_deltas(await harness.events(session_id)) == ["succeeded"]
    assert harness.recorder.creates == []

    # A later request of the same task finds the record closed and leaves it as it is.
    harness.recorder.record_properties = dict(update.properties or {})
    await harness.turn(
        session_id, types.Content(role="user", parts=[types.Part(text="anything else?")])
    )

    assert len(harness.recorder.updates) == 1, "an already closed record was updated again"


async def test_provenance_cancel_while_paused_closes_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers REQ-016-03: a cancel while a long-running call is pending closes the record."""
    harness = _PauseHarness(monkeypatch)
    harness.on_wait = lambda plugin: plugin.mark_cancelled()
    session_id = await harness.start()

    await harness.turn(session_id, _params_message())

    events = await harness.events(session_id)
    assert any(CALL_ID in (event.long_running_tool_ids or set()) for event in events)
    assert len(harness.recorder.updates) == 1, "the cancelled paused run did not close once"
    updated_id, update = harness.recorder.updates[0]
    assert updated_id == RECORD_ID
    assert (update.properties or {})["status"] == "cancelled"
    assert _status_deltas(events) == ["cancelled"]
