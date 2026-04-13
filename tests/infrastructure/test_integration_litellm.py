"""Integration tests for LiteLLM proxy container."""

import subprocess

import httpx
import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def litellm_base_url(docker_compose_up, env_test_file):
    """Return the base URL for the LiteLLM proxy."""
    env_vars = {}
    for line in env_test_file.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env_vars[k] = v
    port = env_vars.get("LITELLM_LOCAL_PORT", "19977")
    return f"http://localhost:{port}"


def test_litellm_container_running(docker_compose_up):
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", "litellm-proxy"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "running"


def test_litellm_container_healthy(docker_compose_up):
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", "litellm-proxy"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "healthy"


def test_litellm_health_liveliness(litellm_base_url):
    resp = httpx.get(f"{litellm_base_url}/health/liveliness", timeout=10)
    assert resp.status_code == 200


def test_litellm_health_readiness(litellm_base_url):
    resp = httpx.get(f"{litellm_base_url}/health/readiness", timeout=10)
    assert resp.status_code == 200


def test_litellm_requires_auth_for_protected_routes(litellm_base_url):
    """Protected routes should require Authorization header."""
    resp = httpx.get(f"{litellm_base_url}/key/info", timeout=10)
    assert resp.status_code in (401, 403), (
        f"Expected 401/403 without auth, got {resp.status_code}"
    )
