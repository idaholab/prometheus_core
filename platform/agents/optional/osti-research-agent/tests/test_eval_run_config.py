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

import asyncio
from types import SimpleNamespace

import pytest

from evals import run as eval_run
from evals.run import _configured_agent_config, _redis_url_with_db
from research_agent.core.config import AgentConfig


class _RegistryConfig:
    proxy_url = "http://registry.example:4000"
    api_key = None

    def with_api_key(self, api_key):
        return SimpleNamespace(proxy_url=self.proxy_url, api_key=api_key)


class _DirectConfig:
    proxy_url = None

    @staticmethod
    def load_fallback_models():
        def model(alias, provider_model):
            return SimpleNamespace(
                alias=alias,
                provider_model=provider_model,
                litellm_params={
                    "api_base": "https://direct.example/v1",
                    "api_key": "direct-key",
                },
            )

        return {
            "medium": model("medium", "openai/research-model"),
            "embedding": model("embedding", "openai/embedding-model"),
        }


def test_eval_profile_with_a_proxy_url_keeps_its_own_key(monkeypatch):
    # The platform no longer has an LLM proxy (26e196dd): the profile's key is
    # used as-is, never swapped for LITELLM_MASTER_KEY.
    monkeypatch.setenv("REGISTRY_URL", "http://stale-registry:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "registry-key")

    config = _configured_agent_config(_RegistryConfig())

    route = config.model_route("orchestrator")
    assert route.base_url == "http://registry.example:4000"
    assert route.api_key is None
    assert route.model == "medium"


def test_eval_direct_profile_uses_resolved_routes(monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://unused-registry:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "unused-registry-key")

    config = _configured_agent_config(_DirectConfig())

    assert config.model_route("orchestrator").model == "research-model"
    assert config.model_route("orchestrator").api_key == "direct-key"
    assert config.model_route("embedding").model == "embedding-model"


def test_eval_redis_databases_are_isolated_without_losing_connection_details():
    url = "rediss://user:secret@redis.example:6380/3?ssl_cert_reqs=required"

    assert _redis_url_with_db(url, 14) == (
        "rediss://user:secret@redis.example:6380/14?ssl_cert_reqs=required"
    )
    assert _redis_url_with_db(url, 15) == (
        "rediss://user:secret@redis.example:6380/15?ssl_cert_reqs=required"
    )


def _single_engine_main(tmp_path, monkeypatch, *extra):
    questions = tmp_path / "questions.yaml"
    questions.write_text("questions:\n  - id: one\n    question: Test question?\n")
    calls = []
    monkeypatch.setattr(
        eval_run,
        "_load_agent_config",
        lambda: AgentConfig(litellm_base_url="http://unused", redis_url="redis://redis:6379"),
    )

    async def fake_run_engine(engine, specs, base, workdir, redis_db, on_record=None, **kwargs):
        calls.append((engine, redis_db))
        return []

    monkeypatch.setattr(eval_run, "_run_engine", fake_run_engine)
    result = asyncio.run(eval_run._main([
        "--questions", str(questions), "--report", str(tmp_path / "report.json"),
        "--no-judge", *extra,
    ]))
    return result, calls


def test_eval_runs_the_deep_engine_by_default(tmp_path, monkeypatch):
    result, calls = _single_engine_main(tmp_path, monkeypatch)

    assert result == 0 and calls == [("deepagent", None)]


def test_redis_db_base_isolates_the_eval_from_the_live_cache(tmp_path, monkeypatch):
    result, calls = _single_engine_main(tmp_path, monkeypatch, "--redis-db-base", "14")

    assert result == 0 and calls == [("deepagent", 14)]


def test_the_removed_pipeline_engine_is_rejected(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _single_engine_main(tmp_path, monkeypatch, "--engines", "pipeline")