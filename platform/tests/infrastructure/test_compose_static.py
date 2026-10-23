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

"""Static validation of docker-compose.yml structure and service definitions."""

import yaml

SPECIALIST_AGENTS = {
    "artifact-debug-agent",
    "corrosion-agent",
    "data-agent",
    "form-filler-agent",
    "osti-research-agent",
    "radiation-agent",
    "synthesis-agent",
    "thermal-agent",
}


def test_compose_file_is_valid_yaml(compose_data):
    """docker-compose.yml parses without error and is a dict."""
    assert isinstance(compose_data, dict)


def test_compose_has_services_key(compose_data):
    assert "services" in compose_data


def test_infrastructure_services_defined(compose_data, infrastructure_services):
    """All five infrastructure services exist under 'services'."""
    defined = set(compose_data["services"].keys())
    assert infrastructure_services.issubset(defined), f"Missing services: {infrastructure_services - defined}"


def test_no_specialist_agents_in_base_compose(compose_data):
    """Specialist agents should only appear in docker-compose.agents.yml."""
    defined = set(compose_data["services"].keys())
    overlap = defined & SPECIALIST_AGENTS
    assert not overlap, f"Specialist agents in base compose: {overlap}"


def test_each_service_has_image_or_build(compose_data, infrastructure_services):
    for svc_name in infrastructure_services:
        svc = compose_data["services"][svc_name]
        assert "image" in svc or "build" in svc, f"Service '{svc_name}' has neither 'image' nor 'build'"


def test_postgres_image_version(compose_data):
    assert compose_data["services"]["litellm-db"]["image"] == "postgres:16-alpine"


def test_redis_service_uses_valkey_bundle(compose_data):
    svc = compose_data["services"]["redis"]
    assert svc["image"] == "valkey/valkey-bundle:9.1.0"
    assert svc["command"][:1] == ["valkey-server"]


def test_litellm_image_pinned(compose_data):
    image = compose_data["services"]["litellm"]["image"]
    assert image == "ghcr.io/berriai/litellm:v1.92.0", (
        "LiteLLM 1.92.0 is the minimum pinned gateway with A2A SDK v1 routing"
    )


def test_client_agent_receives_selectable_llm_configuration(compose_data):
    common_env = compose_data["x-common-env"]
    assert common_env["REGISTRY_URL"] == "${REGISTRY_URL:-http://litellm:4000}"
    assert "LLM_DEFAULT_MODEL" not in common_env
    assert "LLM_API_KEY" not in common_env
    assert "MODEL_NAME" not in common_env

    client_env = compose_data["services"]["client-agent"]["environment"]
    assert client_env["LLM_CONFIG_PROFILE"] == "${LLM_CONFIG_PROFILE:?set LLM_CONFIG_PROFILE in .env}"
    assert client_env["LLM_CONFIG_FILE"] == "${LLM_CONFIG_FILE:-}"
    for key in ("LLM_API_KEY", "EMBEDDING_API_KEY"):
        assert client_env[key] == f"${{{key}:-}}"

    proxy_env = compose_data["services"]["litellm"]["environment"]
    assert proxy_env["LLM_API_KEY"] == "${LLM_API_KEY}"


def test_client_agent_port_is_published_only_by_system_test_override(
    compose_data,
    project_root,
):
    assert "ports" not in compose_data["services"]["client-agent"]

    override_path = project_root / "docker-compose.system-test.yml"
    override = yaml.safe_load(override_path.read_text(encoding="utf-8"))
    assert override["services"]["client-agent"]["ports"] == ["${CLIENT_AGENT_PORT:-8001}:8000"]


def test_system_test_target_does_not_start_or_reconfigure_docker(project_root):
    makefile = (project_root / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("test-system:", 1)[1].split("\n\n", 1)[0]
    assert "docker" not in recipe.lower()
    assert "pytest -m system system" in recipe


def test_restart_policies(compose_data, infrastructure_services):
    for svc_name in infrastructure_services:
        svc = compose_data["services"][svc_name]
        assert svc.get("restart") == "unless-stopped", (
            f"Service '{svc_name}' restart policy is '{svc.get('restart')}', expected 'unless-stopped'"
        )


def test_compose_has_networks_section(compose_data):
    assert "networks" in compose_data


def test_compose_has_volumes_section(compose_data):
    volumes = compose_data.get("volumes", {})
    assert "valkey-data" in volumes, "Missing 'valkey-data' named volume"
    assert "litellm-db-data" in volumes, "Missing 'litellm-db-data' named volume"


def test_every_agent_sets_external_agent_url(project_root, compose_data):
    """Each agent registers http://<service-name>:8000, not a hostname-derived URL.

    PrometheusAgent's hostname fallback only works under Compose (hostname ==
    service name); on Kubernetes the hostname is the pod name, which isn't routable.
    """
    services = {"client-agent": compose_data["services"]["client-agent"]}
    for path in project_root.glob("agents/**/docker-compose.yml"):
        services.update(yaml.safe_load(path.read_text())["services"])

    wrong = {
        name: svc.get("environment", {}).get("EXTERNAL_AGENT_URL")
        for name, svc in services.items()
        if svc.get("environment", {}).get("EXTERNAL_AGENT_URL") != f"http://{name}:8000"
    }
    assert not wrong, f"EXTERNAL_AGENT_URL missing or not http://<service>:8000: {wrong}"
