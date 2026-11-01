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

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import setup_agent  # noqa: E402


def test_create_agent_copies_prompt_and_workflow_template_dirs(tmp_path, monkeypatch):
    output_dir = tmp_path / "generated-agent"
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing-platform.env")

    setup_agent.create_agent(
        {
            "TEMPLATE_NAME": "Demo Agent",
            "TEMPLATE_DESCRIPTION": "A demo generated agent",
            "TEMPLATE_SLUG": "demo-agent",
            "TEMPLATE_CLASS": "Demo",
            "TEMPLATE_SKILL_ID": "demo_analysis",
            "TEMPLATE_SKILL_NAME": "Demo Analysis",
            "TEMPLATE_SKILL_DESCRIPTION": "Runs demo analysis",
            "OUTPUT_DIR": str(output_dir),
            "TRIM_COMMENTS": "false",
        }
    )

    assert (output_dir / "prompts" / "README.md").is_file()
    assert (output_dir / "prompts" / "system_prompt.txt").is_file()
    assert (output_dir / "workflows" / "README.md").is_file()
    workflow_example = output_dir / "workflows" / "example_workflow.yaml.example"
    assert workflow_example.is_file()
    assert "id: demo-agent.example_workflow" in workflow_example.read_text(encoding="utf-8")
    assert "skill_id: demo_analysis" in workflow_example.read_text(encoding="utf-8")
    assert (output_dir / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
    assert not (output_dir / "uv.lock").exists()
    assert "**/__pycache__" in (output_dir / ".dockerignore").read_text(encoding="utf-8")

    dockerfile = (output_dir / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY prompts /app/prompts" in dockerfile
    assert "COPY workflows /app/workflows" in dockerfile

    agent_py = (output_dir / "agent.py").read_text(encoding="utf-8")
    assert "from prometheus_api import load_prompt" in agent_py
    assert "PROMPTS_DIR" not in agent_py
    assert "def load_prompt(" not in agent_py
    assert "add_http_endpoint" in agent_py
    assert "add_static_endpoint" in agent_py


def test_select_platform_env_values_includes_identity_verification_keys(tmp_path):
    """USER_IDENTITY_PUBLIC_KEY/ISS/AUD must be copied from the platform .env --
    a scaffolded agent should be able to verify platform users out of the box,
    without the developer having to hunt these down manually. The private key
    must NEVER be selected: this agent verifies, it never mints."""
    platform_env = tmp_path / "platform.env"
    platform_env.write_text(
        "AGENT_SECRET=shared-secret\n"
        "REDIS_PASSWORD=redis-pw\n"
        "USER_IDENTITY_PRIVATE_KEY=should-never-be-copied\n"
        "USER_IDENTITY_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----abc-----END PUBLIC KEY-----\n"
        "USER_IDENTITY_ISS=prometheus-platform\n"
        "USER_IDENTITY_AUD=prometheus-agents\n"
        "DEEPLYNX_ORG_ID=42\n",
        encoding="utf-8",
    )

    selected = setup_agent.select_platform_env_values(platform_env)

    assert selected["USER_IDENTITY_PUBLIC_KEY"] == "-----BEGIN PUBLIC KEY-----abc-----END PUBLIC KEY-----"
    assert selected["USER_IDENTITY_ISS"] == "prometheus-platform"
    assert selected["USER_IDENTITY_AUD"] == "prometheus-agents"
    assert "USER_IDENTITY_PRIVATE_KEY" not in selected
    assert selected["DEEPLYNX_ORG_ID"] == "42"


def test_select_platform_env_values_copies_only_deeplynx_client_keys(tmp_path):
    """The platform .env also holds the local DeepLynx server's own secrets
    (DB password, JWT and encryption keys) and ports. An agent only needs the
    client settings, so none of the server values may be copied."""
    client = {key: f"{key.lower()}-value" for key in setup_agent.PLATFORM_DEEPLYNX_KEYS}
    server = (
        "DEEPLYNX_DB_PASSWORD",
        "DEEPLYNX_JWT_SECRET",
        "DEEPLYNX_ENCRYPTION_KEY",
        "DEEPLYNX_ENCRYPTION_IV",
        "DEEPLYNX_UI_SECRET",
        "DEEPLYNX_SERVER_PORT",
        "DEEPLYNX_UI_PORT",
    )
    platform_env = tmp_path / "platform.env"
    platform_env.write_text(
        "".join(f"{key}={value}\n" for key, value in client.items())
        + "".join(f"{key}=server-only\n" for key in server),
        encoding="utf-8",
    )

    selected = setup_agent.select_platform_env_values(platform_env)

    assert selected == client


def test_platform_deeplynx_keys_cover_template_compose():
    """Every DEEPLYNX_* the template compose file reads must be copied, so
    adding one there without adding it to the list fails here."""
    compose = (ROOT / "agent_template" / "docker-compose.yml").read_text(encoding="utf-8")
    read_keys = set(re.findall(r"\$\{(DEEPLYNX_[A-Z_]+)", compose))

    assert read_keys
    assert read_keys <= set(setup_agent.PLATFORM_DEEPLYNX_KEYS)


def test_select_platform_env_values_includes_llm_config_profile(tmp_path):
    """The platform's inference routing must carry over to a scaffolded agent.

    The template has no default LLM_CONFIG_PROFILE, so a generated agent that
    didn't inherit it would fail to start. The
    template deliberately ships no MODEL_NAME -- the profile maps the semantic
    flavors the agent asks for in code onto concrete models."""
    platform_env = tmp_path / "platform.env"
    platform_env.write_text(
        "AGENT_SECRET=shared-secret\nLLM_CONFIG_PROFILE=inl_hpc\nMODEL_NAME=should-not-matter\n",
        encoding="utf-8",
    )

    selected = setup_agent.select_platform_env_values(platform_env)

    assert selected["LLM_CONFIG_PROFILE"] == "inl_hpc"
    assert "MODEL_NAME" not in selected


def test_select_platform_env_values_points_at_local_base_image_with_local_sdk(tmp_path, monkeypatch):
    """A LOCAL_SDK=true platform runs the SDK from its checkout, so the agent
    must build FROM the base image the platform built locally, not the registry."""
    monkeypatch.delenv("LOCAL_SDK", raising=False)
    platform_env = tmp_path / "platform.env"
    platform_env.write_text("AGENT_SECRET=shared-secret\nLOCAL_SDK=true\n", encoding="utf-8")

    selected = setup_agent.select_platform_env_values(platform_env)

    assert selected["LOCAL_SDK"] == "true"
    assert "PROMETHEUS_API_BASE_IMAGE_REPO" not in selected


def test_select_platform_env_values_reads_local_sdk_from_environment(tmp_path, monkeypatch):
    """`LOCAL_SDK=true make up` (or an exported LOCAL_SDK) never lands in
    platform/.env, so the scaffolder must also check the environment."""
    monkeypatch.setenv("LOCAL_SDK", "true")
    platform_env = tmp_path / "platform.env"
    platform_env.write_text("AGENT_SECRET=shared-secret\n#LOCAL_SDK=false\n", encoding="utf-8")

    selected = setup_agent.select_platform_env_values(platform_env)

    assert selected["LOCAL_SDK"] == "true"


def test_select_platform_env_values_prefers_platform_env_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_SDK", "true")
    platform_env = tmp_path / "platform.env"
    platform_env.write_text("AGENT_SECRET=shared-secret\nLOCAL_SDK=false\n", encoding="utf-8")

    selected = setup_agent.select_platform_env_values(platform_env)

    assert "LOCAL_SDK" not in selected


def test_select_platform_env_values_leaves_base_image_alone_without_local_sdk(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCAL_SDK", raising=False)
    platform_env = tmp_path / "platform.env"
    platform_env.write_text("AGENT_SECRET=shared-secret\nLOCAL_SDK=false\n", encoding="utf-8")

    selected = setup_agent.select_platform_env_values(platform_env)

    assert "LOCAL_SDK" not in selected


def _feed_input(monkeypatch, answers):
    """Answer the scaffolder's prompts in order; fail on an unexpected prompt."""
    prompts = []
    remaining = iter(answers)

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(remaining)

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_collect_agent_info_uses_command_line_name_and_output_dir(monkeypatch):
    """Both positional arguments are used as given and are not prompted for."""
    # description, slug, class, skill id, skill name, skill description, trim, confirm
    prompts = _feed_input(monkeypatch, ["", "", "", "", "", "", "", "yes"])

    info = setup_agent.collect_agent_info("Plant Analysis", "./plant-agent")

    assert info["TEMPLATE_NAME"] == "Plant Analysis"
    assert info["TEMPLATE_SLUG"] == "plant-analysis"
    assert info["OUTPUT_DIR"] == "./plant-agent"
    assert not any("Agent name" in p or "Output directory" in p for p in prompts)


def test_collect_agent_info_prompts_for_output_dir_when_only_name_given(monkeypatch):
    prompts = _feed_input(monkeypatch, ["", "", "", "", "", "", "", "", "yes"])

    info = setup_agent.collect_agent_info("Data Validator")

    assert info["OUTPUT_DIR"] == "../data-validator"
    assert any("Output directory" in p for p in prompts)
    assert not any("Agent name" in p for p in prompts)


def test_main_passes_positional_arguments_through(monkeypatch):
    received = {}
    monkeypatch.setattr(
        setup_agent,
        "collect_agent_info",
        lambda agent_name, output_dir, assume_defaults: (
            received.update(name=agent_name, out=output_dir, yes=assume_defaults) or {}
        ),
    )
    monkeypatch.setattr(setup_agent, "create_agent", lambda replacements, assume_defaults: None)

    setup_agent.main(["Plant Analysis", "./plant-agent"])

    assert received == {"name": "Plant Analysis", "out": "./plant-agent", "yes": False}


def test_platform_env_path_points_at_monorepo_platform_dir():
    """The template lives at agent-template/ in the monorepo; the platform it
    copies secrets from is the sibling platform/ directory."""
    assert setup_agent.PLATFORM_ENV_PATH.name == ".env"
    assert (setup_agent.PLATFORM_ENV_PATH.parent / "docker-compose.yml").is_file()


def _agent_dir(tmp_path):
    agent_dir = tmp_path / "team-agent"
    agent_dir.mkdir()
    (agent_dir / "agent_card.json").write_text("{}", encoding="utf-8")
    return agent_dir


def test_env_only_writes_env_and_gitignore_for_existing_agent(tmp_path, monkeypatch):
    """A teammate's clone of the team repo gets a .env from their own platform."""
    platform_env = tmp_path / "platform.env"
    platform_env.write_text(
        "AGENT_SECRET=mine\nLOCAL_SDK=true\nLLM_API_KEY=sk-x\nEMBEDDING_API_KEY=sk-emb\n"
        "BACKEND_JWT_SECRET=platform-only\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", platform_env)
    agent_dir = _agent_dir(tmp_path)
    (agent_dir / ".env").write_text("AGENT_SECRET=owners\n", encoding="utf-8")

    setup_agent.main(["--env-only", str(agent_dir)])

    env = (agent_dir / ".env").read_text(encoding="utf-8")
    assert "AGENT_SECRET=mine" in env
    assert "owners" not in env
    assert "LOCAL_SDK=true" in env
    assert "LLM_API_KEY=sk-x" in env
    assert "EMBEDDING_API_KEY=sk-emb" in env
    assert "BACKEND_JWT_SECRET" not in env
    assert ".env" in (agent_dir / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_env_only_rejects_a_directory_without_agent_card(tmp_path, monkeypatch):
    platform_env = tmp_path / "platform.env"
    platform_env.write_text("AGENT_SECRET=mine\n", encoding="utf-8")
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", platform_env)

    with pytest.raises(SystemExit):
        setup_agent.main(["--env-only", str(tmp_path)])

    assert not (tmp_path / ".env").exists()


def test_env_only_takes_no_positional_arguments():
    with pytest.raises(SystemExit):
        setup_agent.parse_args(["--env-only", "x", "Plant Analysis"])


def test_yes_scaffolds_without_prompting(tmp_path, monkeypatch):
    """--yes creates the agent from defaults with no prompts and no leftover placeholders."""
    output_dir = tmp_path / "plant-agent"
    monkeypatch.setattr(setup_agent, "PLATFORM_ENV_PATH", tmp_path / "missing-platform.env")
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail(f"unexpected prompt: {prompt}"))

    setup_agent.main(["--yes", "Plant Analysis", str(output_dir)])

    agent_py = (output_dir / "agent.py").read_text()
    assert "class PlantAnalysisAgent" in agent_py
    assert "TEMPLATE_" not in agent_py


def test_yes_refuses_to_overwrite_an_existing_directory(tmp_path, monkeypatch):
    """--yes exits with an error and leaves an existing output directory untouched."""
    output_dir = tmp_path / "plant-agent"
    output_dir.mkdir()
    (output_dir / "keep.txt").write_text("mine")

    with pytest.raises(SystemExit) as excinfo:
        setup_agent.main(["--yes", "Plant Analysis", str(output_dir)])

    assert excinfo.value.code == 1
    assert (output_dir / "keep.txt").read_text() == "mine"


def test_yes_needs_the_agent_name():
    """--yes without an agent name is a usage error, since there is no default name."""
    with pytest.raises(SystemExit):
        setup_agent.parse_args(["--yes"])
