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

"""Unit tests for the lifted shared utilities (task 03).

These exercise the pure, offline-testable surface: the JSON-RPC envelope built
by ``A2AClient.send()``, ``_extract_from_status`` against a canned A2A payload,
and the ``task_events`` channel/terminal-state helpers. No live agent or Redis
is required.
"""

import json
import uuid

import httpx
import pytest

from app.a2a_client import WORKFLOW_TEMPLATES_TIMEOUT_S, A2AClient
from app import task_events


def _canned_status_payload(data: dict) -> dict:
    """Wrap a ConversationResponse dict as an A2A v1 task.status payload."""
    return {
        "status": {
            "message": {
                "role": "ROLE_AGENT",
                "parts": [{"text": json.dumps(data)}],
            }
        }
    }


def test_send_builds_jsonrpc_envelope(monkeypatch):
    client = A2AClient("http://agent.local/", "sekret")

    captured: dict = {}

    async def fake_stream_request(message, headers, *, on_status=None):
        captured["message"] = message
        captured["headers"] = headers
        return {"result": _canned_status_payload({"status": "completed", "message": "ok"})}

    monkeypatch.setattr(client, "_stream_request", fake_stream_request)

    resp = _run(
        client.send(
            query="hello",
            conversation_id="conv-1",
            followup_answers={"q1": "a1"},
            plan_approved=True,
        )
    )

    msg = captured["message"]
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "SendStreamingMessage"
    # request id is a UUID
    uuid.UUID(msg["id"])

    params = msg["params"]
    assert params["configuration"] == {"returnImmediately": False}
    message = params["message"]
    assert message["role"] == "ROLE_USER"
    assert message["contextId"] == "conv-1"
    uuid.UUID(message["messageId"])

    # The inner ConversationRequest payload is a single JSON text part.
    assert len(message["parts"]) == 1
    inner = json.loads(message["parts"][0]["text"])
    assert inner["query"] == "hello"
    assert inner["conversation_id"] == "conv-1"
    assert inner["followup_answers"] == {"q1": "a1"}
    assert inner["plan_approved"] is True
    # Falsy/omitted optional fields are not serialized.
    assert "plan_rejected" not in inner
    assert "artifacts" not in inner
    assert "workflow_id" not in inner
    assert "uploaded_files" not in inner

    headers = captured["headers"]
    assert headers["Authorization"] == "Bearer sekret"
    assert headers["A2A-Version"] == "1.0"
    assert "text/event-stream" in headers["Accept"]

    # And the canned terminal response is parsed back out.
    assert resp.status == "completed"


def test_send_omits_falsy_optionals(monkeypatch):
    client = A2AClient("http://agent.local", "s")
    captured: dict = {}

    async def fake_stream_request(message, headers, *, on_status=None):
        captured["message"] = message
        return {"result": _canned_status_payload({"status": "executing", "message": "…"})}

    monkeypatch.setattr(client, "_stream_request", fake_stream_request)
    _run(client.send(query="q", conversation_id="c"))

    inner = json.loads(captured["message"]["params"]["message"]["parts"][0]["text"])
    assert inner == {"query": "q", "conversation_id": "c"}


def test_extract_from_status_parses_canned_payload():
    client = A2AClient("http://agent.local", "s")
    payload = _canned_status_payload({"status": "needs_info", "message": "need more"})
    resp = client._extract_from_status(payload)
    assert resp.status == "needs_info"


@pytest.mark.parametrize(
    "bad",
    [
        {},  # no status
        {"status": "not-an-object"},
        {"status": {"message": "not-an-object"}},
        {"status": {"message": {"parts": []}}},  # zero parts
        {"status": {"message": {"parts": [{"text": "not-json"}]}}},
        {"status": {"message": {"parts": [{"text": json.dumps({"no": "status"})}]}}},
        {"status": {"message": {"parts": [{"bogus": "field", "text": "{}"}]}}},
    ],
)
def test_extract_from_status_rejects_malformed(bad):
    client = A2AClient("http://agent.local", "s")
    with pytest.raises(ValueError):
        client._extract_from_status(bad)


def _templates_transport(monkeypatch, handler):
    """Route every ``httpx.AsyncClient`` the client builds through ``handler``; return the seen requests."""
    seen: list = []
    real_async_client = httpx.AsyncClient

    def recording(request):
        seen.append(request)
        return handler(request)

    def client(**kwargs):
        return real_async_client(transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return seen


def test_list_workflow_templates_gets_library_with_bearer(monkeypatch):
    body = {"enabled": True, "workflows": [{"workflow_id": "heat-survey"}], "errors": []}
    seen = _templates_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    client = A2AClient("http://agent.local/", "sekret")

    payload = _run(client.list_workflow_templates())

    assert payload == body
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == "http://agent.local/workflows/templates"
    assert request.headers["Authorization"] == "Bearer sekret"
    # The short library timeout, not the client's 900 s turn timeout.
    assert WORKFLOW_TEMPLATES_TIMEOUT_S == 10.0
    assert request.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 10.0)


def test_list_workflow_templates_raises_on_non_2xx(monkeypatch):
    _templates_transport(monkeypatch, lambda request: httpx.Response(503, json={"detail": "down"}))
    client = A2AClient("http://agent.local", "s")

    with pytest.raises(httpx.HTTPStatusError):
        _run(client.list_workflow_templates())


@pytest.mark.parametrize("body", [[], "library", None], ids=["list", "string", "null"])
def test_list_workflow_templates_rejects_non_object_body(monkeypatch, body):
    # The JSON text itself: ``json=None`` would send no body at all.
    content = json.dumps(body).encode()
    _templates_transport(
        monkeypatch,
        lambda request: httpx.Response(200, content=content, headers={"Content-Type": "application/json"}),
    )
    client = A2AClient("http://agent.local", "s")

    with pytest.raises(ValueError, match="not a JSON object"):
        _run(client.list_workflow_templates())


def test_task_events_helpers():
    assert task_events.is_terminal("completed") is True
    assert task_events.is_terminal("failed") is True
    assert task_events.is_terminal("executing") is False
    assert task_events.is_terminal(None) is False
    assert task_events.events_channel("x") == "tasks:events:x"


def _run(coro):
    import asyncio

    return asyncio.run(coro)
