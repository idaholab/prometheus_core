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

"""A2A payload-size tests using the same shape as the frontend client calls."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
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
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette

from prometheus_api.agent import EventQueue, PrometheusAgent, RequestContext
from prometheus_api.agent.middleware import A2AContentSizeLimitMiddleware, BearerTokenMiddleware


AGENT_SECRET = "test-agent-secret"
BASE_URL = "http://testserver"
AGENT_URL = f"{BASE_URL}/"
DEFAULT_A2A_MAX_CONTENT_LENGTH = 10 * 1024 * 1024
A2A_VERSION_HEADERS = {"A2A-Version": "1.0"}
AUTHORIZED_A2A_HEADERS = {
    **A2A_VERSION_HEADERS,
    "Authorization": f"Bearer {AGENT_SECRET}",
}


class PayloadEchoAgent(PrometheusAgent):
    """Minimal agent that validates the request shape without echoing large blobs."""

    async def _execute(
        self,
        params: dict[str, Any],
        context: RequestContext,
        event_queue: EventQueue,
    ) -> dict[str, Any]:
        query = str(params.get("query") or params.get("message") or "")
        artifacts = params.get("artifacts") or []
        runtime_options = {
            key: value
            for key, value in params.items()
            if key not in {"query", "conversation_id", "artifacts", "skill_id", "user_id"}
        }

        query_bytes = len(query.encode())
        artifact_catalog_bytes = len(json.dumps(artifacts, default=str).encode())
        await self.send_status_update(
            context,
            event_queue,
            state=TaskState.TASK_STATE_WORKING,
            message="payload received",
            metadata={
                "query_bytes": query_bytes,
                "artifact_catalog_bytes": artifact_catalog_bytes,
            },
        )
        await self.send_json_artifact(
            context,
            event_queue,
            payload={
                "query_bytes": query_bytes,
                "artifact_count": len(artifacts),
                "runtime_option_keys": sorted(runtime_options),
            },
            name="payload_summary",
            catalog_artifact=True,
        )

        status_event_count = int(params.get("status_event_count") or 0)
        artifact_event_count = int(params.get("artifact_event_count") or 0)
        large_artifact_bytes = int(params.get("large_artifact_bytes") or 0)
        final_payload_bytes = int(params.get("final_payload_bytes") or 0)

        for index in range(status_event_count):
            await self.send_status_update(
                context,
                event_queue,
                state=TaskState.TASK_STATE_WORKING,
                message=f"progress {index + 1}",
                metadata={"progress_index": index},
            )

        for index in range(artifact_event_count):
            await self.send_text_artifact(
                context,
                event_queue,
                text=f"artifact payload {index}",
                name=f"generated_artifact_{index}",
                metadata={"artifact_index": index},
            )

        if large_artifact_bytes:
            await self.send_json_artifact(
                context,
                event_queue,
                payload={"blob": "x" * large_artifact_bytes},
                name="large_payload_artifact",
            )

        result = {
            "ok": True,
            "query_bytes": query_bytes,
            "artifact_count": len(artifacts),
            "artifact_catalog_bytes": artifact_catalog_bytes,
            "conversation_id": context.context_id,
            "skill_id": params.get("skill_id"),
            "runtime_options": runtime_options,
            "emitted_status_events": status_event_count,
            "emitted_artifact_events": artifact_event_count,
            "large_artifact_bytes": large_artifact_bytes,
        }
        if final_payload_bytes:
            result["large_result"] = "x" * final_payload_bytes
        return result


@dataclass
class FrontendStyleA2AResponse:
    result: dict[str, Any]
    status_events: list[TaskStatusUpdateEvent]
    artifact_events: list[TaskArtifactUpdateEvent]


class FrontendStyleA2AClient:
    """Small test adapter for the app-level A2A client API shape."""

    def __init__(
        self,
        *,
        agent_url: str,
        agent_secret: str,
        httpx_client: httpx.AsyncClient,
    ) -> None:
        self._agent_url = agent_url
        self._httpx_client = httpx_client
        self._client = None
        self._agent_secret = agent_secret

    async def _get_client(self):
        if self._client is None:
            self._httpx_client.headers["Authorization"] = f"Bearer {self._agent_secret}"
            self._client = await create_client(
                _payload_agent_card(),
                client_config=ClientConfig(httpx_client=self._httpx_client),
            )
        return self._client

    async def send(
        self,
        *,
        query: str,
        conversation_id: str,
        artifacts: list[dict[str, Any]],
        on_status: Callable[[TaskStatusUpdateEvent], Awaitable[None] | None] | None = None,
        **runtime_request_options: Any,
    ) -> FrontendStyleA2AResponse:
        payload = {
            "query": query,
            "conversation_id": conversation_id,
            "artifacts": artifacts,
            **runtime_request_options,
        }
        request = SendMessageRequest(
            message=Message(
                message_id=str(uuid.uuid4()),
                role=Role.ROLE_USER,
                parts=[Part(text=json.dumps(payload))],
                context_id=conversation_id,
                metadata={"skillId": "payload_echo"},
            )
        )
        status_events: list[TaskStatusUpdateEvent] = []
        artifact_events: list[TaskArtifactUpdateEvent] = []
        final_result: dict[str, Any] | None = None

        client = await self._get_client()
        async for response in client.send_message(request):
            if response.HasField("status_update"):
                event = response.status_update
                status_events.append(event)
                if on_status is not None:
                    maybe_awaitable = on_status(event)
                    if maybe_awaitable is not None:
                        await maybe_awaitable
                if event.status.state == TaskState.TASK_STATE_COMPLETED and event.status.HasField(
                    "message"
                ):
                    final_result = _json_from_text_message(event.status.message)
            elif response.HasField("artifact_update"):
                artifact_events.append(response.artifact_update)

        if final_result is None:
            raise AssertionError("A2A stream did not include a final JSON status message")

        return FrontendStyleA2AResponse(
            result=final_result,
            status_events=status_events,
            artifact_events=artifact_events,
        )


def _json_from_text_message(message: Message) -> dict[str, Any]:
    for part in message.parts:
        if part.WhichOneof("content") == "text":
            payload = json.loads(part.text)
            assert isinstance(payload, dict)
            return payload
    raise AssertionError("Expected final status message to contain a text part")


def _text_from_status_event(event: TaskStatusUpdateEvent) -> str:
    message = event.status.message
    if message is None:
        return ""
    for part in message.parts:
        if part.WhichOneof("content") == "text":
            return part.text
    return ""


def _payload_agent_card() -> AgentCard:
    return AgentCard(
        name="Payload Echo Agent",
        description="Test agent for A2A payload-size coverage",
        supported_interfaces=[
            AgentInterface(
                url=AGENT_URL,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="payload_echo",
                name="Payload Echo",
                description="Summarizes request payload sizes",
                tags=["test"],
            )
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
    )


def _build_payload_agent_app(*, max_content_length: int | None = DEFAULT_A2A_MAX_CONTENT_LENGTH):
    agent = PayloadEchoAgent(agent_name="Payload Echo Agent")
    agent_card = _payload_agent_card()
    request_handler = DefaultRequestHandler(
        agent_executor=agent.create_executor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    routes = [
        *create_agent_card_routes(agent_card),
        *create_jsonrpc_routes(request_handler, rpc_url="/"),
    ]
    app = Starlette(routes=routes)
    if max_content_length is not None:
        app.add_middleware(
            A2AContentSizeLimitMiddleware,
            max_content_length=max_content_length,
        )
    app.add_middleware(BearerTokenMiddleware, secret=AGENT_SECRET, required=True)
    return app


def _artifact_catalog(description_bytes: int) -> list[dict[str, Any]]:
    if description_bytes <= 0:
        return []
    return [
        {
            "artifact_id": "artifact-1",
            "name": "large-input-catalog-entry",
            "description": "a" * description_bytes,
            "uri": "deeplynx://organizations/1/projects/2/items/3",
            "mime_type": "application/json",
            "size_bytes": description_bytes,
            "producer_agent_id": "upstream-agent",
        }
    ]


def _large_artifact_catalog(count: int) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": f"artifact-{index}",
            "name": f"catalog artifact {index}",
            "description": "artifact catalog entry used to mimic accumulated conversation state",
            "uri": f"deeplynx://organizations/1/projects/2/items/{index}",
            "mime_type": "application/json",
            "size_bytes": 1_024 + index,
            "producer_agent_id": f"upstream-agent-{index % 5}",
            "metadata": {"ordinal": index, "group": index % 10},
        }
        for index in range(count)
    ]


@pytest.mark.parametrize(
    ("query_bytes", "artifact_description_bytes"),
    [
        (0, 0),
        (1_024, 0),
        (64 * 1024, 8 * 1024),
        (1_100_000, 256 * 1024),
    ],
)
async def test_frontend_style_a2a_send_handles_payload_sizes(
    query_bytes: int,
    artifact_description_bytes: int,
) -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)
    observed_statuses: list[TaskStatusUpdateEvent] = []

    async def on_status(event: TaskStatusUpdateEvent) -> None:
        observed_statuses.append(event)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="x" * query_bytes,
            conversation_id="conversation-payload-sizes",
            artifacts=_artifact_catalog(artifact_description_bytes),
            on_status=on_status,
            model="test-model",
            temperature=0.2,
            max_tokens=256,
        )

    assert response.result["ok"] is True
    assert response.result["query_bytes"] == query_bytes
    assert response.result["artifact_count"] == (1 if artifact_description_bytes else 0)
    assert response.result["artifact_catalog_bytes"] >= artifact_description_bytes
    assert response.result["conversation_id"] == "conversation-payload-sizes"
    assert response.result["skill_id"] == "payload_echo"
    assert response.result["runtime_options"] == {
        "max_tokens": 256,
        "model": "test-model",
        "temperature": 0.2,
    }

    assert observed_statuses == response.status_events
    assert [event.status.state for event in response.status_events] == [
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]
    assert len(response.artifact_events) == 1
    assert response.artifact_events[0].artifact.name == "payload_summary"


async def test_frontend_style_a2a_send_handles_many_status_events() -> None:
    status_event_count = 128
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)
    observed_statuses: list[TaskStatusUpdateEvent] = []

    async def on_status(event: TaskStatusUpdateEvent) -> None:
        observed_statuses.append(event)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="status fanout",
            conversation_id="conversation-many-statuses",
            artifacts=[],
            on_status=on_status,
            status_event_count=status_event_count,
        )

    progress_events = [
        event
        for event in response.status_events
        if "progress_index" in MessageToDict(event.metadata)
    ]
    assert len(progress_events) == status_event_count
    assert progress_events[0].metadata["progress_index"] == 0
    assert progress_events[-1].metadata["progress_index"] == status_event_count - 1
    assert len(response.status_events) == status_event_count + 3
    assert observed_statuses == response.status_events
    assert response.status_events[-1].status.state == TaskState.TASK_STATE_COMPLETED
    assert response.result["emitted_status_events"] == status_event_count


async def test_frontend_style_a2a_send_handles_many_artifact_events() -> None:
    artifact_event_count = 64
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="artifact fanout",
            conversation_id="conversation-many-artifacts",
            artifacts=[],
            artifact_event_count=artifact_event_count,
        )

    generated_artifacts = [
        event
        for event in response.artifact_events
        if event.artifact.name and event.artifact.name.startswith("generated_artifact_")
    ]
    assert len(generated_artifacts) == artifact_event_count
    assert len(response.artifact_events) == artifact_event_count + 1
    assert (
        response.artifact_events[-1].artifact.name
        == f"generated_artifact_{artifact_event_count - 1}"
    )
    assert response.status_events[-1].status.state == TaskState.TASK_STATE_COMPLETED
    assert response.result["emitted_artifact_events"] == artifact_event_count


async def test_large_data_in_final_status_is_visible_as_a_large_status_packet() -> None:
    final_payload_bytes = 256 * 1024
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="large final response",
            conversation_id="conversation-large-final",
            artifacts=[],
            final_payload_bytes=final_payload_bytes,
        )

    final_status_text = _text_from_status_event(response.status_events[-1])
    assert len(response.result["large_result"]) == final_payload_bytes
    assert len(final_status_text.encode()) >= final_payload_bytes
    assert response.status_events[-1].status.state == TaskState.TASK_STATE_COMPLETED


async def test_large_data_as_artifact_keeps_final_status_small() -> None:
    large_artifact_bytes = 512 * 1024
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="large artifact response",
            conversation_id="conversation-large-artifact",
            artifacts=[],
            large_artifact_bytes=large_artifact_bytes,
        )

    large_artifact_events = [
        event
        for event in response.artifact_events
        if event.artifact.name == "large_payload_artifact"
    ]
    assert len(large_artifact_events) == 1
    large_part = large_artifact_events[0].artifact.parts[0]
    assert large_part.WhichOneof("content") == "data"
    assert len(MessageToDict(large_part.data)["blob"]) == large_artifact_bytes
    assert "large_result" not in response.result
    assert response.result["large_artifact_bytes"] == large_artifact_bytes
    assert len(_text_from_status_event(response.status_events[-1]).encode()) < 2_048


async def test_frontend_style_a2a_send_handles_large_artifact_catalog_shape() -> None:
    artifact_count = 750
    artifacts = _large_artifact_catalog(artifact_count)
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="catalog-heavy request",
            conversation_id="conversation-large-catalog",
            artifacts=artifacts,
        )

    assert response.result["artifact_count"] == artifact_count
    assert response.result["artifact_catalog_bytes"] > 100_000
    assert response.status_events[-1].status.state == TaskState.TASK_STATE_COMPLETED


async def test_concurrent_a2a_sends_to_same_conversation_keep_results_isolated() -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )

        async def send_one(index: int) -> FrontendStyleA2AResponse:
            return await client.send(
                query="x" * (index + 1),
                conversation_id="shared-conversation",
                artifacts=[],
                request_index=index,
            )

        responses = await asyncio.gather(*(send_one(index) for index in range(8)))

    assert sorted(response.result["query_bytes"] for response in responses) == list(range(1, 9))
    assert {response.result["conversation_id"] for response in responses} == {"shared-conversation"}
    assert sorted(
        response.result["runtime_options"]["request_index"] for response in responses
    ) == list(range(8))
    assert all(
        response.status_events[-1].status.state == TaskState.TASK_STATE_COMPLETED
        for response in responses
    )


async def test_status_callback_exception_propagates_to_frontend_style_client() -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    def on_status(_: TaskStatusUpdateEvent) -> None:
        raise RuntimeError("status callback failed")

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        with pytest.raises(RuntimeError, match="status callback failed"):
            await client.send(
                query="callback failure",
                conversation_id="conversation-callback-failure",
                artifacts=[],
                on_status=on_status,
            )


async def test_slow_status_callback_still_observes_every_status_event() -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)
    observed_statuses: list[TaskStatusUpdateEvent] = []

    async def on_status(event: TaskStatusUpdateEvent) -> None:
        await asyncio.sleep(0)
        observed_statuses.append(event)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        client = FrontendStyleA2AClient(
            agent_url=AGENT_URL,
            agent_secret=AGENT_SECRET,
            httpx_client=httpx_client,
        )
        response = await client.send(
            query="slow callback",
            conversation_id="conversation-slow-callback",
            artifacts=[],
            on_status=on_status,
            status_event_count=10,
        )

    assert observed_statuses == response.status_events
    assert len(observed_statuses) == 13


async def test_a2a_message_send_requires_agent_secret() -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)
    request = _send_message_request(query="hello", conversation_id="auth-conversation")

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        unauthorized = await client.post("/", json=request, headers=A2A_VERSION_HEADERS)
        authorized = await client.post(
            "/",
            json=request,
            headers=AUTHORIZED_A2A_HEADERS,
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["data"]["reason"] == "Missing Authorization header"
    assert authorized.status_code == 200
    assert "result" in authorized.json()


async def test_a2a_message_send_enforces_default_payload_limit_boundary() -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)
    under_limit_query = "x" * (9 * 1024 * 1024)
    over_limit_query = "x" * (11 * 1024 * 1024)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        under_limit = await client.post(
            "/",
            json=_send_message_request(
                query=under_limit_query,
                conversation_id="under-default-limit",
            ),
            headers=AUTHORIZED_A2A_HEADERS,
        )
        over_limit = await client.post(
            "/",
            json=_send_message_request(
                query=over_limit_query,
                conversation_id="over-default-limit",
            ),
            headers=AUTHORIZED_A2A_HEADERS,
        )

    assert under_limit.status_code == 200
    under_limit_body = under_limit.json()
    assert under_limit_body["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert _json_from_rpc_result_status(under_limit_body)["query_bytes"] == len(under_limit_query)

    assert over_limit.status_code == 200
    assert over_limit.json() == {
        "error": {"code": -32600, "message": "Payload too large"},
        "id": None,
        "jsonrpc": "2.0",
    }


async def test_a2a_message_send_returns_json_rpc_error_for_payload_over_limit() -> None:
    app = _build_payload_agent_app(max_content_length=1_024)
    transport = httpx.ASGITransport(app=app)
    request = _send_message_request(query="x" * 2_048, conversation_id="oversized-conversation")

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        response = await client.post(
            "/",
            json=request,
            headers=AUTHORIZED_A2A_HEADERS,
        )

    assert response.status_code == 200
    assert response.json() == {
        "error": {"code": -32600, "message": "Payload too large"},
        "id": None,
        "jsonrpc": "2.0",
    }


@pytest.mark.parametrize("message_text", ["plain prompt text", '{"query": "unterminated"'])
async def test_a2a_stream_accepts_plain_text_and_invalid_json_as_message(
    message_text: str,
) -> None:
    app = _build_payload_agent_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as httpx_client:
        response = await _send_streaming_text_message(
            httpx_client,
            text=message_text,
            conversation_id="conversation-plain-text",
        )

    assert response.result["ok"] is True
    assert response.result["query_bytes"] == len(message_text.encode())
    assert response.result["conversation_id"] == "conversation-plain-text"
    assert response.result["skill_id"] == "payload_echo"


def _send_message_request(*, query: str, conversation_id: str) -> dict[str, Any]:
    payload = {"query": query, "conversation_id": conversation_id, "artifacts": []}
    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=json.dumps(payload))],
            context_id=conversation_id,
            metadata={"skillId": "payload_echo"},
        )
    )
    return {
        "jsonrpc": "2.0",
        "id": "payload-size-check",
        "method": "SendMessage",
        "params": MessageToDict(request),
    }


def _json_from_rpc_result_status(response_body: dict[str, Any]) -> dict[str, Any]:
    parts = response_body["result"]["task"]["status"]["message"]["parts"]
    text = parts[0].get("text") or parts[0].get("root", {}).get("text")
    payload = json.loads(text)
    assert isinstance(payload, dict)
    return payload


async def _send_streaming_text_message(
    httpx_client: httpx.AsyncClient,
    *,
    text: str,
    conversation_id: str,
) -> FrontendStyleA2AResponse:
    httpx_client.headers["Authorization"] = f"Bearer {AGENT_SECRET}"
    client = await create_client(
        _payload_agent_card(),
        client_config=ClientConfig(httpx_client=httpx_client),
    )
    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=text)],
            context_id=conversation_id,
            metadata={"skillId": "payload_echo"},
        )
    )
    status_events: list[TaskStatusUpdateEvent] = []
    artifact_events: list[TaskArtifactUpdateEvent] = []
    final_result: dict[str, Any] | None = None

    async for response in client.send_message(request):
        if response.HasField("status_update"):
            event = response.status_update
            status_events.append(event)
            if event.status.state == TaskState.TASK_STATE_COMPLETED and event.status.HasField(
                "message"
            ):
                final_result = _json_from_text_message(event.status.message)
        elif response.HasField("artifact_update"):
            artifact_events.append(response.artifact_update)

    if final_result is None:
        raise AssertionError("A2A stream did not include a final JSON status message")
    return FrontendStyleA2AResponse(
        result=final_result,
        status_events=status_events,
        artifact_events=artifact_events,
    )
