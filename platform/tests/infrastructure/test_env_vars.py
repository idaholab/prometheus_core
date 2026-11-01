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

"""Validate .env.example completeness and cross-references with docker-compose.yml.

The behaviour of `config init` (filling secrets, the profile menu, file modes) is tested with the
tool, in platform/ctl/tests/unit. This file tests `.env.example` itself.
"""

import sys
from pathlib import Path

import pytest

# The tool is standard library only, so the infra tests can import its generator code directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ctl"))

from platformctl.system import envfile  # noqa: E402

REQUIRED_VARS = [
    "LLM_API_KEY",
    "AGENT_SECRET",
    "REDIS_PASSWORD",
    "BACKEND_JWT_SECRET",
    "ADMIN_DB_PASSWORD",
    "ADMIN_DB_ENCRYPTION_KEY",
]

LLM_CONFIG_VARS = [
    "LLM_CONFIG_PROFILE",
    "LLM_CONFIG_FILE",
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
]


def test_env_example_exists(env_example_path):
    assert env_example_path.exists(), ".env.example file does not exist"


@pytest.mark.parametrize("var", REQUIRED_VARS)
def test_required_var_present(env_example_vars, var):
    assert var in env_example_vars, f"Required variable '{var}' missing from .env.example"


@pytest.mark.parametrize("var", LLM_CONFIG_VARS)
def test_llm_config_var_present(env_example_vars, var):
    assert var in env_example_vars, f"LLM configuration variable '{var}' missing from .env.example"


def test_all_compose_var_refs_have_entry_or_default(compose_var_refs, env_example_vars):
    """Every ${VAR} in docker-compose.yml without a :-default must exist in .env.example.

    Well-known optional vars (proxy settings) are excluded since they are
    intentionally commented out in .env.example and only needed behind a corporate proxy.
    """
    optional_vars = {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
    missing = []
    for var_name, has_default in compose_var_refs:
        if not has_default and var_name not in env_example_vars and var_name not in optional_vars:
            missing.append(var_name)
    assert not missing, f"Compose references without defaults or .env.example entry: {missing}"


def test_required_secrets_have_generator(env_example_path):
    """Required secrets ship blank; `./platformctl config init` fills each from the
    python3 one-liner in its comment block, so every one must have one."""
    gens = envfile.generators(env_example_path.read_text())
    missing = [v for v in REQUIRED_VARS if v != "LLM_API_KEY" and v not in gens]
    assert not missing, f"Required secrets without a generator one-liner: {missing}"


def test_port_vars_have_values(env_example_vars):
    """Port variables should have values defined in .env.example."""
    port_vars = [
        "REDIS_LOCAL_PORT",
        "CLIENT_AGENT_PORT",
        "BACKEND_PORT",
    ]
    missing = [v for v in port_vars if v not in env_example_vars]
    assert not missing, f"Port variables missing from .env.example: {missing}"
