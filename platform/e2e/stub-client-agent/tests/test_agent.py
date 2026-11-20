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

"""Tests for the e2e stub client-agent: the reply it gives, and the shape the backend reads."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from prometheus_api.agent.base import DelegatingPrometheusAgentExecutor
from prometheus_api.contract import ConversationResponse

AGENT_DIR = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("stub_client_agent_module", AGENT_DIR / "agent.py")
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _execute(params: dict, context_id: str = "ctx-1") -> tuple[dict, AsyncMock]:
    agent = _MODULE.StubClientAgent(agent_name="Stub Client Agent")
    agent.send_status_update = AsyncMock()  # event emission needs a live A2A stack
    context = MagicMock(spec=RequestContext)
    context.context_id = context_id
    result = asyncio.run(agent._execute(params, context, AsyncMock(spec=EventQueue)))
    return result, agent.send_status_update


def test_any_prompt_gets_the_fixed_answer_in_its_conversation():
    for query in ("Hello, what can you help me with?", "", "show me a mesh"):
        result, _ = _execute({"query": query, "conversation_id": "conv-1"})

        assert result == {"conversation_id": "conv-1", "status": "answer", "response_text": _MODULE.TEXT_ANSWER}


def test_the_reply_parses_as_the_contract_the_backend_reads():
    result, _ = _execute({"query": "hello", "conversation_id": "conv-1"})

    # The backend json.loads the final message and validates it as this model
    parsed = ConversationResponse.model_validate(json.loads(json.dumps(result)))
    assert parsed.status == "answer"
    assert parsed.response_text == _MODULE.TEXT_ANSWER


def test_it_sends_one_status_update_before_answering():
    _, status = _execute({"query": "hello", "conversation_id": "conv-1"})

    status.assert_awaited_once()
    assert status.await_args.kwargs["message"] == _MODULE.STATUS_MESSAGE


def test_the_conversation_id_falls_back_to_the_a2a_context():
    result, _ = _execute({"query": "hi"}, context_id="ctx-from-a2a")

    assert result["conversation_id"] == "ctx-from-a2a"


def test_the_executor_runs_the_stub_without_a_deeplynx_execution_record():
    agent = _MODULE.StubClientAgent(agent_name="Stub Client Agent")
    executor = agent.create_executor()

    assert isinstance(executor, DelegatingPrometheusAgentExecutor)
    assert executor._execution_scope is None
    assert executor._execute_fn == agent._execute


def test_main_starts_the_agent_on_its_port(monkeypatch):
    monkeypatch.setenv("AGENT_PORT", "8123")
    with patch.object(_MODULE.StubClientAgent, "run", autospec=True) as run:
        _MODULE.main()

    assert run.call_args.kwargs == {"port": 8123}
