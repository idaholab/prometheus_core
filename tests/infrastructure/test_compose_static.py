"""Static validation of docker-compose.yml structure and service definitions."""

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
    assert infrastructure_services.issubset(defined), (
        f"Missing services: {infrastructure_services - defined}"
    )


def test_no_specialist_agents_in_base_compose(compose_data):
    """Specialist agents should only appear in docker-compose.agents.yml."""
    defined = set(compose_data["services"].keys())
    overlap = defined & SPECIALIST_AGENTS
    assert not overlap, f"Specialist agents in base compose: {overlap}"


def test_each_service_has_image_or_build(compose_data, infrastructure_services):
    for svc_name in infrastructure_services:
        svc = compose_data["services"][svc_name]
        assert "image" in svc or "build" in svc, (
            f"Service '{svc_name}' has neither 'image' nor 'build'"
        )


def test_postgres_image_version(compose_data):
    assert compose_data["services"]["litellm-db"]["image"] == "postgres:16-alpine"


def test_redis_image_version(compose_data):
    assert compose_data["services"]["redis"]["image"] == "redis:7-alpine"


def test_litellm_image_pinned(compose_data):
    image = compose_data["services"]["litellm"]["image"]
    assert ":latest" not in image, "LiteLLM image should be pinned, not :latest"
    assert ":" in image, "LiteLLM image should have an explicit tag"


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
    assert "redis-data" in volumes, "Missing 'redis-data' named volume"
    assert "litellm-db-data" in volumes, "Missing 'litellm-db-data' named volume"
