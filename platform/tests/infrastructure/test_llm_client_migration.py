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

"""Enforce provider-agnostic LLM usage in runtime agents."""

from pathlib import Path

import yaml

FORBIDDEN_RUNTIME_PATTERNS = (
    "from anthropic import",
    "import anthropic",
    "from openai import",
    "import openai",
    "langchain_anthropic",
    "langchain_openai",
    "ChatAnthropic",
    "ChatOpenAI",
    "AsyncAnthropic",
    "AsyncOpenAI",
    "LLM_API_KEY =",
    "MODEL_NAME =",
)

LLM_AGENT_COMPOSE_FILES = (
    "agents/debug-agents/corrosion-agent/docker-compose.yml",
    "agents/debug-agents/material-data-agent/docker-compose.yml",
    "agents/debug-agents/radiation-agent/docker-compose.yml",
    "agents/debug-agents/thermal-agent/docker-compose.yml",
    "agents/form-filler-agent/docker-compose.yml",
    "agents/optional/osti-research-agent/docker-compose.yml",
    "agents/synthesis-agent/docker-compose.yml",
)

PROVIDER_KEY_ENV = {
    "LLM_API_KEY": "${LLM_API_KEY:-}",
    "EMBEDDING_API_KEY": "${EMBEDDING_API_KEY:-}",
}


def _runtime_agent_files(platform_root: Path):
    for path in (platform_root / "agents").rglob("*.py"):
        if "tests" not in path.parts and ".venv" not in path.parts:
            yield path


def test_runtime_agents_do_not_use_provider_sdks(project_root):
    violations = []
    for path in _runtime_agent_files(project_root):
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_RUNTIME_PATTERNS:
            if pattern in source:
                violations.append(f"{path.relative_to(project_root)}: {pattern}")

    assert not violations, "Direct provider usage remains:\n" + "\n".join(violations)


def test_agent_dependencies_do_not_install_provider_sdks(project_root):
    violations = []
    for path in (project_root / "agents").rglob("pyproject.toml"):
        source = path.read_text(encoding="utf-8").lower()
        for dependency in ('"anthropic', '"langchain-anthropic'):
            if dependency in source:
                violations.append(f"{path.relative_to(project_root)}: {dependency}")

    assert not violations, "Provider dependencies remain:\n" + "\n".join(violations)


def test_llm_agent_compose_files_receive_selectable_profiles(project_root):
    for relative_path in LLM_AGENT_COMPOSE_FILES:
        compose_data = yaml.safe_load((project_root / relative_path).read_text(encoding="utf-8"))
        services = compose_data["services"]
        assert len(services) == 1
        environment = next(iter(services.values()))["environment"]

        assert environment["REGISTRY_URL"] == "${REGISTRY_URL:-http://backend:8000}"
        assert environment["LLM_CONFIG_PROFILE"] == "${LLM_CONFIG_PROFILE:?set LLM_CONFIG_PROFILE in .env}"
        assert environment["LLM_CONFIG_FILE"] == "${LLM_CONFIG_FILE:-}"
        assert environment["LITELLM_MASTER_KEY"] == "${AGENT_SECRET}"
        assert "LLM_DEFAULT_MODEL" not in environment
        for key, expected in PROVIDER_KEY_ENV.items():
            assert environment[key] == expected


def test_runtime_agents_do_not_attach_the_litellm_proxy_key(project_root):
    """The platform has no LLM proxy, so no agent swaps its profile's key for LITELLM_MASTER_KEY."""
    violations = []
    for path in _runtime_agent_files(project_root):
        source = path.read_text(encoding="utf-8")
        if "with_api_key(" in source:
            violations.append(f"{path.relative_to(project_root)}: with_api_key")

    assert not violations, "Proxy-key configuration remains:\n" + "\n".join(violations)


def test_osti_runtime_does_not_force_model_temperature(project_root):
    root = project_root / "agents" / "optional" / "osti-research-agent"
    violations = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts or ".venv" in path.parts:
            continue
        if "temperature=" in path.read_text(encoding="utf-8").replace(" ", ""):
            violations.append(str(path.relative_to(project_root)))

    assert not violations, "OSTI runtime forces model temperature:\n" + "\n".join(violations)
