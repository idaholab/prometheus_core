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

"""Provider-agnostic LLM client integration tests for the orchestrator."""

from __future__ import annotations

from orchestrator import runtime


def test_runtime_client_preserves_direct_profile_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "direct.yaml"
    config_path.write_text(
        """
model_list:
  - model_name: medium
    litellm_params:
      model: openai/test-model
      api_key: os.environ/LLM_API_KEY
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("LLM_API_KEY", "provider-key")

    client = runtime.create_llm()
    medium = client.config.load_fallback_models()["medium"]

    assert client.config.proxy_url is None
    assert client.config.api_key is None
    assert medium.litellm_params["api_key"] == "provider-key"
