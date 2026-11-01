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

"""The status lines the frontend parses are the ones this agent emits.

The frontend's Agents tab and Active Jobs tab read the verbatim status strings
(``parseAgentStream.ts``, ``activeJobs.ts``). Both sides test against one shared
fixture, ``platform/frontend/src/lib/agentPanel/statusLines.fixture.json``: the
frontend parses every rendered example there, and these tests assert the
client-agent emits exactly those rendered examples. Rewording a line here
without updating the fixture (and so the parser) fails this suite.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import runtime_stub  # noqa: F401  (installs prometheus_api.agent stubs)

import task_graph
from orchestrator import runtime, skills

PLATFORM_DIR = Path(__file__).resolve().parents[3]
FIXTURE = PLATFORM_DIR / "frontend" / "src" / "lib" / "agentPanel" / "statusLines.fixture.json"


def _lines() -> Dict[str, Dict[str, Any]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in data["lines"]}


LINES = _lines()


def rendered(line_id: str, **override: str) -> str:
    entry = LINES[line_id]
    return entry["template"].format(**{**entry["example"], **override})


def _capture(monkeypatch) -> List[str]:
    emitted: List[str] = []
    monkeypatch.setattr(runtime, "store_status_update", lambda _conv, msg, **_kw: emitted.append(msg))
    return emitted


def _stub_skill(monkeypatch, tool: Any, *, streaming: bool = False) -> None:
    async def find_tool(*_args, **_kwargs):
        return tool

    async def get_capability(_skill_id):
        return SimpleNamespace(input_schema={"type": "object", "properties": {}}, supports_streaming=streaming)

    monkeypatch.setattr(skills, "find_tool_for_skill", find_tool)
    monkeypatch.setattr(
        skills, "get_capability_cache", lambda: SimpleNamespace(get_capability_by_skill_id=get_capability)
    )


SKILL = LINES["invoking"]["example"]["skill"]


def test_fixture_covers_every_in_repo_producer_file() -> None:
    for entry in LINES.values():
        producer = entry["producer"]
        if producer.startswith("external:"):
            continue
        assert (PLATFORM_DIR.parent / producer).is_file(), producer


def test_a_successful_streaming_dispatch_emits_invoking_progress_completed(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    message = LINES["progress"]["example"]["message"]

    class _Tool:
        async def ainvoke(self, params):
            await params["_status_callback"](message)
            return {"ok": True}

    _stub_skill(monkeypatch, _Tool(), streaming=True)
    asyncio.run(skills.invoke_skill(SKILL, {}, "conv-1"))

    assert emitted == [rendered("invoking"), rendered("progress"), rendered("completed")]


def test_a_dispatch_that_raises_emits_the_failed_line(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    error = LINES["failed"]["example"]["error"]

    class _Tool:
        async def ainvoke(self, _params):
            raise RuntimeError(error)

    _stub_skill(monkeypatch, _Tool())
    asyncio.run(skills.invoke_skill(SKILL, {}, "conv-1"))

    assert emitted[0] == rendered("invoking")
    assert rendered("failed") in emitted


def test_a_missing_capability_emits_the_unavailable_line(monkeypatch) -> None:
    emitted = _capture(monkeypatch)
    _stub_skill(monkeypatch, None)
    asyncio.run(skills.invoke_skill(SKILL, {}, "conv-1"))

    assert emitted == [rendered("invoking"), rendered("unavailable")]


def test_a_backgrounded_root_reports_the_deepest_dispatch_as_waiting_on(monkeypatch) -> None:
    skill = LINES["waiting_on"]["example"]["skill"]
    message = LINES["waiting_on"]["example"]["message"]
    child = SimpleNamespace(waiting_on=[], title=skill, agent=None, last_status_message=message)
    root = SimpleNamespace(waiting_on=["child"], last_status_message="")
    monkeypatch.setattr(task_graph, "get_node", lambda _conv, task_id: child if task_id == "child" else None)

    assert task_graph._deepest_blocking_message("conv-1", root) == rendered("waiting_on")


def _source_pattern(template: str) -> re.Pattern[str]:
    """The template as it appears in an f-string: each ``{field}`` matches any ``{expr}``."""
    parts = re.split(r"\{[a-z_]+\}", template)
    return re.compile(r"\{[^{}]+\}".join(re.escape(p) for p in parts))


@pytest.mark.parametrize(
    "line_id", ["next_step", "response_ready", "awaiting_info", "plan_ready", "plan_rejected", "background_complete"]
)
def test_the_producer_source_still_emits_the_line(line_id: str) -> None:
    """Lines emitted from deep inside the turn loop are checked in their producer's source."""
    entry = LINES[line_id]
    source = (PLATFORM_DIR.parent / entry["producer"]).read_text(encoding="utf-8")
    assert _source_pattern(entry["template"]).search(source), f"{entry['template']!r} not in {entry['producer']}"
