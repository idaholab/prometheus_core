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

"""Execution-record lineage edges: ``input_to`` for fetched, ``generated`` for emitted."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext
from prometheus_api.agent.artifacts import ArtifactReference
from prometheus_api.agent.base import _deeplynx_item_id
from prometheus_api.agent.identity import UserIdentity, identity_scope
from prometheus_api.storage_client.connection import ConnectionConfig

RECORD_ID = 500
ORG, PROJECT = 1, 2


class FakeStorage:
    """In-memory DeepLynx: execution items, uploads, and edges."""

    def __init__(self):
        self.edges = []
        self.fail_edges = False

    def client_class(self):
        storage = self

        class Items:
            async def create(self, item):
                return SimpleNamespace(id=RECORD_ID)

            async def get(self, item_id):
                return SimpleNamespace(properties={}, class_id=None, original_id=None)

            async def update(self, item_id, update):
                return None

            async def add_tags(self, item_id, tags):
                return None

        class Files:
            async def upload(self, file_path, name, description):
                return SimpleNamespace(id=900, uri=None, size=3)

        class Relationships:
            async def create(self, relationship):
                if storage.fail_edges:
                    raise RuntimeError("edge endpoint down")
                storage.edges.append(
                    (
                        relationship.from_item_id,
                        relationship.relationship_type,
                        relationship.to_item_id,
                    )
                )

        class Client:
            def __init__(self, config):
                self.items = Items()
                self.files = Files()
                self.relationships = Relationships()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return Client


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr("prometheus_api.agent.base.AsyncStorageClient", fake.client_class())

    async def get_credential(self, resource, scope=None):
        return SimpleNamespace(
            value={"org_id": ORG, "project_id": PROJECT, "key": "k", "secret": "s"}
        )

    monkeypatch.setattr(PrometheusAgent, "get_credential", get_credential)
    return fake


def _uri(item_id):
    return f"deeplynx://organizations/{ORG}/projects/{PROJECT}/items/{item_id}"


def _agent(*references):
    agent = PrometheusAgent(agent_name="Lineage Agent")
    agent.artifact_resolver._download_artifact_uri_to_cache = MagicMock(return_value="/tmp/x")
    for reference in references:
        agent.artifact_registry.register(reference)
    return agent


def _reference(artifact_id, uri):
    return ArtifactReference(
        artifact_id=artifact_id,
        conversation_id="conv",
        name=f"{artifact_id}.txt",
        description="",
        uri=uri,
        json_body=None if uri else {"inline": True},
    )


def _context():
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-1"
    context.context_id = "conv"
    return context


async def _in_execution(agent, body):
    identity = UserIdentity(user_id="user", claims={}, raw_token="token")
    with identity_scope(identity):
        async with agent._create_execution_record({}, _context()):
            await body()


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (_uri(42), 42),
        ("deeplynx://organizations/1/projects/2/items/x", None),
        ("deeplynx://session-abc/moose/input.i", None),
        ("memory://organizations/1/projects/2/items/42", None),
        ("", None),
        (None, None),
    ],
)
def test_deeplynx_item_id(uri, expected):
    assert _deeplynx_item_id(uri) == expected


async def test_fetched_artifacts_are_linked_input_to_once(storage):
    """Covers REQ-009-25 and BEH-009-12."""
    agent = _agent(
        _reference("a", _uri(11)),
        _reference("a-copy", _uri(11)),  # another catalog entry, same DeepLynx item
        _reference("b", _uri(12)),
    )

    async def body():
        for artifact_id in ("a", "a", "a-copy", "b"):
            await agent.get_artifact_file_path(artifact_id, conversation_id="conv")

    await _in_execution(agent, body)

    assert storage.edges == [(11, "input_to", RECORD_ID), (12, "input_to", RECORD_ID)]


async def test_fetch_without_deeplynx_item_is_not_linked(storage):
    """Covers REQ-009-25: only DeepLynx item URIs are linked."""
    agent = _agent(_reference("inline", None), _reference("remote", "memory://x/y.txt"))
    agent.artifact_resolver._materialize_inline_artifact = MagicMock(return_value="/tmp/y")

    async def body():
        await agent.get_artifact_file_path("inline", conversation_id="conv")
        await agent.get_artifact_file_path("remote", conversation_id="conv")

    await _in_execution(agent, body)

    assert storage.edges == []


async def test_fetch_outside_execution_is_not_linked(storage):
    """Covers BEH-009-13: no bound execution item, no edge."""
    agent = _agent(_reference("a", _uri(11)))

    await agent.get_artifact_file_path("a", conversation_id="conv")

    assert storage.edges == []


async def test_input_link_failure_is_logged_and_retried(storage, caplog):
    """Covers REQ-009-25: a failed edge is logged, not fatal, and not counted."""
    agent = _agent(_reference("a", _uri(11)))

    async def body():
        storage.fail_edges = True
        path = await agent.get_artifact_file_path("a", conversation_id="conv")
        assert path == "/tmp/x"
        storage.fail_edges = False
        await agent.get_artifact_file_path("a", conversation_id="conv")

    await _in_execution(agent, body)

    assert "Failed to link artifact a input_to execution record 500" in caplog.text
    assert storage.edges == [(11, "input_to", RECORD_ID)]


async def test_linked_inputs_reset_between_executions(storage):
    """Covers BEH-009-12: each execution links its own fetches."""
    agent = _agent(_reference("a", _uri(11)))

    async def body():
        await agent.get_artifact_file_path("a", conversation_id="conv")

    await _in_execution(agent, body)
    await _in_execution(agent, body)

    assert storage.edges == [(11, "input_to", RECORD_ID)] * 2


def _storage_config():
    return ConnectionConfig(
        base_url="https://deeplynx.test/api/v1",
        organization_id=ORG,
        project_id=PROJECT,
        api_key="k",
        api_secret="s",
    )


async def _send(agent, tmp_path):
    source = tmp_path / "out.txt"
    source.write_text("out")
    return await agent.send_deeplynx_artifact(
        _context(),
        AsyncMock(spec=EventQueue),
        file_path=source,
        name="out.txt",
        description="output",
        storage_config=_storage_config(),
    )


async def test_emitted_artifact_is_linked_generated(storage, tmp_path):
    """Covers REQ-009-26 and BEH-009-13."""
    agent = _agent()
    agent.send_artifact_reference = AsyncMock()

    async def body():
        await _send(agent, tmp_path)

    await _in_execution(agent, body)

    assert storage.edges == [(RECORD_ID, "generated", 900)]
    agent.send_artifact_reference.assert_awaited_once()


async def test_emit_outside_execution_is_not_linked(storage, tmp_path):
    """Covers BEH-009-13: no bound execution item, no edge."""
    agent = _agent()
    agent.send_artifact_reference = AsyncMock()

    await _send(agent, tmp_path)

    assert storage.edges == []
    agent.send_artifact_reference.assert_awaited_once()


async def test_generated_link_failure_is_logged_and_artifact_still_sent(storage, tmp_path, caplog):
    """Covers REQ-009-26: a failed edge is logged and the artifact is still emitted."""
    agent = _agent()
    agent.send_artifact_reference = AsyncMock()
    storage.fail_edges = True

    async def body():
        await _send(agent, tmp_path)

    await _in_execution(agent, body)

    assert "Failed to link execution record 500 generated artifact item 900" in caplog.text
    agent.send_artifact_reference.assert_awaited_once()
