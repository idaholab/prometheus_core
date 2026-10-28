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

"""Tests for the ADK ``retrieve`` tool.

The run uses in-memory ADK services, a stub model that calls ``retrieve`` once, and a fake
DeepLynx client whose ``advanced_query`` returns one page of two items, so no real LLM or
DeepLynx is involved.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from prometheus_api.adk import retrieval
from prometheus_api.adk.retrieval import DeepLynxRetrievalBroker, retrieve_tool
from prometheus_api.storage_client.connection import ConnectionConfig
from prometheus_api.storage_client.models.item import Item
from prometheus_api.storage_client.models.pagination import Page, PageInfo

APP = "retrieval-test"
USER = "user-1"
QUERY = "pump seal failures"
ORG = 7
PROJECT = 42


class _StubLlm(BaseLlm):
    """Calls ``retrieve`` once with QUERY, then answers with text after the tool response."""

    model: str = "stub"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        if any(part.function_response for part in last.parts or []):
            parts = [types.Part(text="done")]
        else:
            call = types.FunctionCall(name="retrieve", args={"query": QUERY, "limit": 2})
            parts = [types.Part(function_call=call)]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def _item(item_id: int, name: str, version: str) -> Item:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Item(
        id=item_id,
        name=name,
        description=f"snippet of {name}",
        properties={"version": version},
        created_at=now,
        updated_at=now,
    )


class _FakeSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def advanced_query(self, **kwargs: Any) -> Page[Item]:
        self.calls.append(kwargs)
        items = [_item(101, "Pump A report", "3"), _item(202, "Seal B report", "5")]
        info = PageInfo(
            page_number=1, page_size=2, total_count=2, has_next=False, has_previous=False
        )
        return Page(items=items, page_info=info)


class _FakeClient:
    """The ``AsyncStorageClient`` surface the broker uses: a context manager with ``search``."""

    search = _FakeSearch()

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_retrieve_tool_returns_cited_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers REQ-016-09."""
    config_users: list[str] = []

    async def fake_deeplynx_config(agent: Any, user_id: str) -> ConnectionConfig:
        config_users.append(user_id)
        return ConnectionConfig(organization_id=ORG, project_id=PROJECT, jwt_token="t")

    search = _FakeSearch()
    monkeypatch.setattr(_FakeClient, "search", search)
    monkeypatch.setattr(retrieval, "deeplynx_config", fake_deeplynx_config)
    monkeypatch.setattr(retrieval, "AsyncStorageClient", _FakeClient)

    tool = retrieve_tool(DeepLynxRetrievalBroker(agent=object()))  # type: ignore[arg-type]
    assert tool.name == "retrieve"

    sessions = InMemorySessionService()
    app = App(
        name=APP,
        root_agent=LlmAgent(name="retrieval_agent", model=_StubLlm(), tools=[tool]),
    )
    runner = Runner(app=app, session_service=sessions)
    session = await sessions.create_session(app_name=APP, user_id=USER)

    events = [
        event
        async for event in runner.run_async(
            user_id=USER,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="search")]),
        )
    ]

    # The query reached DeepLynx text search, as the calling user, in the configured project.
    assert config_users == [USER]
    assert search.calls == [
        {"filters": [], "project_ids": [PROJECT], "text_search": QUERY, "page_size": 2}
    ]

    responses = [r for event in events for r in event.get_function_responses()]
    assert len(responses) == 1 and responses[0].name == "retrieve"
    response = responses[0].response
    assert response is not None
    chunks = response["result"]

    assert len(chunks) == 2
    assert [c["uri"] for c in chunks] == [
        f"deeplynx://organizations/{ORG}/projects/{PROJECT}/items/101",
        f"deeplynx://organizations/{ORG}/projects/{PROJECT}/items/202",
    ], "each chunk must carry its deeplynx:// URI, not only the snippet"
    assert [c["item_id"] for c in chunks] == [101, 202]
    assert [c["score"] for c in chunks] == [1, 2]
    assert [c["version"] for c in chunks] == ["3", "5"]
    assert [c["snippet"] for c in chunks] == [
        "snippet of Pump A report",
        "snippet of Seal B report",
    ]
    assert all(c["source"] == "deeplynx" for c in chunks)
    assert all(c["untrusted"] is True for c in chunks)
