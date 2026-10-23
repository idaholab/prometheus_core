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

"""Validate .env.example completeness and cross-references with docker-compose.yml."""

import importlib.util
from pathlib import Path

import pytest


def _load_init_env():
    path = Path(__file__).resolve().parents[2] / "scripts" / "init_env.py"
    spec = importlib.util.spec_from_file_location("init_env", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    """Required secrets ship blank; scripts/init_env.py fills each from the
    python3 one-liner in its comment block, so every one must have one."""
    init_env = _load_init_env()
    gens = init_env.generators(env_example_path.read_text())
    missing = [v for v in REQUIRED_VARS if v != "LLM_API_KEY" and v not in gens]
    assert not missing, f"Required secrets without a generator one-liner: {missing}"


def test_init_env_fills_secrets_and_checks_llm_key(tmp_path, env_example_path, monkeypatch):
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_CONFIG_PROFILE", raising=False)
    llm_vars = ("LLM_API_KEY", "LLM_CONFIG_PROFILE")

    assert init_env.main() == 1  # LLM_CONFIG_PROFILE and LLM_API_KEY still blank
    first = init_env.values(env.read_text())
    assert all(first[v] for v in REQUIRED_VARS if v != "LLM_API_KEY")

    env.write_text(env.read_text().replace("LLM_CONFIG_PROFILE=\n", "LLM_CONFIG_PROFILE=anthropic\n"))
    assert init_env.main() == 1  # LLM_API_KEY still blank

    env.write_text(env.read_text().replace("LLM_API_KEY=\n", "LLM_API_KEY=sk-ant-x\n"))
    assert init_env.main() == 0
    second = init_env.values(env.read_text())
    assert {k: v for k, v in second.items() if k not in llm_vars} == {
        k: v for k, v in first.items() if k not in llm_vars
    }, "existing values must never be overwritten"


def test_init_env_requires_a_profile(tmp_path, env_example_path, monkeypatch, capsys):
    """There is no default profile: a blank one fails, even with a key set."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.delenv("LLM_CONFIG_PROFILE", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")

    assert init_env.main() == 1
    assert "LLM_CONFIG_PROFILE is empty" in capsys.readouterr().err

    env.write_text(env.read_text().replace("LLM_CONFIG_FILE=\n", "LLM_CONFIG_FILE=/custom.yaml\n"))
    assert init_env.main() == 0  # a custom YAML replaces the profile


def test_init_env_takes_llm_key_from_environment(tmp_path, env_example_path, monkeypatch):
    """CI sets LLM_CONFIG_PROFILE and LLM_API_KEY in the environment instead of answering the prompt."""
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)
    monkeypatch.setenv("LLM_CONFIG_PROFILE", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")

    assert init_env.main() == 0
    written = init_env.values(env.read_text())
    assert written["LLM_CONFIG_PROFILE"] == "anthropic"
    assert written["LLM_API_KEY"] == "sk-from-env"

    # A key already in .env wins over the environment
    monkeypatch.setenv("LLM_API_KEY", "sk-other")
    assert init_env.main() == 0
    assert init_env.values(env.read_text())["LLM_API_KEY"] == "sk-from-env"


def test_init_env_prompts_for_profile_and_key(tmp_path, env_example_path, monkeypatch):
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: True)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(init_env, "choose", lambda options, labels, default: "openai")
    monkeypatch.setattr(init_env.getpass, "getpass", lambda prompt: "sk-openai-x")

    assert init_env.main() == 0
    written = init_env.values(env.read_text())
    assert written["LLM_CONFIG_PROFILE"] == "openai"
    assert written["LLM_API_KEY"] == "sk-openai-x"


def test_init_env_rejects_unknown_profile(tmp_path, env_example_path, monkeypatch, capsys):
    init_env = _load_init_env()
    example = tmp_path / ".env.example"
    example.write_text(env_example_path.read_text())
    env = tmp_path / ".env"
    env.write_text(
        example.read_text()
        .replace("LLM_CONFIG_PROFILE=\n", "LLM_CONFIG_PROFILE=genisis\n")
        .replace("LLM_API_KEY=\n", "LLM_API_KEY=sk-x\n")
    )
    monkeypatch.setattr(init_env, "EXAMPLE", example)
    monkeypatch.setattr(init_env, "ENV", env)
    monkeypatch.setattr(init_env, "interactive", lambda: False)

    assert init_env.main() == 1
    err = capsys.readouterr().err
    assert "LLM_CONFIG_PROFILE=genisis" in err
    assert "anthropic" in err

    env.write_text(env.read_text().replace("LLM_CONFIG_PROFILE=genisis\n", "LLM_CONFIG_PROFILE=registry\n"))
    assert init_env.main() == 1
    assert "LLM_CONFIG_PROFILE=registry" in capsys.readouterr().err  # installed by the SDK, but no proxy here

    env.write_text(env.read_text().replace("LLM_CONFIG_FILE=\n", "LLM_CONFIG_FILE=/custom.yaml\n"))
    assert init_env.main() == 0  # a custom YAML replaces the profile


def test_profiles_match_sdk_llm_configs():
    """Every installed profile but "registry" is offered; all but the keyless ollama read LLM_API_KEY."""
    init_env = _load_init_env()
    known = init_env.profiles()
    installed = {p.stem for p in init_env.LLM_CONFIGS.glob("*.yaml")}
    assert list(known) == sorted(installed - {"registry"})
    # EMBEDDING_API_KEY is never the profile key. Only the keyless local ollama
    # profile (api_key: none) needs no key at all.
    keys = {name: key for name, (key, _) in known.items()}
    assert [name for name, key in keys.items() if key is None] == ["ollama"]
    for name, key in keys.items():
        if name != "ollama":
            assert key == "LLM_API_KEY", f"{name} must read LLM_API_KEY"


def test_port_vars_have_values(env_example_vars):
    """Port variables should have values defined in .env.example."""
    port_vars = [
        "REDIS_LOCAL_PORT",
        "CLIENT_AGENT_PORT",
        "BACKEND_PORT",
    ]
    missing = [v for v in port_vars if v not in env_example_vars]
    assert not missing, f"Port variables missing from .env.example: {missing}"
