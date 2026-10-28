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

"""Tests for the commit gate and the tool filter of ``PrometheusMemoryService``."""

import json

import pytest
from google.adk.events.event import Event
from google.adk.sessions.session import Session
from google.genai import types

from prometheus_api.adk.memory import (
    EXECUTION_STATUS_STATE_KEY,
    SKILL_ID_STATE_KEY,
    PrometheusMemoryService,
)

ROLE = "geometry"
USER = "user-1"


def _run_session(
    *, invocation_id: str, skill_id: str, status: str, params: dict, tools: list[str]
) -> Session:
    """Build a session whose one run sends ``params`` and calls ``tools`` in order."""
    events = [
        Event(
            invocation_id=invocation_id,
            author="user",
            content=types.Content(role="user", parts=[types.Part(text=json.dumps(params))]),
        ),
        *(
            Event(
                invocation_id=invocation_id,
                author=ROLE,
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))],
                ),
            )
            for name in tools
        ),
    ]
    return Session(
        id=f"session-{invocation_id}",
        app_name=ROLE,
        user_id=USER,
        state={SKILL_ID_STATE_KEY: skill_id, EXECUTION_STATUS_STATE_KEY: status},
        events=events,
    )


async def _procedures(service: PrometheusMemoryService) -> list[dict]:
    response = await service.search_memory(app_name=ROLE, user_id=USER, query="")
    return [dict(entry.custom_metadata) for entry in response.memories]


async def test_memory_commits_successful_runs():
    """Covers REQ-016-08."""
    service = PrometheusMemoryService("sqlite+aiosqlite://", tools=["read_file", "run_cubit"])
    mesh_params = {"geometry": "pin", "mesh_size": 0.1}

    await service.add_session_to_memory(
        _run_session(
            invocation_id="inv-ok",
            skill_id="mesh",
            status="succeeded",
            params=mesh_params,
            tools=["read_file", "run_cubit"],
        )
    )
    await service.add_session_to_memory(
        _run_session(
            invocation_id="inv-fail",
            skill_id="mesh",
            status="failed",
            params=mesh_params,
            tools=["read_file"],
        )
    )
    await service.add_session_to_memory(
        _run_session(
            invocation_id="inv-read",
            skill_id="summarize",
            status="succeeded",
            params={"path": "report.txt"},
            tools=["read_file"],
        )
    )

    mesh = [p for p in await _procedures(service) if p["task_signature"].startswith("mesh:")]
    assert mesh == [
        {
            "task_signature": "mesh:geometry,mesh_size",
            "steps": ["read_file", "run_cubit"],
            "required_tools": ["read_file", "run_cubit"],
            "successes": 1,
            "failures": 1,
        }
    ], "REQ-016-08: a failed run counts a failure and never stores a second procedure"

    service.set_tools(["read_file"])
    signatures = [p["task_signature"] for p in await _procedures(service)]
    assert signatures == ["summarize:path"], (
        "REQ-016-08: search drops the procedure that needs run_cubit"
    )


async def test_memory_add_memory_is_not_implemented():
    """Covers REQ-016-08."""
    service = PrometheusMemoryService("sqlite+aiosqlite://")
    with pytest.raises(NotImplementedError):
        await service.add_memory(app_name=ROLE, user_id=USER, memories=[])
