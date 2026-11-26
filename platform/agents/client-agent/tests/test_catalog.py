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

"""Unit tests for the orchestration tool catalog helpers."""

from types import SimpleNamespace

from orchestration.catalog import _skill_spec, _tool_name, _unique_tool_name


def _capability(**overrides) -> SimpleNamespace:
    fields = {
        "agent_id": "thermal-agent",
        "agent_name": "thermal-agent",
        "skill_id": "analyze_thermal",
        "skill_name": "Analyze thermal",
        "description": "Thermal screening.",
        "usage_notes": None,
        "input_schema": {"type": "object", "properties": {"power": {"type": "number"}}},
        "requires_approval": False,
        "expected_duration_seconds": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


def test_unique_tool_name_suffixes_taken_names() -> None:
    assert _unique_tool_name("run", {}) == "run"
    assert _unique_tool_name("run", {"run": 1, "run_2": 1}) == "run_3"


def test_unique_tool_name_keeps_the_64_character_limit() -> None:
    base = _tool_name("x" * 80)
    name = _unique_tool_name(base, {base: 1})
    assert len(base) == 64
    assert name == "x" * 62 + "_2"


def test_skill_spec_appends_usage_notes_to_the_description() -> None:
    spec = _skill_spec("analyze_thermal", _capability(usage_notes="Call once per core."))
    assert spec.description == "Thermal screening.\nUsage: Call once per core."
    assert spec.expected_duration_seconds == 30
