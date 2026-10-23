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

"""Cross-repo A2A contract tests (static, no Docker).

These tests catch protocol drift between the three parties of the A2A
conversation *before* runtime:

1. platform A2A client (``tests/system/a2a_client.py``) — builds the
   JSON-RPC envelope sent to the client-agent
2. client-agent (``agents/client-agent/tool_discovery.py``) — builds the
   JSON-RPC envelope sent to specialist agents
3. prometheus_api (``PrometheusAgentExecutor`` + a2a-sdk) — parses what the
   other two produce

Each request builder's real output is captured and fed through the real
a2a-sdk ``SendMessageRequest`` protobuf and the real ``_extract_params``
implementation, asserting that skillId, conversation params, and contextId
survive the round trip.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
for _entry in (PLATFORM_ROOT / "agents" / "client-agent",):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from a2a.server.agent_execution import RequestContext  # noqa: E402
from a2a.server.context import ServerCallContext  # noqa: E402
from a2a.types import SendMessageRequest  # noqa: E402
from google.protobuf.json_format import ParseDict  # noqa: E402
from prometheus_api.agent import PrometheusAgentExecutor  # noqa: E402
from prometheus_api.contract import (  # noqa: E402
    ConversationRequest,
    ConversationResponse,
    ConversationStatus,
)

import tool_discovery  # noqa: E402  (client-agent)
from system.a2a_client import A2AClient  # noqa: E402  (platform A2A client)


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _specialist_final_status(payload: dict) -> dict:
    return {
        "result": {
            "task": {
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {"parts": [{"text": json.dumps(payload)}]},
                }
            }
        }
    }


def _capture_client_agent_request(monkeypatch, **kwargs) -> dict:
    """Run the real call_a2a_agent and capture the JSON-RPC envelope it sends."""
    captured: dict = {}

    class _CapturingClient:
        def __init__(self, *args, **client_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, endpoint, json=None, headers=None):
            captured["endpoint"] = endpoint
            captured["message"] = json
            return _FakeResponse(_specialist_final_status({"status": "completed"}))

    monkeypatch.setattr(tool_discovery.httpx, "AsyncClient", _CapturingClient)
    asyncio.run(tool_discovery.call_a2a_agent("http://backend:8000/a2a/test-agent", "analyze_sample", **kwargs))
    return captured["message"]


def _capture_frontend_request(monkeypatch, response_payload: dict, **send_kwargs):
    """Run the real A2AClient.send and capture the JSON-RPC envelope it sends."""
    captured: dict = {}

    final_event = {
        "result": {
            "statusUpdate": {
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "message": {"parts": [{"text": json.dumps(response_payload)}]},
                },
            }
        }
    }

    class _FakeStream:
        def __init__(self):
            self.headers = {"content-type": "application/x-ndjson"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield json.dumps(final_event)

    class _CapturingClient:
        def __init__(self, *args, **client_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, **kwargs):
            captured["message"] = kwargs.get("json")
            return _FakeStream()

    import system.a2a_client as a2a_module

    monkeypatch.setattr(a2a_module.httpx, "AsyncClient", _CapturingClient)
    client = A2AClient(agent_url="http://client-agent:8000", agent_secret="secret")
    response = asyncio.run(client.send(**send_kwargs))
    return captured["message"], response


def _request_context_from_envelope(envelope: dict) -> RequestContext:
    """Build a RequestContext the way the a2a-sdk server does from a request."""
    request = ParseDict(envelope["params"], SendMessageRequest())
    return RequestContext(call_context=ServerCallContext(), request=request)


# ---------------------------------------------------------------------------
# client-agent -> specialist (prometheus_api executor)
# ---------------------------------------------------------------------------


def test_client_agent_request_parses_through_prometheus_api(monkeypatch):
    envelope = _capture_client_agent_request(
        monkeypatch,
        conversation_id="conv-77",
        material_id="SS316",
        temperature_c=350,
    )

    # The envelope must satisfy the real a2a-sdk wire schema.
    assert envelope["method"] == "SendMessage"
    context = _request_context_from_envelope(envelope)

    # conversationId must arrive as the SDK context_id (artifact/state scoping).
    assert context.context_id == "conv-77"

    # The real executor must recover skill id and parameters.
    params = PrometheusAgentExecutor(agent_name="Test")._extract_params(context)
    assert params["skill_id"] == "analyze_sample"
    assert params["conversation_id"] == "conv-77"
    assert params["material_id"] == "SS316"
    assert params["temperature_c"] == 350


def test_client_agent_resume_overrides_context_id(monkeypatch):
    envelope = _capture_client_agent_request(
        monkeypatch,
        conversation_id="conv-77",
        _a2a_context_id="downstream-ctx",
        _a2a_task_id="task-1",
    )
    context = _request_context_from_envelope(envelope)
    assert context.context_id == "downstream-ctx"
    assert envelope["params"]["message"]["taskId"] == "task-1"


# ---------------------------------------------------------------------------
# frontend -> client-agent
# ---------------------------------------------------------------------------


def test_frontend_request_parses_through_prometheus_api(monkeypatch):
    envelope, _ = _capture_frontend_request(
        monkeypatch,
        {"conversation_id": "conv-88", "status": "answer", "response_text": "hi"},
        query="analyze SS316 corrosion",
        conversation_id="conv-88",
        plan_approved=True,
    )

    assert envelope["method"] == "SendStreamingMessage"
    context = _request_context_from_envelope(envelope)
    assert context.context_id == "conv-88"

    # The text part payload must be a valid ConversationRequest.
    params = PrometheusAgentExecutor(agent_name="Test")._extract_params(context)
    request = ConversationRequest.model_validate(params)
    assert request.query == "analyze SS316 corrosion"
    assert request.conversation_id == "conv-88"
    assert request.plan_approved is True


def test_frontend_parses_server_response_payload(monkeypatch):
    server_response = ConversationResponse(
        conversation_id="conv-99",
        status=ConversationStatus.COMPLETED,
        report="Report body",
        artifacts=[{"artifact_id": "a-1", "name": "mesh.exo"}],
    )
    _, parsed = _capture_frontend_request(
        monkeypatch,
        json.loads(json.dumps(server_response.model_dump())),
        query="q",
        conversation_id="conv-99",
    )
    assert parsed.status == "completed"
    assert parsed.conversation_id == "conv-99"
    assert parsed.report == "Report body"
    assert parsed.artifacts == [{"artifact_id": "a-1", "name": "mesh.exo"}]


def test_frontend_rejects_unknown_status_loudly(monkeypatch):
    with pytest.raises(Exception):
        _capture_frontend_request(
            monkeypatch,
            {"conversation_id": "conv-1", "status": "not-a-real-status"},
            query="q",
            conversation_id="conv-1",
        )


# ---------------------------------------------------------------------------
# status vocabulary
# ---------------------------------------------------------------------------


def test_statuses_handled_by_frontend_exist_in_contract():
    # Mirrors the dispatch in frontend/components/message_handler.py
    handled = {
        "needs_info",
        "plan_ready",
        "completed",
        "answer",
        "recommendation",
        "executing",
        "error",
        "backgrounded",
    }
    assert handled == set(ConversationStatus.values())
