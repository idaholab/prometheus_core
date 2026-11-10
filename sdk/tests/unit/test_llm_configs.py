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

"""Tests for installed LLM configuration profiles.

The YAML files in ``prometheus_api/llm_configs/`` are the ground truth for the
available profiles; every file found there is validated against the schema
``LLMConfig`` expects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import prometheus_api.llm_configs as llm_configs
from prometheus_api.llm_client.config import LLMConfig
from prometheus_api.llm_configs import get_llm_config_path, list_llm_config_profiles


CONFIG_DIR = Path(llm_configs.__file__).resolve().parent
CONFIG_FILES = sorted(CONFIG_DIR.glob("*.yaml"))
EXPECTED_FLAVORS = {"default", "small", "medium", "large", "vision", "embedding"}
INFERENCE_KEY = "os.environ/LLM_API_KEY"
EMBEDDING_KEY = "os.environ/EMBEDDING_API_KEY"
# REQ-005-16: only keyless local providers may set ``api_key: none``.
NO_KEY = "none"
KEYLESS_PROFILES = {"ollama"}


def _load(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path.name} must contain a YAML mapping"
    return payload


def test_config_directory_holds_only_yaml_profiles():
    """REQ-005-13, REQ-013-15: only ``*.yaml`` files are installed and loadable."""
    stray = [
        path.name
        for path in CONFIG_DIR.iterdir()
        if path.is_file() and path.suffix != ".py" and path.suffix != ".yaml"
    ]
    assert not stray, f"LLM config profiles must use the .yaml extension: {stray}"
    assert "registry" in list_llm_config_profiles()


@pytest.mark.parametrize("config_path", CONFIG_FILES, ids=lambda path: path.stem)
def test_installed_profile_resolves(config_path):
    """REQ-005-13: every file in the directory is a selectable profile."""
    assert get_llm_config_path(config_path.stem) == config_path
    assert get_llm_config_path(config_path.name) == config_path


@pytest.mark.parametrize("config_path", CONFIG_FILES, ids=lambda path: path.stem)
def test_installed_profile_matches_llm_config_schema(config_path):
    """REQ-005-15, REQ-005-16: each profile is valid YAML in the LLMConfig schema."""
    payload = _load(config_path)
    assert set(payload) <= {"proxy_url", "model_list"}, f"unknown keys: {set(payload)}"
    assert "proxy_url" in payload or "model_list" in payload

    if "proxy_url" in payload:
        assert isinstance(payload["proxy_url"], str)
        assert payload["proxy_url"].startswith("os.environ/")

    if "model_list" not in payload:
        return

    models = payload["model_list"]
    assert isinstance(models, list)
    names = [entry["model_name"] for entry in models]
    assert len(names) == len(set(names)), "duplicate model_name entries"
    assert set(names) == EXPECTED_FLAVORS

    for entry in models:
        assert isinstance(entry, dict)
        params = entry["litellm_params"]
        assert isinstance(params, dict)
        assert isinstance(params.get("model"), str) and params["model"].strip()
        if config_path.stem in KEYLESS_PROFILES:
            allowed_keys = {NO_KEY}
        elif entry["model_name"] == "embedding":
            allowed_keys = {INFERENCE_KEY, EMBEDDING_KEY}
        else:
            allowed_keys = {INFERENCE_KEY}
        assert params.get("api_key") in allowed_keys, (
            f"{entry['model_name']} must read its key from {sorted(allowed_keys)}"
        )

    loaded = LLMConfig(
        config_file=config_path, proxy_url="http://unused:4000"
    ).load_fallback_models()
    assert set(loaded) == EXPECTED_FLAVORS


def test_unknown_packaged_llm_config_is_rejected():
    """REQ-005-13: arbitrary paths cannot escape the installed profile directory."""
    with pytest.raises(ValueError, match="Unknown LLM config profile"):
        get_llm_config_path("../private")
