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

"""Tests for parsing-related environment configuration and boolean values."""

from research_agent.core.config import AgentConfig, _env_bool


def test_from_env_reads_phase2_flags(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://reg:4000")
    monkeypatch.setenv("PARSE_OCR", "on")
    monkeypatch.setenv("ANALYZE_FIGURES", "true")
    monkeypatch.setenv("ANALYZER_MODEL_CALL_LIMIT", "6")
    monkeypatch.setenv("ANALYZER_TOOL_CALL_LIMIT", "10")
    monkeypatch.setenv("VERIFIER_MODEL_CALL_LIMIT", "14")
    monkeypatch.setenv("VERIFIER_TOOL_CALL_LIMIT", "20")
    monkeypatch.setenv("TOTAL_BUDGET_S", "600")
    monkeypatch.setenv("MAX_PAPERS_ANALYZED", "4")
    monkeypatch.setenv("MAX_PDF_MB", "40")
    monkeypatch.setenv("DOCLING_TIMEOUT_S", "180")
    monkeypatch.setenv("DOCLING_IMAGES_SCALE", "1.0")
    monkeypatch.setenv("DOCLING_TABLE_MODE", "FAST")
    monkeypatch.setenv("MAX_FIGURES", "8")
    monkeypatch.setenv("MIN_FIGURE_AREA", "20000")

    cfg = AgentConfig.from_env()

    assert cfg.parse_ocr == "on"
    assert cfg.analyze_figures is True
    assert cfg.analyzer_model_call_limit == 6
    assert cfg.analyzer_tool_call_limit == 10
    assert cfg.verifier_model_call_limit == 14
    assert cfg.verifier_tool_call_limit == 20
    assert cfg.total_budget_s == 600
    assert cfg.max_papers_analyzed == 4
    assert cfg.max_pdf_mb == 40
    assert cfg.docling_timeout_s == 180
    assert cfg.docling_images_scale == 1.0
    assert cfg.docling_table_mode == "fast"
    assert cfg.max_figures == 8
    assert cfg.min_figure_area == 20000


def test_from_env_phase2_defaults(monkeypatch):
    for var in (
        "PARSE_OCR",
        "ANALYZE_FIGURES",
        "ANALYZER_MODEL_CALL_LIMIT",
        "ANALYZER_TOOL_CALL_LIMIT",
        "VERIFIER_MODEL_CALL_LIMIT",
        "VERIFIER_TOOL_CALL_LIMIT",
        "TOTAL_BUDGET_S",
        "MAX_PAPERS_ANALYZED",
        "MAX_PDF_MB",
        "DOCLING_TIMEOUT_S",
        "DOCLING_IMAGES_SCALE",
        "DOCLING_TABLE_MODE",
        "MAX_FIGURES",
        "MIN_FIGURE_AREA",
        "LITELLM_BASE_URL",
        "REGISTRY_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = AgentConfig.from_env()

    assert cfg.parse_ocr == "auto"
    assert cfg.analyze_figures is False
    assert cfg.analyzer_model_call_limit == 8
    assert cfg.analyzer_tool_call_limit == 12
    assert cfg.verifier_model_call_limit == 10
    assert cfg.verifier_tool_call_limit == 12
    assert cfg.total_budget_s == 900
    assert cfg.max_papers_analyzed == 5
    assert cfg.max_pdf_mb == 50
    assert cfg.docling_timeout_s == 240
    assert cfg.docling_images_scale == 2.0
    assert cfg.docling_table_mode == "accurate"
    assert cfg.max_figures == 12
    assert cfg.min_figure_area == 10_000


def test_env_bool(monkeypatch):
    for truthy in ("1", "true", "TRUE", "yes", "on", " On "):
        monkeypatch.setenv("X_TEST_BOOL", truthy)
        assert _env_bool("X_TEST_BOOL", default=False) is True

    monkeypatch.setenv("X_TEST_BOOL", "nope")
    assert _env_bool("X_TEST_BOOL", default=True) is False

    monkeypatch.delenv("X_TEST_BOOL", raising=False)
    assert _env_bool("X_TEST_BOOL", default=True) is True
    assert _env_bool("X_TEST_BOOL", default=False) is False


def test_docling_memory_settings_are_validated():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentConfig(litellm_base_url="http://u", docling_images_scale=0)
    with pytest.raises(ValidationError):
        AgentConfig(litellm_base_url="http://u", docling_table_mode="turbo")
