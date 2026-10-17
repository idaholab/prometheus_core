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

"""Tests for the /agents slash command (registered agents listing)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from orchestrator import debug_commands, runtime
from orchestrator.models import ConversationRequest

CONV = "conv-agents-cmd"


class _FakeCapabilityCache:
    """Capability cache stand-in: refresh is a no-op and it holds no capabilities."""

    def __init__(self, capabilities: list[Any] | None = None) -> None:
        self._capabilities = list(capabilities or [])

    async def refresh(self) -> None:
        return None

    async def get_capabilities(self) -> list[Any]:
        return list(self._capabilities)


def _registry_agent(
    agent_id: str, name: str, skills: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """One registry entry in the shape discover_agents() returns."""
    return {
        "agent_id": agent_id,
        "name": name,
        "url": f"http://{agent_id}:8000",
        "agent_card_params": {"name": name, "skills": list(skills or [])},
    }


@pytest.fixture()
def fake_registry(monkeypatch) -> list[dict[str, Any]]:
    """Feed /agents from an in-memory registry; tests append agents to the returned list."""
    agents: list[dict[str, Any]] = []

    async def _discover_agents() -> list[dict[str, Any]]:
        return list(agents)

    cache = _FakeCapabilityCache()
    monkeypatch.setattr(debug_commands, "discover_agents", _discover_agents)
    monkeypatch.setattr(debug_commands, "get_capability_cache", lambda: cache)
    monkeypatch.setattr(runtime, "store_status_update", lambda *a, **k: None)
    return agents


def _handle(query: str):
    return asyncio.run(
        debug_commands._maybe_handle_slash_command(
            ConversationRequest(query=query, conversation_id=CONV), CONV, None, []
        )
    )


def test_agents_reply_states_order_and_sorts(
    fake_registry: list[dict[str, Any]],
) -> None:
    """The /agents reply MUST list agents ordered by case-insensitive display name,
    then by agent id, and MUST state that order in the reply."""
    fake_registry.extend(
        [
            _registry_agent("zeta-agent", "Zeta"),
            _registry_agent("beta-2", "Beta"),
            _registry_agent("alpha-agent", "alpha"),
            _registry_agent("beta-1", "Beta"),
        ]
    )

    response = _handle("/agents")

    assert response is not None
    assert response.message_metadata["slash_command"] == "agents"
    msg = response.message
    assert "Sorted by name, A to Z." in msg

    items = [line for line in msg.splitlines() if line[:1].isdigit() and ". **" in line]
    assert items == ["1. **alpha**", "2. **Beta**", "3. **Beta**", "4. **Zeta**"]
    # The two "Beta" agents are told apart by id: beta-1 is listed before beta-2.
    assert msg.index("ID: `beta-1`") < msg.index("ID: `beta-2`")
    assert (
        msg.index("1. **alpha**")
        < msg.index("ID: `alpha-agent`")
        < msg.index("2. **Beta**")
    )

    assert [entry["agent_id"] for entry in response.message_metadata["agents"]] == [
        "alpha-agent",
        "beta-1",
        "beta-2",
        "zeta-agent",
    ]


def test_agents_reply_is_nested_markdown(
    fake_registry: list[dict[str, Any]],
) -> None:
    """Each agent in the /agents reply MUST be one numbered Markdown item whose id,
    URL and skills are nested bullets indented three spaces."""
    fake_registry.append(
        _registry_agent(
            "mesh-agent",
            "Mesh Agent",
            skills=[
                {"id": "convert_mesh", "name": "Convert Mesh"},
                {"id": "inspect_mesh", "name": "Inspect Mesh"},
            ],
        )
    )

    response = _handle("/agents")

    assert response is not None
    lines = response.message.splitlines()
    for expected in (
        "1. **Mesh Agent**",
        "   - ID: `mesh-agent`",
        "   - URL: http://mesh-agent:8000",
        "   - Skills (2): `convert_mesh` (Convert Mesh), `inspect_mesh` (Inspect Mesh)",
    ):
        assert expected in lines, f"missing line {expected!r} in {lines!r}"
    assert not [line for line in lines if line.startswith(("  url:", "  skills:"))]


def test_agents_reply_empty_and_warnings(
    fake_registry: list[dict[str, Any]], monkeypatch
) -> None:
    """The /agents reply MUST say no agent is registered when none is, and MUST list
    each collection warning as a bullet under a **Warnings** label."""

    async def _failing_discover_agents() -> list[dict[str, Any]]:
        raise RuntimeError("registry unreachable")

    monkeypatch.setattr(debug_commands, "discover_agents", _failing_discover_agents)

    response = _handle("/agents")

    assert response is not None
    msg = response.message
    lines = msg.splitlines()
    assert msg.startswith(
        "**Registered agents (0)**\n\nNo registered agents were found."
    )
    assert "Sorted by name" not in msg
    assert "**Warnings**" in lines
    warning_bullets = lines[lines.index("**Warnings**") + 1 :]
    assert warning_bullets == ["", "- agent discovery failed: registry unreachable"]


def test_agents_reply_marks_agent_without_skills(
    fake_registry: list[dict[str, Any]],
) -> None:
    """An agent that advertises no skills MUST show `Skills: none advertised`."""
    fake_registry.append(_registry_agent("bare-agent", "Bare Agent"))

    response = _handle("/agents")

    assert response is not None
    lines = response.message.splitlines()
    assert lines[0] == "**Registered agents (1)**"
    assert "No registered agents were found." not in lines
    assert "   - Skills: none advertised" in lines
    assert "**Warnings**" not in lines


def test_agents_reply_shows_skill_without_id_as_bare_name(
    fake_registry: list[dict[str, Any]],
) -> None:
    """A skill with a name and no id MUST appear in the Skills line as its bare name,
    without backticks."""
    fake_registry.append(
        _registry_agent("doc-agent", "Doc Agent", skills=[{"name": "Summarize Docs"}])
    )

    response = _handle("/agents")

    assert response is not None
    lines = response.message.splitlines()
    assert "   - Skills (1): Summarize Docs" in lines, lines
    assert "`" not in next(line for line in lines if line.startswith("   - Skills"))


def test_agents_reply_indents_bullets_by_marker_width(
    fake_registry: list[dict[str, Any]],
) -> None:
    """Nested bullets MUST be indented by the width of their item's marker, so item 10
    keeps its id, URL and skills nested under it (4 spaces) while item 9 keeps 3."""
    fake_registry.extend(
        _registry_agent(f"agent-{n:02d}", f"Agent {n:02d}") for n in range(1, 10)
    )
    fake_registry.append(
        _registry_agent(
            "agent-10",
            "Agent 10",
            skills=[{"id": "convert_mesh", "name": "Convert Mesh"}],
        )
    )

    response = _handle("/agents")

    assert response is not None
    lines = response.message.splitlines()

    item_9 = lines.index("9. **Agent 09**")
    assert lines[item_9 + 1 : item_9 + 4] == [
        "   - ID: `agent-09`",
        "   - URL: http://agent-09:8000",
        "   - Skills: none advertised",
    ]

    item_10 = lines.index("10. **Agent 10**")
    assert lines[item_10 + 1 : item_10 + 4] == [
        "    - ID: `agent-10`",
        "    - URL: http://agent-10:8000",
        "    - Skills (1): `convert_mesh` (Convert Mesh)",
    ]
