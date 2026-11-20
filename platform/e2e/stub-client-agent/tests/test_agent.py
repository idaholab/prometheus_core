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

"""Tests for the e2e stub client-agent: which reply each prompt gets, and the shape the backend reads."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from prometheus_api.agent.base import DelegatingPrometheusAgentExecutor
from prometheus_api.contract import ConversationResponse
from starlette.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parents[1]
# The image copies the shared samples in; outside it, read them where they live
SHARED_SAMPLES = AGENT_DIR.parents[1] / "frontend" / "e2e" / "samples"
os.environ.setdefault("SAMPLES_DIR", str(SHARED_SAMPLES))
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


def test_a_prompt_naming_no_sample_gets_the_fixed_answer_and_no_artifact():
    for query in ("Hello, what can you help me with?", ""):
        result, _ = _execute({"query": query, "conversation_id": "conv-1"})

        assert result == {"conversation_id": "conv-1", "status": "answer", "response_text": _MODULE.TEXT_ANSWER}


def test_every_reply_parses_as_the_contract_the_backend_reads():
    for query in ("hello", "show me the mesh", "the ifc model please", "draw a diagram", "the json results"):
        result, _ = _execute({"query": query, "conversation_id": "conv-1"})

        # The backend json.loads the final message and validates it as this model
        parsed = ConversationResponse.model_validate(json.loads(json.dumps(result)))
        assert parsed.status == "answer"


def test_a_mesh_prompt_returns_the_stl_by_url_for_the_backend_to_convert():
    result, _ = _execute({"query": "Show me the MESH", "conversation_id": "conv-1"})

    (artifact,) = result["new_artifacts"]
    assert result["artifacts"] == [artifact]
    assert result["response_text"] == "Here is the mesh."
    assert artifact["name"] == "part.stl"
    assert artifact["mime_type"] == "model/stl"
    assert artifact["uri"] == f"{_MODULE.SAMPLES_BASE_URL}/part.stl"
    assert artifact["conversation_id"] == "conv-1"
    assert artifact["artifact_id"].startswith("e2e-mesh-")
    assert "json_body" not in artifact


def test_an_ifc_prompt_returns_the_model_by_url():
    result, _ = _execute({"query": "open the ifc model", "conversation_id": "conv-1"})

    (artifact,) = result["new_artifacts"]
    assert result["response_text"] == "Here is the IFC model."
    assert artifact["name"] == "model.ifc"
    assert artifact["mime_type"] == "model/ifc"
    assert artifact["uri"] == f"{_MODULE.SAMPLES_BASE_URL}/model.ifc"


def test_a_diagram_prompt_returns_the_mermaid_source_inline():
    result, _ = _execute({"query": "draw the diagram", "conversation_id": "conv-1"})

    (artifact,) = result["new_artifacts"]
    assert result["response_text"] == "Here is the diagram."
    assert artifact["mime_type"] == "text/x-mermaid"
    assert artifact["json_body"] == {"diagram": (SHARED_SAMPLES / "diagram.mmd").read_text(encoding="utf-8")}
    assert "uri" not in artifact


def test_a_json_prompt_returns_the_file_by_url_not_inline():
    # A stored JSON file, with no json_body, once showed an empty viewer (PPLT-374)
    result, _ = _execute({"query": "show me the JSON results", "conversation_id": "conv-1"})

    (artifact,) = result["new_artifacts"]
    assert result["response_text"] == "Here are the results."
    assert artifact["name"] == "results.json"
    assert artifact["mime_type"] == "application/json"
    assert artifact["uri"] == f"{_MODULE.SAMPLES_BASE_URL}/results.json"
    assert "json_body" not in artifact


def test_each_artifact_gets_its_own_id():
    first, _ = _execute({"query": "mesh"})
    second, _ = _execute({"query": "mesh"})

    assert first["new_artifacts"][0]["artifact_id"] != second["new_artifacts"][0]["artifact_id"]


def test_every_sample_the_stub_hands_out_is_one_of_the_shared_samples():
    # The Dockerfile copies these names from the shared folder, so a rename there must show up here
    dockerfile = (AGENT_DIR / "Dockerfile").read_text(encoding="utf-8")
    for sample in _MODULE.SAMPLES:
        assert sample.path.is_file(), sample.filename
        assert sample.filename in dockerfile, sample.filename


def test_the_samples_server_serves_each_file_without_a_token():
    from starlette.applications import Starlette
    from starlette.staticfiles import StaticFiles

    app = Starlette()
    app.mount("/", StaticFiles(directory=_MODULE.SAMPLES_DIR))
    client = TestClient(app)
    for sample in _MODULE.SAMPLES:
        response = client.get(f"/{sample.filename}")
        assert response.status_code == 200
        assert response.content == sample.path.read_bytes()


def test_serve_samples_runs_uvicorn_on_the_samples_port():
    with patch("uvicorn.Server") as server_cls:
        server_cls.return_value.serve = AsyncMock()
        asyncio.run(_MODULE.serve_samples())

    config = server_cls.call_args.args[0]
    assert config.port == _MODULE.SAMPLES_PORT
    assert config.host == "0.0.0.0"


def test_start_samples_server_runs_it_on_a_daemon_thread():
    with patch("threading.Thread") as thread_cls, patch.object(_MODULE, "serve_samples", new=MagicMock()) as serve:
        _MODULE.start_samples_server()
        target = thread_cls.call_args.kwargs["target"]
        with patch("asyncio.run") as run:
            target()

    assert thread_cls.call_args.kwargs["daemon"] is True
    thread_cls.return_value.start.assert_called_once()
    run.assert_called_once_with(serve.return_value)


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


def test_main_starts_the_samples_server_then_the_agent_on_its_port(monkeypatch):
    monkeypatch.setenv("AGENT_PORT", "8123")
    order = []
    with patch.object(_MODULE, "start_samples_server", side_effect=lambda: order.append("samples")), \
         patch.object(_MODULE.StubClientAgent, "run", autospec=True,
                      side_effect=lambda self, port: order.append(("agent", port))):
        _MODULE.main()

    assert order == ["samples", ("agent", 8123)]
