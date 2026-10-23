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

"""Tests for thermal agent INPUT_REQUIRED behavior."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue
from a2a.types import TaskStatusUpdateEvent, TaskState
from google.protobuf.json_format import MessageToDict

THERMAL_DIR = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location("thermal_agent_module", THERMAL_DIR / "agent.py")
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
ThermalAnalysisAgent = _MODULE.ThermalAnalysisAgent


def test_thermal_agent_requests_temperature():
    agent = ThermalAnalysisAgent(agent_name="Thermal Analysis Agent")
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-1"
    context.context_id = "ctx-1"
    context.message = MagicMock(parts=[])
    queue = AsyncMock(spec=EventQueue)

    result = asyncio.run(agent._execute({"material_id": "SS316"}, context, queue))

    assert result == {"status": "input_required"}
    calls = queue.enqueue_event.call_args_list
    assert len(calls) == 1
    event = calls[0][0][0]
    assert isinstance(event, TaskStatusUpdateEvent)
    assert event.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    part = event.status.message.parts[0]
    assert part.WhichOneof("content") == "data"
    payload = MessageToDict(part.data)
    assert payload["missing_inputs"][0]["name"] == "temperature_c"


def test_thermal_agent_reads_inputs_from_params():
    # Operating conditions come nested under context from the model, or top level
    # from an INPUT_REQUIRED answer, which wins.
    resolve = ThermalAnalysisAgent._resolve_inputs

    assert resolve({"material_id": "SS316", "context": {"temperature_c": 300}})["temperature_c"] == 300
    assert resolve({"material_id": "SS316", "temperature_c": 450, "context": {"temperature_c": 300}})[
        "temperature_c"
    ] == 450
    assert resolve({"material_id": "SS316", "context": "not a dict"})["temperature_c"] is None


def test_thermal_agent_resume_needs_no_saved_state():
    # On resume the client-agent re-sends every argument plus the answer, so the
    # agent proceeds past the temperature prompt from params alone.
    agent = ThermalAnalysisAgent(agent_name="Thermal Analysis Agent")
    agent.load_context_state = MagicMock(side_effect=AssertionError("no saved state needed"))
    agent.send_status_update = AsyncMock()
    agent.send_json_artifact = AsyncMock()
    context = MagicMock(spec=RequestContext)
    context.task_id = "task-1"
    context.context_id = "ctx-1"
    queue = AsyncMock(spec=EventQueue)

    result = asyncio.run(agent._execute({"material_id": "SS316", "temperature_c": 450}, context, queue))

    assert result.get("status") != "input_required"
    assert not any(
        call.args[0].status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        for call in queue.enqueue_event.call_args_list
        if isinstance(call.args[0], TaskStatusUpdateEvent)
    )
