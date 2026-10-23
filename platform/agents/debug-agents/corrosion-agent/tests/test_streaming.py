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

"""Streaming-contract test for the corrosion agent.

Backs the ``"streaming": true`` promise in ``agent_card.json``: an agent that
advertises streaming must actually emit at least one non-final ``status-update``
event during ``_execute`` (these are what the client-agent's streaming path and
the frontend consume). The base executor turns ``send_status_update`` into a
non-final ``TaskStatusUpdateEvent`` (covered in ``prometheus_api`` tests); this
test asserts the agent itself emits one mid-execution.
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from a2a.types import TaskState


def _load_agent_module():
    here = Path(__file__).resolve()
    repo_root = here.parents[4]  # prometheus_platform
    sys.path.insert(0, str(repo_root))
    # prometheus_api ships in the base image at runtime; for local/CI test runs it
    # must be importable (installed, or the sibling checkout on sys.path).
    sys.path.insert(0, str(repo_root.parent / "prometheus_api"))

    module_path = here.parents[1] / "agent.py"
    spec = importlib.util.spec_from_file_location("corrosion_agent_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_streaming_agent_emits_intermediate_status_update(monkeypatch):
    mod = _load_agent_module()
    agent = mod.CorrosionAnalysisAgent(agent_name="Corrosion Analysis Agent")

    # Mock the LLM so _execute runs without network or credentials.
    class FakeLLM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def medium(self, prompt, **kwargs):
            return SimpleNamespace(
                text=json.dumps({"risk_level": "low", "confidence": 0.9}),
                provider_model="test-model",
                model_alias="medium",
            )

    monkeypatch.setattr(agent, "llm_client", lambda *args, **kwargs: FakeLLM())

    # Stub base helpers that reach external state (Redis-backed context/catalog);
    # keep send_status_update real so we assert the actual emitted event.

    async def _fake_json_artifact(*a, **k):
        return "artifact-id"

    monkeypatch.setattr(agent, "send_json_artifact", _fake_json_artifact)

    events = []

    class RecordingQueue:
        async def enqueue_event(self, event):
            events.append(event)

    context = SimpleNamespace(task_id="task-1", context_id="conv-1")
    params = {
        "material_id": "SS316",
        "context": {"temperature_c": 300, "pressure_mpa": 15.5},
        "skill_id": "analyze_corrosion",
    }

    result = asyncio.run(agent._execute(params, context, RecordingQueue()))

    status_updates = [
        e
        for e in events
        if type(e).__name__ == "TaskStatusUpdateEvent"
        and e.status.state == TaskState.TASK_STATE_WORKING
    ]
    assert status_updates, "a streaming:true agent must emit a non-final status-update during _execute"
    # The analysis still completes normally.
    assert result.get("risk_level") == "low"
